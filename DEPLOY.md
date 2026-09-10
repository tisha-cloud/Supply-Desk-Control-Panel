# Deploying

Two hosts, because the two halves have genuinely different needs.

| Half | Host | Why |
|---|---|---|
| Next.js app (`control-panel/`) | **Vercel** | It is a Next.js app; Vercel builds and serves it with no configuration. |
| FastAPI backend (`control-panel/backend/`) | **Render** (or Railway / Fly) | Long-running jobs, ~400 MB of native dependencies, and a writable disk. None of that fits a serverless function. |

## Why not Vercel alone

Vercel can run Python, but not this Python:

- **Time.** A workbook import parses 318 MB and an extraction run walks dozens of
  documents. Vercel functions cap at 300 seconds even on Pro; both routinely exceed it.
- **Size.** PyMuPDF, pandas, Pillow and python-pptx together blow past the 250 MB
  unzipped bundle limit.
- **State.** Job progress lives in an in-process dict, and generated files are written to
  disk. Serverless functions share neither between invocations.

Everything on **Render alone** would work — it can host the Next.js app too — but you
would give up Vercel's build pipeline, preview deployments and edge caching for the
frontend, and gain nothing. Two hosts, one free-tier-ish bill.

---

## 1. Push to GitHub

The whole repository goes, not just `control-panel/`. The backend imports `master_extract`
and `extractor.*` from `extraction/`, and `ai_client` and `ppt_generator` from `LLM/`;
publishing the control panel alone produces a service that fails at import.

It is small: **123 files, about 10 MB.** The 465 MB of landlord documents and the 83 MB of
generated decks are gitignored and stay on your machine.

```bash
# Create an empty PRIVATE repository on github.com first - no README, no
# .gitignore, no licence - then:
git remote add origin https://github.com/<you>/<repo>.git
git branch -M main
git push -u origin main
```

Keep it **private**. The repository holds no keys, but it does hold the shape of your
supply data and your client-facing templates.

---

## 2. Backend on Render

**New → Blueprint → pick this repository.** Render reads `render.yaml`, builds
`control-panel/backend/Dockerfile` with the repository root as its context, and prompts
for the values below. Alternatively, **New → Web Service → Docker** and set the Dockerfile
path by hand.

| Variable | Value |
|---|---|
| `SUPABASE_URL` | `https://<project>.supabase.co` |
| `SUPABASE_SECRET_KEY` | the `sb_secret_…` key. Bypasses row-level security — server only |
| `SUPABASE_PUBLISHABLE_KEY` | the `sb_publishable_…` key, used only to validate access tokens |
| `SEED_ADMIN_EMAIL` / `SEED_ADMIN_PASSWORD` | the first administrator. **Set a real password here** rather than deploying with `admin123` |
| `ALLOWED_ORIGINS` | your Vercel domain |
| `GEMINI_API_KEY` | extraction, until the Claude migration lands |

Health check is `/api/health`. It should answer `supabase_configured: true`,
`auth_ready: true` and real `row_counts`.

Note the plan: **Starter, not Free.** A free service sleeps after inactivity, and a cold
start during an import kills the job after `replace_spaces` has already deleted rows.

---

## 3. Frontend on Vercel

**Add New → Project → import the repository**, then:

| Setting | Value |
|---|---|
| **Root Directory** | `control-panel` ← the one setting that is easy to miss |
| Framework | Next.js (detected) |
| Build / install | defaults |

### Deploy only the Next.js app

Importing the repository, Vercel scans it and may offer **two** applications: the Next.js
frontend at `/`, and a FastAPI backend at `/api/backend` that it infers from
`control-panel/backend/`. **Deploy only the frontend.**

`/api/backend` is already a Next.js route handler - the proxy that reads the caller session
from cookies and attaches it as a bearer token. A FastAPI deployment winning that path
would send every backend call out unauthenticated, which looks like a broken backend rather
than a routing mistake.

`control-panel/.vercelignore` hides `backend/` so it is not detected on a fresh import. If
you are mid-import and both are already listed, remove the FastAPI one by hand.

Environment variables:

| Variable | Value |
|---|---|
| `NEXT_PUBLIC_SUPABASE_URL` | `https://<project>.supabase.co` |
| `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY` | the `sb_publishable_…` key |
| `BACKEND_URL` | `https://supply-desk-api.onrender.com` — no trailing slash |

`BACKEND_URL` is deliberately not `NEXT_PUBLIC_`. The browser never calls the backend
directly; every call goes through `/api/backend/*`, which runs server-side, attaches the
caller's Supabase token and forwards it. That is also what makes a plain download link
work — a browser navigation sends cookies but never an `Authorization` header.

If it is missing, the proxy says so by name rather than reporting an unreachable
`127.0.0.1`.

### Function timeout

The proxy is capped at **60 seconds**, the Hobby ceiling — asking for more fails the build.
It has to cover a cold start on the backend host, which on a free Render instance can take
most of a minute by itself. On Pro, raise it to 300 in both `vercel.json` and the
`maxDuration` export in `src/app/api/backend/[...path]/route.ts`; a workbook import needs
the headroom.

Then set `ALLOWED_ORIGINS` on Render to the Vercel domain and redeploy.

### AUTH_SETUP_MODE

Leave it unset. It exists only for a database where migration `0006` has not been run and
which therefore has no accounts: without it the sign-in gate strands you at a form nobody
can satisfy. Setting it to `1` opens every page to anyone who can reach the deployment.

The gate defaults to enforcing and never asks the backend whether to. An earlier version
probed the backend on each cold start and treated an unreachable one as "authentication is
not set up" — so a serverless instance that could not reach a sleeping backend inside its
timeout let everyone through.

---

## 4. Supabase

Run every migration in `control-panel/supabase/migrations/` from the SQL editor, oldest
first. `0006` is the one that switches authentication on; until it has run the app is open
to anyone who can reach it, and says so.

In **Authentication → URL Configuration**, set the Site URL to your Vercel domain.

---

## Order

1. Supabase migrations (including `0006`).
2. Render — note the URL it gives you.
3. Vercel with `BACKEND_URL` set to that URL.
4. `ALLOWED_ORIGINS` on Render → the Vercel domain.
5. Sign in as the seed administrator and change the password.

---

## Known limits of this deployment

Honest list of what does not yet work once hosted, none of which blocks day-to-day use:

- **Importing the 318 MB workbook by server path.** The Import panel reads the file from
  the machine the backend runs on. On Render that file does not exist, and it cannot be
  pushed through Vercel either (4.5 MB request limit). Until browser → Supabase Storage
  upload is built, import it from a local backend against the same Supabase project — the
  data lands in the same database.
- **The bundled supply directory.** `extraction/BLR_Builders_Developers_Supply/` is
  gitignored, so `/api/health` reports `supply_dir_exists: false` and the "re-read
  everything" sweep has nothing to sweep. Uploading documents through Document Intake
  works normally.
- **One worker.** Job progress is an in-process dict, so `WEB_CONCURRENCY` must stay at 1
  until job state moves entirely into Supabase.
- **Generated files.** Decks are written to the mounted disk and uploaded to Storage, but
  `download` still serves from disk. Losing the disk loses the local copies, not the
  Storage ones.

---

## Running it locally after all this

Unchanged:

```bash
cd control-panel/backend && python main.py     # BACKEND_RELOAD=1 for hot reload
cd control-panel && npm run dev
```

Hot reload is now opt-in. It used to be always on, which meant any file touch restarted
the worker and killed in-flight import jobs.
