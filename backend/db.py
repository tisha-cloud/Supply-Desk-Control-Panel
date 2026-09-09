"""
Supabase access for the backend, plus the upsert helpers the two ingest paths
share.

The backend uses the service_role key, so it bypasses RLS. Nothing here should
ever be reachable from the browser directly - the Next.js app talks to this
service, and end users talk to Supabase with their own anon/authenticated key.
"""
import re
import threading
import unicodedata
from typing import Any, Dict, Iterable, List, Optional

import config

_client = None
_lock = threading.Lock()


class SupabaseUnavailable(RuntimeError):
    pass


def client():
    """Lazily build a singleton Supabase client."""
    global _client
    if not config.supabase_configured():
        raise SupabaseUnavailable(
            "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are not set. "
            "Copy backend/.env.example to backend/.env and fill them in."
        )
    with _lock:
        if _client is None:
            from supabase import create_client
            _client = create_client(config.SUPABASE_URL, config.SUPABASE_SERVICE_ROLE_KEY)
    return _client


# ------------------------------------------------------------------- helpers
def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return text or "unnamed"


def _clean(record: Dict[str, Any]) -> Dict[str, Any]:
    """Drop None values so a partial update never blanks an existing column."""
    return {k: v for k, v in record.items() if v is not None}


# --------------------------------------------------------------- reference data
def ensure_micro_market(code: str, name: Optional[str] = None) -> Optional[str]:
    if not code:
        return None
    sb = client()
    existing = sb.table("micro_markets").select("id").eq("code", code).limit(1).execute()
    if existing.data:
        return existing.data[0]["id"]
    created = sb.table("micro_markets").insert(
        {"code": code, "name": name or code}).execute()
    return created.data[0]["id"] if created.data else None


def ensure_organisation(name: str, role: str = "developer") -> Optional[str]:
    if not name or not str(name).strip():
        return None
    name = str(name).strip()
    slug = slugify(name)
    sb = client()
    existing = sb.table("organisations").select("id, role").eq("slug", slug).limit(1).execute()
    if existing.data:
        row = existing.data[0]
        # A landlord that both develops and operates should say so.
        if row.get("role") and row["role"] != role and row["role"] != "both":
            sb.table("organisations").update({"role": "both"}).eq("id", row["id"]).execute()
        return row["id"]
    created = sb.table("organisations").insert(
        {"name": name, "slug": slug, "role": role}).execute()
    return created.data[0]["id"] if created.data else None


