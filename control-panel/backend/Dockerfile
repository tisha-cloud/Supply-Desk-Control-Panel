# The FastAPI backend, with the two projects it imports.
#
# Build from the REPOSITORY ROOT, not from this directory:
#
#     docker build -f control-panel/backend/Dockerfile -t supply-desk-api .
#
# config.py puts ../../extraction and ../../LLM on sys.path, so the image keeps
# the same three-directory layout the checkout has. Copying the backend alone
# would produce a container that fails at import: main.py needs ai_client from
# LLM/, extraction_service needs master_extract and extractor.* from
# extraction/, and the deck generator needs the .pptx template.

FROM python:3.12-slim

# PyMuPDF, Pillow and pandas all publish manylinux wheels, so no compiler is
# needed. curl is here for the container health check.
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl \
 && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Dependencies first: this layer is rebuilt only when requirements change.
COPY control-panel/backend/requirements.txt ./control-panel/backend/requirements.txt
RUN pip install --no-cache-dir -r control-panel/backend/requirements.txt \
 && pip install --no-cache-dir "gunicorn==23.0.0"

# The two sibling projects. Their heavy inputs - landlord documents, source
# workbooks, generated decks - are gitignored and never enter the image; only
# the code and the .pptx template do.
COPY LLM/ ./LLM/
COPY extraction/ ./extraction/
COPY control-panel/backend/ ./control-panel/backend/

WORKDIR /app/control-panel/backend

# 0.0.0.0 because 127.0.0.1 inside a container is unreachable from outside it.
# One worker: job progress lives in an in-process dict, so a second worker
# would answer job polls that know nothing about the running job.
ENV BACKEND_HOST=0.0.0.0 \
    BACKEND_PORT=8000 \
    WEB_CONCURRENCY=1

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD curl -fsS "http://127.0.0.1:${BACKEND_PORT}/api/health" || exit 1

# Gunicorn for process supervision, uvicorn workers for ASGI. The long timeout
# is deliberate: a workbook import holds its request open while it parses.
CMD ["sh", "-c", "gunicorn main:app \
  --worker-class uvicorn.workers.UvicornWorker \
  --workers ${WEB_CONCURRENCY} \
  --bind ${BACKEND_HOST}:${BACKEND_PORT} \
  --timeout 600 \
  --graceful-timeout 30 \
  --access-logfile - \
  --error-logfile -"]
