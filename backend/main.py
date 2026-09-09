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

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

import db

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


@app.post("/api/extraction/run")
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


@app.post("/api/extraction/upload")
async def upload_source_files(developer: str = Form(...),
                              files: List[UploadFile] = File(...)):
    """Add landlord documents to the supply folder so the next run picks them up."""
    from services import extraction_service

    staged = []
    temp_dir = os.path.join(config.UPLOAD_DIR, uuid.uuid4().hex)
    os.makedirs(temp_dir, exist_ok=True)
    try:
        for upload in files:
            path = os.path.join(temp_dir, os.path.basename(upload.filename or "file"))
            with open(path, "wb") as fh:
                shutil.copyfileobj(upload.file, fh)
            staged.append(path)
        target = extraction_service.stage_uploads(staged, developer)
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

    return {"staged": len(staged), "developer": developer, "folder": target}


# ============================================== managed office workbook import
@app.post("/api/import/managed-xlsx")
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
    if supply_type not in ("conventional", "managed", "coworking", "sale", "other"):
        raise HTTPException(400, "Unknown supply_type: %s" % supply_type)
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
@app.get("/api/jobs/{job_id}")
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


@app.get("/api/jobs")
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


@app.get("/api/dedup/organisations")
def list_duplicate_organisations():
    """Proposed merges. Nothing is applied until a human confirms one."""
    if not config.supabase_configured():
        raise HTTPException(503, "Supabase is not configured.")
    from services import dedup
    return dedup.duplicate_report()


@app.post("/api/dedup/organisations/merge")
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


@app.post("/api/decks/generate")
def generate_deck(request: DeckRequest):
    """Prompt in, .pptx out. Runs inline - a deck takes seconds, not minutes."""
    if not config.supabase_configured():
        raise HTTPException(503, "Supabase is not configured.")
    from services import deck_service

    try:
        result = deck_service.generate(
            request.query,
            client_name=request.client_name or "Valued Client",
            template_name=request.template_name,
            building_ids=request.building_ids or None,
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
        db.upload_bytes(config.BUCKET_DECKS, storage_path, data,
                        "application/vnd.openxmlformats-officedocument.presentationml.presentation")
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
        "options": result["options"],
        "criteria": result["criteria"],
        "building_ids": result["building_ids"],
        "storage_path": storage_path,
        "download_url": "/api/decks/download/%s" % result["filename"],
    }


@app.post("/api/decks/preview")
def preview_deck(request: DeckRequest):
    """Show which buildings a prompt would select, without building the file."""
    if not config.supabase_configured():
        raise HTTPException(503, "Supabase is not configured.")
    from services import deck_service

    criteria = deck_service.parse_requirement(request.query)
    buildings = deck_service.shortlist(criteria)
    return {
        "criteria": criteria,
        "count": len(buildings),
        "buildings": [{
            "id": b["id"],
            "name": b["name"],
            "micro_market": b.get("_micro_market"),
            "landlord": b.get("_landlord"),
            "available_sqft": b.get("_available_sqft"),
            "available_seats": b.get("_available_seats"),
            "rent_psf": b.get("_rent"),
            "supply_type": b.get("supply_type"),
        } for b in buildings],
    }


@app.get("/api/decks/download/{filename}")
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
        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation")


@app.get("/api/templates")
def list_templates():
    if not os.path.isdir(config.TEMPLATES_DIR):
        return []
    return sorted(f for f in os.listdir(config.TEMPLATES_DIR)
                  if f.lower().endswith((".pptx", ".potx")))


if __name__ == "__main__":
    import uvicorn
    print("Backend on http://%s:%d" % (config.HOST, config.PORT))
    uvicorn.run("main:app", host=config.HOST, port=config.PORT, reload=True)