# ------------------------------------------------------------------- buildings
def find_building(name: str, micro_market_id: Optional[str] = None,
                  developer_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """
    Match on the building's own name, narrowed by BOTH landlord and micro-market
    when they are known.

    Narrowing on the landlord alone is not enough: plenty of buildings are filed
    under a generic developer like "Independent", so "BHIVE Platinum" in
    Indiranagar would otherwise merge with the unrelated "BHIVE Platinum" in HSR
    Layout. Two buildings only count as the same asset when the name, the
    landlord and the micro-market all agree.
    """
    if not name:
        return None
    sb = client()
    query = sb.table("buildings").select("*").ilike("name", name.strip())
    if developer_id:
        query = query.eq("developer_id", developer_id)
    if micro_market_id:
        query = query.eq("micro_market_id", micro_market_id)
    found = query.limit(1).execute()
    if found.data:
        return found.data[0]

    # Fall back to a loose match within the same landlord only - matching across
    # landlords on name alone merges genuinely different assets.
    if developer_id:
        loose = (sb.table("buildings").select("*")
                 .eq("developer_id", developer_id)
                 .ilike("name", "%%%s%%" % name.strip()[:24])
                 .limit(1).execute())
        if loose.data:
            return loose.data[0]
    return None


def upsert_building(payload: Dict[str, Any]) -> str:
    """Insert or update a building, returning its id."""
    sb = client()
    name = (payload.get("name") or "").strip()
    if not name:
        raise ValueError("building payload has no name")

    existing = find_building(name, payload.get("micro_market_id"), payload.get("developer_id"))
    if existing:
        update = _clean(payload)
        update.pop("name", None)  # never rewrite the name we matched on
        if update:
            sb.table("buildings").update(update).eq("id", existing["id"]).execute()
        return existing["id"]

    record = _clean(payload)
    record.setdefault("slug", "%s-%s" % (slugify(name), slugify(payload.get("locality") or "blr"))[:80])
    # slug is unique; collisions get a numeric suffix rather than failing the run
    for attempt in range(5):
        try:
            created = sb.table("buildings").insert(record).execute()
            return created.data[0]["id"]
        except Exception as exc:
            if "duplicate key" in str(exc).lower() and attempt < 4:
                record["slug"] = "%s-%d" % (record["slug"][:70], attempt + 2)
                continue
            raise


def replace_spaces(building_id: str, spaces: List[Dict[str, Any]],
                   source_file: Optional[str] = None) -> int:
    """
    Swap in a fresh availability set for one building.

    Availability is a snapshot, not an accumulating log: re-importing July's
    file after June's must not leave June's vacant floors behind. Rows a human
    edited by hand are kept - see `is_verified` on the building.

    Callers must pass a building's WHOLE set for that source file in one go.
    Calling this once per option would delete the options written moments
    earlier, which is exactly how three operators in one tower became one.
    """
    sb = client()
    delete = sb.table("spaces").delete().eq("building_id", building_id)
    if source_file:
        delete = delete.eq("source_file", source_file)
    delete.execute()

    if not spaces:
        return 0
    rows = []
    for space in spaces:
        row = _clean(space)
        row["building_id"] = building_id
        if source_file:
            row.setdefault("source_file", source_file)
        rows.append(row)
    for chunk in _chunks(rows, 500):
        sb.table("spaces").insert(chunk).execute()
    return len(rows)


def upsert_contacts(contacts: Iterable[Dict[str, Any]],
                    building_id: Optional[str] = None,
                    organisation_id: Optional[str] = None) -> int:
    sb = client()
    written = 0
    for contact in contacts:
        email = (contact.get("email") or "").strip().lower() or None
        name = (contact.get("name") or "").strip() or None
        if not (email or name or contact.get("phone")):
            continue
        query = sb.table("contacts").select("id")
        query = query.eq("building_id", building_id) if building_id else query.is_("building_id", "null")
        if organisation_id:
            query = query.eq("organisation_id", organisation_id)
        if email:
            query = query.eq("email", email)
        elif name:
            query = query.eq("name", name)
        existing = query.limit(1).execute()

        record = _clean({
            "building_id": building_id,
            "organisation_id": organisation_id,
            "name": name,
            "designation": contact.get("designation"),
            "phone": contact.get("phone"),
            "email": email,
        })
        if existing.data:
            sb.table("contacts").update(record).eq("id", existing.data[0]["id"]).execute()
        else:
            sb.table("contacts").insert(record).execute()
        written += 1
    return written


# ---------------------------------------------------------------------- jobs
def create_job(kind: str, label: str = "", total_files: int = 0) -> str:
    created = client().table("ingest_jobs").insert({
        "kind": kind, "label": label, "total_files": total_files, "status": "queued",
    }).execute()
    return created.data[0]["id"]


def update_job(job_id: str, **fields) -> None:
    if not job_id:
        return
    try:
        client().table("ingest_jobs").update(_clean(fields)).eq("id", job_id).execute()
    except Exception:
        pass  # never let progress reporting kill the job it is reporting on


def append_job_log(job_id: str, line: str) -> None:
    if not job_id:
        return
    try:
        sb = client()
        current = sb.table("ingest_jobs").select("log").eq("id", job_id).limit(1).execute()
        log = (current.data[0].get("log") or "") if current.data else ""
        log = (log + line.rstrip() + "\n")[-20000:]
        sb.table("ingest_jobs").update({"log": log}).eq("id", job_id).execute()
    except Exception:
        pass


# -------------------------------------------------------------------- storage
def upload_bytes(bucket: str, path: str, data: bytes, content_type: str) -> str:
    """Upload and return the storage path. Overwrites an existing object."""
    storage = client().storage.from_(bucket)
    try:
        storage.upload(path, data, {"content-type": content_type, "upsert": "true"})
    except Exception as exc:
        if "already exists" not in str(exc).lower():
            raise
        storage.update(path, data, {"content-type": content_type})
    return path


def public_url(bucket: str, path: str) -> str:
    return client().storage.from_(bucket).get_public_url(path)


def signed_url(bucket: str, path: str, expires_in: int = 3600) -> str:
    result = client().storage.from_(bucket).create_signed_url(path, expires_in)
    return result.get("signedURL") or result.get("signedUrl") or ""


# ------------------------------------------------------- schema capability
_column_cache: Dict[str, bool] = {}


def has_column(table: str, column: str) -> bool:
    """
    Whether a column exists, cached per process.

    Lets an import run against a database that has not had the latest migration
    applied yet: the extra field is dropped rather than failing the whole run.
    """
    key = "%s.%s" % (table, column)
    if key in _column_cache:
        return _column_cache[key]
    try:
        client().table(table).select(column).limit(1).execute()
        _column_cache[key] = True
    except Exception:
        _column_cache[key] = False
    return _column_cache[key]


def _chunks(items: List[Any], size: int):
    for i in range(0, len(items), size):
        yield items[i:i + size]
