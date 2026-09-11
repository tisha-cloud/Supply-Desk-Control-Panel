"""
Control Panel backend.

A thin FastAPI service in front of the two Python projects that already exist:
the landlord-document extraction pipeline and the PPTX deck generator. The
Next.js app calls this; browsers talk to Supabase directly for ordinary CRUD.
"""
import os
import shutil
import threading
import traceback
import uuid
from typing import Any, Dict, List, Optional

import config  # must import first: it wires sys.path for the reused projects

from fastapi import (BackgroundTasks, Depends, FastAPI, File, Form, HTTPException,
                     UploadFile)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

import auth
import db
from auth import Caller, require, require_user

app = FastAPI(title="BLR Control Panel Backend", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-process job state, so the UI still shows progress when Supabase is not
# configured yet. Supabase remains the durable record when it is.
JOBS: Dict[str, Dict[str, Any]] = {}
_jobs_lock = threading.Lock()


def _set_job(job_id: str, **fields) -> None:
    with _jobs_lock:
        JOBS.setdefault(job_id, {"id": job_id, "log": []}).update(fields)


def _log(job_id: str, line: str) -> None:
    with _jobs_lock:
        JOBS.setdefault(job_id, {"id": job_id, "log": []})["log"].append(line)
    db.append_job_log(job_id, line)


# ============================================================ health / config
@app.get("/")
def root():
    """
    What this service is, for anyone who opens the base URL.

    A managed host probes / when it starts a service, and an operator checking
    a deployment tries it first. Answering 404 to both is needlessly confusing
    when a sentence will do.
    """
    return {
        "service": "Bangalore Supply Desk API",
        "docs": "/docs",
        "health": "/api/health",
        "note": "The web app is a separate deployment; this is only its backend.",
    }


@app.get("/api/health")
def health():
    from ai_client import AIClient
    provider = AIClient().get_active_provider()

    # True row counts, read with the secret key. The browser reads with the
    # publishable key under RLS, so comparing the two is how the UI tells
    # "genuinely empty" apart from "row-level security is blocking me".
    counts = {}
    if config.supabase_configured():
        try:
            sb = db.client()
            for table in ("buildings", "spaces", "building_images", "organisations"):
                counts[table] = sb.table(table).select("*", count="exact", head=True).execute().count
        except Exception:
            counts = {}

    return {
        "status": "ok",
        "row_counts": counts,
        "supabase_configured": config.supabase_configured(),
        # False until migration 0006 has been run. While it is false the
        # backend cannot identify callers and leaves every route open, so the
        # UI shows a banner rather than letting that pass unnoticed.
        "auth_ready": auth.auth_schema_ready(),
        "llm_provider": provider,
        "supply_dir": config.SUPPLY_DIR,
        "supply_dir_exists": os.path.isdir(config.SUPPLY_DIR),
        "templates": sorted(os.listdir(config.TEMPLATES_DIR))
                     if os.path.isdir(config.TEMPLATES_DIR) else [],
    }


# ================================================================= extraction
class ExtractionRequest(BaseModel):
    developer: Optional[str] = None
    limit: int = 0
    workers: int = 2
    cache_only: bool = False
    gapfill: bool = False


@app.post("/api/extraction/run", dependencies=[Depends(require("intake.run"))])
def start_extraction(request: ExtractionRequest, background: BackgroundTasks):
    """Kick off a pipeline run over the landlord supply folder."""
    if not config.supabase_configured():
        raise HTTPException(503, "Supabase is not configured; set it up before publishing data.")

    job_id = db.create_job("extraction", label=request.developer or "All landlords")
    _set_job(job_id, status="queued", kind="extraction")

    def work():
        from services import extraction_service
        try:
            _set_job(job_id, status="running")
            stats = extraction_service.run_extraction(
                job_id,
                developer_filter=request.developer,
                limit=request.limit,
                workers=request.workers,
                cache_only=request.cache_only,
                gapfill=request.gapfill,
            )
            _set_job(job_id, status="succeeded", stats=stats)
            db.update_job(job_id, status="succeeded", stats=stats, finished_at="now()")
        except Exception as exc:
            detail = traceback.format_exc(limit=3)
            _set_job(job_id, status="failed", error=str(exc))
            db.update_job(job_id, status="failed", error=detail[:4000], finished_at="now()")

    background.add_task(work)
    return {"job_id": job_id, "status": "queued"}


@app.post("/api/extraction/upload", dependencies=[Depends(require("intake.run"))])
async def upload_source_files(developer: str = Form(...),
                              files: List[UploadFile] = File(...),
                              supply_type: str = Form("")):
    """
    Add landlord documents to the supply folder so the next run picks them up.

    `supply_type` is what the operator says this stock is. The pipeline can
    infer a category from the document, but that is read out of prose; somebody
    who has opened the file knows, and what they declare wins.
    """
    from services import categories, extraction_service

    if supply_type and not categories.canonical_supply_type(supply_type):
        raise HTTPException(400, "Unknown supply_type: %s" % supply_type)

    staged = []
    temp_dir = os.path.join(config.UPLOAD_DIR, uuid.uuid4().hex)
    os.makedirs(temp_dir, exist_ok=True)
    try:
        for upload in files:
            path = os.path.join(temp_dir, os.path.basename(upload.filename or "file"))
            with open(path, "wb") as fh:
                shutil.copyfileobj(upload.file, fh)
            staged.append(path)
        target = extraction_service.stage_uploads(staged, developer, supply_type)
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

    return {"staged": len(staged), "developer": developer, "folder": target,
            "supply_type": categories.canonical_supply_type(supply_type)}


# ============================================== managed office workbook import
@app.post("/api/import/managed-xlsx", dependencies=[Depends(require("supply.import"))])
async def import_managed_workbook(background: BackgroundTasks,
                                  file: Optional[UploadFile] = File(None),
                                  server_path: Optional[str] = Form(None),
                                  upload_images: bool = Form(True),
                                  supply_type: str = Form("managed"),
                                  dry_run: bool = Form(False)):
    """
    Import the Managed Office Space workbook.

    The file is ~318MB, almost all of it embedded photographs, so it can also be
    imported by server path to avoid pushing it through the browser.
    """
    from services import categories
    canonical = categories.canonical_supply_type(supply_type)
    if not canonical:
        raise HTTPException(400, "Unknown supply_type: %s" % supply_type)
    # Managed and co-working are one listing category; the distinction is made
    # per requirement at proposal time, not per record at import time.
    supply_type = canonical
    if not config.supabase_configured() and not dry_run:
        raise HTTPException(503, "Supabase is not configured.")

    if server_path:
        xlsx_path = server_path
        if not os.path.isfile(xlsx_path):
            raise HTTPException(400, "No file at %s" % xlsx_path)
    elif file is not None:
        xlsx_path = os.path.join(config.UPLOAD_DIR, "%s_%s" % (
            uuid.uuid4().hex[:8], os.path.basename(file.filename or "workbook.xlsx")))
        with open(xlsx_path, "wb") as fh:
            shutil.copyfileobj(file.file, fh)
    else:
        raise HTTPException(400, "Provide either an uploaded file or a server_path.")

    # A dry run answers immediately - it is a parse check, not an ingest.
    if dry_run:
        from services import managed_xlsx
        stats = managed_xlsx.import_workbook(
            xlsx_path, None, upload_images=False,
            supply_type=supply_type, dry_run=True)
        return {"dry_run": True, "status": "succeeded", "stats": stats, "source": xlsx_path}

    job_id = db.create_job(
        "managed_xlsx", label="%s (%s)" % (os.path.basename(xlsx_path), supply_type))
    _set_job(job_id, status="queued", kind="managed_xlsx")

    def work():
        from services import managed_xlsx
        try:
            _set_job(job_id, status="running")
            stats = managed_xlsx.import_workbook(
                xlsx_path, job_id, upload_images=upload_images,
                supply_type=supply_type)
            _set_job(job_id, status="succeeded", stats=stats)
            db.update_job(job_id, status="succeeded", stats=stats, finished_at="now()")
        except Exception as exc:
            detail = traceback.format_exc(limit=3)
            _set_job(job_id, status="failed", error=str(exc))
            db.update_job(job_id, status="failed", error=detail[:4000], finished_at="now()")

    background.add_task(work)
    return {"job_id": job_id, "status": "queued", "source": xlsx_path}


# ====================================================================== jobs
@app.get("/api/jobs/{job_id}", dependencies=[Depends(require_user)])
def get_job(job_id: str):
    """Live job state: Supabase is authoritative, in-process state is a fallback."""
    record = None
    if config.supabase_configured():
        try:
            found = db.client().table("ingest_jobs").select("*").eq("id", job_id).limit(1).execute()
            record = found.data[0] if found.data else None
        except Exception:
            record = None
    if record is None:
        with _jobs_lock:
            record = JOBS.get(job_id)
    if record is None:
        raise HTTPException(404, "No such job")
    return record


@app.get("/api/jobs", dependencies=[Depends(require_user)])
def list_jobs(kind: Optional[str] = None, limit: int = 20):
    if not config.supabase_configured():
        with _jobs_lock:
            return list(JOBS.values())[-limit:]
    query = db.client().table("ingest_jobs").select("*").order("created_at", desc=True).limit(limit)
    if kind:
        query = query.eq("kind", kind)
    return query.execute().data or []


# ============================================================ de-duplication
class MergeRequest(BaseModel):
    keep_id: str
    merge_ids: List[str]


@app.get("/api/dedup/organisations", dependencies=[Depends(require("supply.read"))])
def list_duplicate_organisations():
    """Proposed merges. Nothing is applied until a human confirms one."""
    if not config.supabase_configured():
        raise HTTPException(503, "Supabase is not configured.")
    from services import dedup
    return dedup.duplicate_report()


@app.post("/api/dedup/organisations/merge", dependencies=[Depends(require("supply.merge"))])
def merge_duplicate_organisations(request: MergeRequest):
    if not config.supabase_configured():
        raise HTTPException(503, "Supabase is not configured.")
    from services import dedup
    try:
        return dedup.merge_organisations(request.keep_id, request.merge_ids)
    except Exception as exc:
        raise HTTPException(500, "Merge failed: %s" % exc)


# ====================================================================== decks
class DeckRequest(BaseModel):
    query: str
    client_name: Optional[str] = "Valued Client"
    template_name: Optional[str] = None
    building_ids: Optional[List[str]] = None
    # "pptx" for the client-facing proposal, "xlsx" for the same options as a
    # grid. Both are built from one shortlist.
    output_format: str = "pptx"


DECK_MEDIA_TYPES = {
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


@app.post("/api/decks/generate", dependencies=[Depends(require("proposals.write"))])
def generate_deck(request: DeckRequest):
    """Prompt in, .pptx or .xlsx out. Runs inline - it takes seconds."""
    if not config.supabase_configured():
        raise HTTPException(503, "Supabase is not configured.")
    from services import deck_service

    try:
        result = deck_service.generate(
            request.query,
            client_name=request.client_name or "Valued Client",
            template_name=request.template_name,
            building_ids=request.building_ids or None,
            output_format=request.output_format or "pptx",
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    except Exception as exc:
        raise HTTPException(500, "Deck generation failed: %s" % exc)

    deck_id = None
    storage_path = None
    try:
        with open(result["path"], "rb") as fh:
            data = fh.read()
        storage_path = "decks/%s" % result["filename"]
        media_type = DECK_MEDIA_TYPES.get(
            os.path.splitext(result["filename"])[1].lower(), "application/octet-stream")
        db.upload_bytes(config.BUCKET_DECKS, storage_path, data, media_type)
        created = db.client().table("decks").insert({
            "title": result["criteria"].get("title") or request.query[:80],
            "client_name": request.client_name,
            "prompt": request.query,
            "criteria": result["criteria"],
            "building_ids": result["building_ids"],
            "template_name": request.template_name or "options format.pptx",
            "storage_path": storage_path,
            "status": "succeeded",
        }).execute()
        deck_id = created.data[0]["id"] if created.data else None
    except Exception:
        pass  # the deck exists on disk even if recording it failed

    return {
        "deck_id": deck_id,
        "filename": result["filename"],
        "format": result.get("format", "pptx"),
        "options": result["options"],
        "criteria": result["criteria"],
        "building_ids": result["building_ids"],
        "storage_path": storage_path,
        "download_url": "/api/decks/download/%s" % result["filename"],
    }


@app.post("/api/decks/preview", dependencies=[Depends(require("proposals.write"))])
def preview_deck(request: DeckRequest):
    """Show which buildings a prompt would select, without building the file."""
    if not config.supabase_configured():
        raise HTTPException(503, "Supabase is not configured.")
    from services import deck_service

    from services import categories

    criteria = deck_service.parse_requirement(request.query)
    buildings = deck_service.shortlist(criteria)

    def summarise(building):
        vacant = building.get("_vacant") or []
        conditions = sorted({s.get("condition") for s in vacant if s.get("condition")})
        timelines = sorted({s.get("timeline") for s in vacant if s.get("timeline")})
        return {
            "id": building["id"],
            "name": building["name"],
            "micro_market": building.get("_micro_market"),
            "landlord": building.get("_landlord"),
            "available_sqft": building.get("_available_sqft"),
            "available_seats": building.get("_available_seats"),
            "rent_psf": building.get("_rent"),
            "price_per_seat": building.get("_seat_price"),
            "condition": ", ".join(conditions),
            "timeline": ", ".join(timelines),
            "options": len(vacant),
            "photos": len(building.get("building_images") or []),
            # How this option sits against the requirement: "meets", "short"
            # by `shortfall`, or "unknown" when the record carries no size.
            "fit": building.get("_fit"),
            "shortfall": building.get("_shortfall") or 0,
            "operator": building.get("_operator") or None,
            "developer": building.get("_developer") or None,
            # One listing category: a row still stored as `coworking` reads as
            # managed here so the reviewer sees the categories they know.
            "supply_type": categories.canonical_supply_type(building.get("supply_type")),
        }

    required, unit = deck_service.requirement_size(criteria)
    return {
        "criteria": criteria,
        "count": len(buildings),
        "required": required,
        "required_unit": unit,
        "meets": sum(1 for b in buildings if b.get("_fit") == "meets"),
        "product": criteria.get("product"),
        "product_label": criteria.get("product_label"),
        "product_note": criteria.get("product_note"),
        "buildings": [summarise(b) for b in buildings],
    }


@app.get("/api/decks/download/{filename}", dependencies=[Depends(require("proposals.read"))])
def download_deck(filename: str):
    path = os.path.join(config.DECK_DIR, os.path.basename(filename))
    if not os.path.isfile(path):
        legacy = os.path.join(config.LLM_DIR, "generated_decks", os.path.basename(filename))
        if os.path.isfile(legacy):
            path = legacy
        else:
            raise HTTPException(404, "Deck not found")
    return FileResponse(
        path, filename=os.path.basename(path),
        media_type=DECK_MEDIA_TYPES.get(
            os.path.splitext(path)[1].lower(), "application/octet-stream"))


@app.get("/api/templates", dependencies=[Depends(require_user)])
def list_templates():
    if not os.path.isdir(config.TEMPLATES_DIR):
        return []
    return sorted(f for f in os.listdir(config.TEMPLATES_DIR)
                  if f.lower().endswith((".pptx", ".potx")))


# ================================================================ user access
import routes_access  # noqa: E402  (imported late: it depends on `auth` and `db`)

app.include_router(routes_access.router)


@app.on_event("startup")
def bootstrap_first_admin():
    """
    Create the first administrator when the database has no users at all.

    Creating a user requires the user-management permission, so an empty
    profiles table has no way in. This runs only when that table is completely
    empty and never touches an existing account.
    """
    try:
        from services import users
        created = users.ensure_seed_admin()
    except Exception as exc:
        print("Could not seed the first administrator: %s" % exc)
        return
    if created:
        print("=" * 68)
        print("Created the first administrator: %s" % created["email"])
        print("Password: %s" % config.SEED_ADMIN_PASSWORD)
        print("Change it from User Access as soon as you have signed in.")
        print("=" * 68)


if __name__ == "__main__":
    import uvicorn
    print("Backend on http://%s:%d" % (config.HOST, config.PORT))
    # Reload is a development convenience and a production hazard: touching a
    # file restarts the worker, killing any in-flight import or extraction job
    # after replace_spaces has already deleted rows. Off unless asked for.
    uvicorn.run("main:app", host=config.HOST, port=config.PORT,
                reload=config.RELOAD)
