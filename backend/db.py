"""
Supabase access for the backend, plus the upsert helpers the two ingest paths
share.

The backend uses the service_role key, so it bypasses RLS. Nothing here should
ever be reachable from the browser directly - the Next.js app talks to this
service, and end users talk to Supabase with their own anon/authenticated key.
"""
import re
import threading
from difflib import SequenceMatcher
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
    """
    Drop values that mean "not found", so a re-import enriches rather than erases.

    None was already dropped, but the extractor fills its columns with empty
    strings rather than leaving them absent - so a second pass over a document
    that happened not to mention the power rating would have written "" over a
    figure somebody had recorded by hand. An empty string is never a fact worth
    keeping; clearing a field deliberately is done from the building editor,
    which writes to Supabase directly and does not come through here.
    """
    return {k: v for k, v in record.items()
            if v is not None and not (isinstance(v, str) and not v.strip())}


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

# LIKE treats % and _ as wildcards, so a building named "50% Block" would match
# far more than itself.
_LIKE_SPECIALS = {"%": r"\%", "_": r"\_", "\\": r"\\\\"}

# Two names have to be this close before they are treated as one building.
# The previous rule - a 24-character substring - merged genuinely different
# blocks of one park: "Bagmane World Technology Centre - Opal"[:24] also
# matches Aquamarine, Citrine and Peridot.
NAME_MATCH_THRESHOLD = 0.93


def like_escape(text):
    """Make a string safe to interpolate into an ilike pattern."""
    return "".join(_LIKE_SPECIALS.get(ch, ch) for ch in str(text or ""))


def _name_key(text):
    return re.sub(r"[^a-z0-9]+", " ", str(text or "").lower()).strip()


def _block_identifier(text):
    """
    The short trailing token that distinguishes one block from its siblings:
    "Wing D" -> "d", "WTC Block 5" -> "5". None when the name does not end in one.
    """
    key = _name_key(text)
    match = re.search(r"(?:block|wing|tower|phase|core|unit)\s+([a-z0-9]{1,3})$", key)
    if match:
        return match.group(1)
    match = re.search(r"\s([a-z0-9]{1,2})$", key)
    return match.group(1) if match else None


def same_building_name(left, right, threshold=NAME_MATCH_THRESHOLD):
    """
    Whether two building names refer to the same asset.

    Deliberately strict. A false merge silently destroys inventory - the
    survivor's fields are overwritten and the other block's availability is
    attached to the wrong building - whereas a false split shows up as a
    duplicate that a human can merge.

    A differing block identifier is decisive on its own: "Wing D" and "Wing E"
    are 97% similar as strings but are different buildings, and a ratio alone
    would merge every wing of a park into the first one seen.
    """
    a, b = _name_key(left), _name_key(right)
    if not a or not b:
        return False
    if a == b:
        return True

    block_a, block_b = _block_identifier(left), _block_identifier(right)
    if block_a and block_b and block_a != block_b:
        return False

    return SequenceMatcher(None, a, b).ratio() >= threshold


def find_building(name, micro_market_id=None, developer_id=None):
    """
    Find the building this record describes, or None.

    Identity requires the name, the landlord and the micro-market to agree.
    Narrowing on the landlord alone is not enough - plenty of buildings are
    filed under a generic developer like "Independent" - and the old loose
    fallback ignored the micro-market entirely, which merged seven genuinely
    different buildings across markets, including three separate
    "Salarpuria Magnificia" records in Indiranagar, ORR and Whitefield.
    """
    if not name:
        return None
    sb = client()
    name = str(name).strip()

    query = sb.table("buildings").select("*").ilike("name", like_escape(name))
    if developer_id:
        query = query.eq("developer_id", developer_id)
    if micro_market_id:
        query = query.eq("micro_market_id", micro_market_id)
    found = query.limit(1).execute()
    if found.data:
        return found.data[0]

    # Near-miss spellings, but only inside the same market: a different
    # micro-market means a different asset, whatever the name says.
    if not (developer_id or micro_market_id):
        return None
    candidates = sb.table("buildings").select("*")
    if developer_id:
        candidates = candidates.eq("developer_id", developer_id)
    if micro_market_id:
        candidates = candidates.eq("micro_market_id", micro_market_id)
    for row in (candidates.limit(200).execute().data or []):
        if same_building_name(name, row.get("name")):
            return row
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
