# BLR Control Panel

One Supabase database behind three tools:

| Feature | What it does | Where it runs |
|---|---|---|
| **Extraction** | Reads landlord PDFs, decks, spreadsheets and screenshots into the database, deriving occupied space from what each document withholds | Python pipeline in `../extraction` |
| **Supply Database** | Imports the Managed Office Space workbook with its embedded photographs, then full CRUD by hand | Next.js ↔ Supabase directly |
| **Deck Builder** | Plain-English requirement → shortlist you can edit → `.pptx` on your options template, or the same options as `.xlsx` | Python generator in `../LLM` |

```
        ┌── Extraction ──┐
raw landlord files ──────┤
                         ├──▶  SUPABASE  ◀── Managed Office xlsx + manual CRUD
        ┌── Deck Builder ┘        │
prompt ─┴──▶ queries the DB ──────┘
             └─▶ generates .pptx
```

Nothing was rewritten: the extraction pipeline and the deck generator stay in Python
(PyMuPDF for colour-coded vacancy detection, `python-pptx` for template cloning). The
Next.js app is the interface and the CRUD surface; a thin FastAPI service exposes the
two Python projects to it.

---

## Setup

### 1. Supabase

Create a project at [supabase.com](https://supabase.com/dashboard), then run every
migration from the SQL editor, oldest first:

```
supabase/migrations/0001_init.sql             -- tables, views, triggers
supabase/migrations/0002_rls_and_storage.sql  -- buckets and row-level security
supabase/migrations/0003_space_operator.sql   -- operator per suite, not per tower
supabase/migrations/0004_anon_access.sql      -- browser access before login exists
supabase/migrations/0005_three_categories.sql -- fold co-working into managed
```

### 2. Credentials

Two files, because the browser and the backend use different keys.

```bash
cp .env.local.example .env.local          # NEXT_PUBLIC_SUPABASE_URL + publishable key
cp backend/.env.example backend/.env      # SUPABASE_URL + secret key
```

Supabase is midway through renaming its keys, and both naming schemes are accepted:

| Where | New name | Legacy name |
|---|---|---|
| `.env.local` | `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY` | `NEXT_PUBLIC_SUPABASE_ANON_KEY` |
| `backend/.env` | `SUPABASE_SECRET_KEY` | `SUPABASE_SERVICE_ROLE_KEY` |

The publishable/anon key is safe in the browser and governed by RLS. The secret/service-role
key bypasses RLS and must stay server-side — it is only ever read by the FastAPI backend.

The Gemini key is picked up automatically from `../extraction/.env`; it does not need
repeating.

### 3. Install and run

```bash
# Terminal 1 - backend
cd backend
pip install -r requirements.txt
python main.py                     # http://127.0.0.1:8000

# Terminal 2 - frontend
npm install
npm run dev                        # http://localhost:3000
```

Or `npm run dev:all` to start both at once.

---

## Loading the data

**Managed Office workbook** — Supply Database tab. Pick the category to tag the file as
(it defaults to Managed), then use **Check without importing** first: that parses the
whole workbook and reports what it would create without writing anything. The file is
~318 MB and almost entirely embedded photographs, so it is read from disk by path rather
than uploaded through the browser. The importer walks the `.xlsx` zip directly (worksheet → drawing →
anchor → media part), which is why it maps all 438 images in well under a second
without loading the workbook into memory. Anchor columns identify which option each
photograph belongs to.

Untick *Upload embedded photographs* for a fast, data-only import; the images account
for roughly a third of Supabase's 1 GB free tier.

**Landlord documents** — Extraction tab. Upload files under a landlord name, then run
the pipeline. Documents are deduplicated by content hash, and older monthly editions of
the same report are superseded automatically.

> Extraction is gated by the Gemini free-tier quota: **20 requests per day, per model**.
> A full 66-file run needs to spread across several models. Tick *Replay cached results
> only* to rebuild from stored responses without spending any quota.

---

## Schema

### The three categories

`supply_type` on each building is **`conventional`**, **`managed`** or **`sale`**.

Managed and co-working are one category, not two. The listing is identical — the same
operator, the same centre, the same seats — and which product a client is buying depends
only on the size of the requirement that walks in the door:

| Requirement | Quoted as |
|---|---|
| fewer than 15 seats | Co-working |
| 15 seats or more | Managed office |

So the product name belongs to the *requirement*, and the Deck Builder applies it when the
proposal is written. Keeping it on the building made the two categories impossible to tell
apart when editing — the same Table Space centre could be filed either way depending on who
typed it in — and a co-working filter then hid managed stock that was equally available.

What the operator does in general is still recorded, on the organisation rather than the
building: `organisations.offers_managed` / `offers_coworking`, as Yes / Limited / No. Table
Space is managed-only; 91Springboard is coworking-first; WeWork does both.

> The `coworking` enum value survives so that a row restored from a pre-`0005` backup still
> loads. Nothing writes it, and `services/categories.py` (backend) and `src/lib/supply.ts`
> (browser) fold it into `managed` on read.

`buildings` is the shared physical asset — a tower is the same building whether it is
let conventionally by the floor or operated as managed office by the seat. What differs
is the availability record in `spaces`, which carries either `area_sqft` or `seats`.

| Table | Holds |
|---|---|
| `buildings` | the asset: address, structure, total size, floor plate, power, parking, OC |
| `spaces` | one row per floor (conventional) or per option (managed), with `occupancy` |
| `building_images` | Storage pointers, one primary per building |
| `contacts` | per building or per organisation |
| `organisations` | developers and operators (`role` can be `both`) |
| `micro_markets` | CBD, ORR, WF, North-BLR … |
| `ingest_jobs`, `source_documents` | run progress and file-level coverage |
| `decks` | every generated deck, its prompt and the buildings it used |

Two flags are worth respecting when reading the data:

- `spaces.is_derived` — a `Balance Floors` row computed as *total − listed available*,
  not something any document stated. `derivation_note` records the arithmetic.
- `buildings.total_size_is_estimated` — the total was reconstructed from floor plate ×
  levels because no document stated one. `total_size_basis` records how.

Re-importing replaces a building's spaces for that source file rather than appending,
so last month's vacant floors do not linger after this month's report lands.

### Operator names

The supply sheets name operators loosely — 56 distinct labels for 31 real companies
(`Wework` vs `WeWork India`, `UV` for Urban Vault, sub-brands like `BHIVE Platinum` and
`315Work Avenue DLR1`). The importer resolves them against the workbook's own Operators
sheet and keeps the sub-brand in `buildings.operator_brand`, so the operator list stays
clean without losing the product line.

---

## Editing the data

The Supply Database tab is the working surface:

- **Category tabs** across the top filter to Conventional / Managed & Co-working / Sale,
  each with a live count.
- **Tick rows** to select buildings, then move them between categories in bulk or delete
  them. This is the fast way to split an imported workbook if part of it is really
  conventional or for sale.
- **A building page** edits every field inline. Availability rows, contacts and
  photographs each add/edit/delete in place and save on blur; `Ctrl+S` saves the form,
  and navigating away with unsaved edits warns first.
- Derived rows stay labelled: a `Balance Floors` row is marked *derived*, and a
  reconstructed building size shows a banner naming the arithmetic behind it.

---

## Building a proposal

The Deck Builder tab is one pass with a review step in the middle:

1. **Describe the requirement** in plain English. The model turns it into filters — micro-market,
   area or headcount, condition, budget, landlord — and those filters query the database.
2. **Read what it decided.** The interpreted filters are shown as chips, and a seat requirement
   states which product it will be quoted as and why (see the table above).
3. **Edit the shortlist.** Remove any option the model picked, reorder the ones that stay, and
   restore anything you removed by mistake. The table shows availability, price, condition,
   timeline and whether a photograph exists, so an option can be judged without leaving the page.
4. **Pick a format.** *PowerPoint proposal* renders your options template; *Excel sheet* writes
   the same options as a filterable grid with a cover sheet naming the client and the brief.
   Both are built from the same shortlist, so no figure can differ between them, and you can
   make both.

Every number comes from the database. The model chooses *which* options to show and writes the
narrative copy; it is never the source of a figure.

---

## Troubleshooting

### "Supabase is not configured on the backend"

The backend reads `backend/.env` **once, at import time**. A backend process
started before that file existed - or before you last edited it - keeps
reporting `supabase_configured: false` no matter what the file now says.

Check which backend the app is actually talking to:

```bash
curl http://127.0.0.1:8000/api/health
```

If the response has no `row_counts` field, it is running code older than that
diagnostic and needs restarting.

On Windows a uvicorn process killed uncleanly can leave the port bound under a
PID that no longer resolves: `netstat` still lists it, `Stop-Process` reports
"cannot find a process with the process identifier", and the socket keeps
answering. Nothing but a reboot frees it. Until then, move the backend:

```
backend/.env      BACKEND_PORT=8100
.env.local        BACKEND_URL=http://127.0.0.1:8100
```

Both files are read at startup, so restart the backend and the Next.js server
after changing them.

### The page shows an old build

`next start` serves the `.next` directory as it was when the process started.
If you rebuilt while it was running, stop it and start it again.
