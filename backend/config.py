"""
Backend configuration and the sys.path wiring that lets this service reuse the
existing extraction and deck-generation code without copying it.

The two Python projects already living in this repo stay where they are:
    ../../extraction   the landlord-document pipeline (PyMuPDF colour reading,
                       Gemini client, occupancy derivation)
    ../../LLM          the PPTX generator that clones 'options format.pptx'
"""
import os
import sys

from dotenv import load_dotenv

BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
CONTROL_PANEL_DIR = os.path.dirname(BACKEND_DIR)
PROJECT_ROOT = os.path.dirname(CONTROL_PANEL_DIR)

EXTRACTION_DIR = os.path.join(PROJECT_ROOT, "extraction")
LLM_DIR = os.path.join(PROJECT_ROOT, "LLM")

# Load .env from the backend, then fall back to the extraction project's .env
# so the Gemini key only has to be configured in one place.
load_dotenv(os.path.join(BACKEND_DIR, ".env"))
load_dotenv(os.path.join(EXTRACTION_DIR, ".env"))

for path in (EXTRACTION_DIR, LLM_DIR):
    if os.path.isdir(path) and path not in sys.path:
        sys.path.insert(0, path)

# ------------------------------------------------------------------- storage
WORK_DIR = os.path.join(BACKEND_DIR, ".work")
UPLOAD_DIR = os.path.join(WORK_DIR, "uploads")
DECK_DIR = os.path.join(WORK_DIR, "decks")
for _d in (WORK_DIR, UPLOAD_DIR, DECK_DIR):
    os.makedirs(_d, exist_ok=True)

SUPPLY_DIR = os.path.join(EXTRACTION_DIR, "BLR_Builders_Developers_Supply")
TEMPLATES_DIR = os.path.join(LLM_DIR, "templates")

# ------------------------------------------------------------------ supabase
# Supabase is migrating its key names: legacy projects issue a service_role
# JWT, newer ones an `sb_secret_...` key. Either grants the server-side access
# this backend needs (bulk ingest bypasses RLS), so accept both spellings.
SUPABASE_URL = (os.getenv("SUPABASE_URL") or os.getenv("NEXT_PUBLIC_SUPABASE_URL") or "").strip()
SUPABASE_SERVICE_ROLE_KEY = (
    os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    or os.getenv("SUPABASE_SECRET_KEY")
    or ""
).strip()

BUCKET_IMAGES = "building-images"
BUCKET_DECKS = "decks"
BUCKET_SOURCES = "source-files"

# Host/port the service binds to. Configurable because a crashed uvicorn can
# leave port 8000 held by an unkillable process until the machine restarts.
HOST = os.getenv("BACKEND_HOST", "127.0.0.1").strip()
PORT = int(os.getenv("BACKEND_PORT", "8000"))

# ---------------------------------------------------------------------- misc
ALLOWED_ORIGINS = [
    o.strip() for o in
    os.getenv("ALLOWED_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000").split(",")
    if o.strip()
]


def supabase_configured() -> bool:
    return bool(SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY)
