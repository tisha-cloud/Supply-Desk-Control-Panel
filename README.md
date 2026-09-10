# Bangalore Supply Desk

Commercial real-estate supply for Bengaluru: landlord documents in, one database in the
middle, client proposals out.

```
control-panel/     the web app - Next.js frontend and the Supabase schema  -> Vercel
backend/           the FastAPI service the app calls                       -> Render
extraction/        the landlord-document pipeline: PDFs, decks, spreadsheets, screenshots
LLM/               the PowerPoint generator that clones your options template
```

All four are one repository because `backend/` imports the other two at runtime:
`master_extract` and `extractor.*` from `extraction/`, `ai_client` and `ppt_generator`
from `LLM/`. Publishing any one of them alone gives you a service that fails on import.

The layout mirrors the deployment. `backend/` sits beside `control-panel/` rather than
inside it because Vercel treats any `main.py` plus `requirements.txt` under its root
directory as a second application to deploy, and offered to mount it at `/api/backend` -
the path of the Next.js route that attaches the caller session to every backend call.

**Start here:** [`control-panel/README.md`](control-panel/README.md) — what the app does,
how the schema is shaped, and how to run it.

**Deploying:** [`DEPLOY.md`](DEPLOY.md) — Vercel for the frontend, Render for the backend,
and why it cannot be Vercel alone.

## What is not in this repository

Deliberately gitignored, and not recoverable from a clone:

- `extraction/BLR_Builders_Developers_Supply/` — 465 MB of landlord documents, client-confidential.
- Source workbooks (`*.xlsx`) and `LLM/generated_decks/` — large binaries, regenerated on demand.
- Every `.env`. The `.env.example` files list what each one needs.

A clone is about 10 MB.
