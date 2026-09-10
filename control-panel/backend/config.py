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

# Captured before any .env is read. Render, Railway and Heroku inject PORT into
# the real environment and expect the service to bind to it - but extraction/.env
# also defines a PORT for its own standalone server, and that file is loaded
# below. Reading the platform value first keeps the two from colliding.
_PLATFORM_PORT = os.environ.get("PORT")

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

# The publishable key. The backend does not need it for data access, but the
# Auth API requires an apikey header when it validates a user's access token.
SUPABASE_PUBLISHABLE_KEY = (
    os.getenv("SUPABASE_PUBLISHABLE_KEY")
    or os.getenv("SUPABASE_ANON_KEY")
    or os.getenv("NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY")
    or os.getenv("NEXT_PUBLIC_SUPABASE_ANON_KEY")
    or SUPABASE_SERVICE_ROLE_KEY
).strip()

# Where the project publishes the keys that sign access tokens. Derived from
# the project URL unless overridden.
SUPABASE_JWKS_URL = (
    os.getenv("SUPABASE_JWKS_URL")
    or ("%s/auth/v1/.well-known/jwks.json" % SUPABASE_URL.rstrip("/") if SUPABASE_URL else "")
).strip()

# The first administrator, created on first start when no users exist yet.
# Change the password from the User Access screen once you are signed in.
SEED_ADMIN_EMAIL = os.getenv("SEED_ADMIN_EMAIL", "admin@gmail.com").strip()
SEED_ADMIN_PASSWORD = os.getenv("SEED_ADMIN_PASSWORD", "admin123")

BUCKET_IMAGES = "building-images"
BUCKET_DECKS = "decks"
BUCKET_SOURCES = "source-files"

# Host/port the service binds to. Configurable because a crashed uvicorn can
# leave port 8000 held by an unkillable process until the machine restarts.
HOST = os.getenv("BACKEND_HOST", "127.0.0.1").strip()
# BACKEND_PORT wins when set explicitly; otherwise take whatever the host
# assigned. A managed host picks the port, so ignoring it would bind the
# service where the platform is not listening and the deploy would time out.
PORT = int(os.getenv("BACKEND_PORT") or _PLATFORM_PORT or 8000)

# Hot reload. Development only - a file touch restarts the worker and kills any
# in-flight import mid-write. Deployments leave this unset.
RELOAD = os.getenv("BACKEND_RELOAD", "").strip().lower() in ("1", "true", "yes")

# ---------------------------------------------------------------------- misc
ALLOWED_ORIGINS = [
    o.strip() for o in
    os.getenv("ALLOWED_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000").split(",")
    if o.strip()
]


def supabase_configured() -> bool:
    return bool(SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY)
