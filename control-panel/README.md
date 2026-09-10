# Bangalore Supply Desk

One Supabase database behind three tools, each named for what it does:

| Screen | What it does | Where it runs |
|---|---|---|
| **Document Intake** | Reads landlord PDFs, decks, spreadsheets and screenshots into the database, deriving occupied space from what each document withholds | Python pipeline in `../extraction` |
| **Supply Inventory** | Imports the supply workbook with its embedded photographs, then full CRUD by hand | Next.js ↔ Supabase directly |
| **Proposal Builder** | Plain-English requirement → shortlist you can edit → `.pptx` on your options template, or the same options as `.xlsx` | Python generator in `../LLM` |
| **User Access** | People, roles, and what each role is permitted to do | FastAPI ↔ Supabase Auth |

```
     ┌── Document Intake ──┐
raw landlord files ────────┤
                           ├──▶  SUPABASE  ◀── supply workbook + manual CRUD
     ┌── Proposal Builder ─┘        │
prompt ─┴──▶ queries the DB ────────┘
             └─▶ .pptx or .xlsx
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
supabase/migrations/0006_auth_and_roles.sql   -- sign-in, roles, permissions
```

`0006` replaces the open `anon` access from `0004`. Until you run it the app has no
sign-in at all and every screen is open to anyone who can reach it — the User Access
screen and a badge in the header both say so.

### 2. Credentials

Two files, because the browser and the backend use different keys.

```bash
cp .env.local.example .env.local             # NEXT_PUBLIC_SUPABASE_URL + publishable key
cp ../backend/.env.example ../backend/.env   # SUPABASE_URL + secret key
```

The backend lives at `../backend`, beside this directory rather than inside it: Vercel
builds the Next.js app from here, and treats any `main.py` plus `requirements.txt` beneath
its root as a second application to deploy.

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
cd ../backend
pip install -r requirements.txt
python main.py                     # http://127.0.0.1:8000

# Terminal 2 - frontend
npm install
npm run dev                        # http://localhost:3000
```

Or `npm run dev:all` to start both at once.

---

## Signing in and user access

### The first administrator

When `0006` has run and the `profiles` table is empty, the backend creates one account on
startup and prints it:

```
admin@gmail.com  /  admin123
```

That is the only account that is ever created automatically, and only into a database with
no users at all — it can never overwrite or resurrect a real one. **Change the password from
User Access as soon as you have signed in**, or set `SEED_ADMIN_EMAIL` and
`SEED_ADMIN_PASSWORD` in `backend/.env` before the first start.

Everyone else is created by an administrator: **User Access → People → Add person**, with a
name, an email, a temporary password and a role. There is no self-signup and no invitation
email, because no mail server is configured.

### Roles and permissions

A role is a named set of permissions. Three are seeded:

| Role | Holds |
|---|---|
| **Administrator** | Everything, including user management. Built in — cannot be edited or deleted. |
| **Editor** | Read and edit supply, import workbooks, merge landlords, run intake, build proposals. No deleting, no user management. |
| **Viewer** | Read-only: sees supply and proposals, changes nothing. |

Create your own on **User Access → Roles**: name it, tick what it may do, save. The
permissions are:

| Permission | Lets someone |
|---|---|
| `supply.read` | See buildings, availability, photographs and contacts |
| `supply.write` | Add and change them |
| `supply.delete` | Permanently remove buildings and availability rows |
| `supply.import` | Load a supply workbook |
| `supply.merge` | Fold duplicate landlord records together |
| `intake.run` | Upload landlord documents and run the pipeline |
| `proposals.read` | See and download proposals |
| `proposals.write` | Match a requirement and build one |
| `users.manage` | Create users and define roles |

Only `admin` holds the wildcard `*`, which covers permissions added by future features. A
role you create cannot be given it: that would be a second all-powerful role which, being
editable, could be scoped away.

### What actually enforces this

Three layers, and only the first two are security:

1. **Row-level security in Postgres.** Every table policy calls `has_perm(...)`. A viewer
   who opens the browser console and runs `supabase.from("buildings").delete()` is refused
   by the database.
2. **Permission guards on the FastAPI routes.** The backend holds the secret key and
   bypasses RLS by design, so each route declares the permission it needs and verifies the
   caller's Supabase token against the project key set.
3. **Hidden controls in the UI.** A courtesy, so nobody is offered a button that will fail.

The tool refuses to leave itself unadministrable: the last administrator cannot be deleted,
deactivated or demoted, a built-in role cannot be edited, and a role still held by someone
cannot be deleted.

---

## Loading the data

**Managed Office workbook** — Supply Inventory tab. Pick the category to tag the file as
(it defaults to Managed), then use **Check without importing** first: that parses the
whole workbook and reports what it would create without writing anything. The file is
~318 MB and almost entirely embedded photographs, so it is read from disk by path rather
than uploaded through the browser. The importer walks the `.xlsx` zip directly (worksheet → drawing →
anchor → media part), which is why it maps all 438 images in well under a second
without loading the workbook into memory. Anchor columns identify which option each
photograph belongs to.

Untick *Upload embedded photographs* for a fast, data-only import; the images account
for roughly a third of Supabase's 1 GB free tier.

**Landlord documents** — Document Intake tab. Upload files under a landlord name, then run
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

So the product name belongs to the *requirement*, and the Proposal Builder applies it when the
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

The Supply Inventory tab is the working surface:

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

The Proposal Builder tab is one pass with a review step in the middle:

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
