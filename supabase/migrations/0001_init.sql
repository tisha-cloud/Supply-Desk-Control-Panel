-- =============================================================================
-- BLR Commercial Real Estate Control Panel - core schema
--
-- One database serves all three features:
--   1. the extraction pipeline (landlord PDFs/decks -> buildings + spaces)
--   2. the Managed Office Space workbook import (+ its embedded photographs)
--   3. the LLM deck generator, which only ever reads from here
--
-- Both supply types share `buildings`: a tower is the same physical asset
-- whether it is let conventionally by the floor or operated as managed office
-- by the seat. What differs is the availability record, which lives in
-- `spaces`.
-- =============================================================================

create extension if not exists "uuid-ossp";
create extension if not exists pg_trgm;   -- fuzzy building-name matching on import

-- --------------------------------------------------------------- enumerations
do $$ begin
  create type supply_type as enum ('conventional', 'managed', 'sale', 'other');
exception when duplicate_object then null; end $$;

do $$ begin
  create type occupancy_status as enum ('available', 'occupied', 'unknown');
exception when duplicate_object then null; end $$;

do $$ begin
  create type asset_type as enum
    ('office', 'retail', 'industrial', 'warehouse', 'land', 'residential', 'mixed');
exception when duplicate_object then null; end $$;

do $$ begin
  create type org_role as enum ('developer', 'operator', 'both');
exception when duplicate_object then null; end $$;

do $$ begin
  create type job_status as enum ('queued', 'running', 'succeeded', 'failed', 'cancelled');
exception when duplicate_object then null; end $$;

-- ------------------------------------------------------------- micro-markets
create table if not exists micro_markets (
  id          uuid primary key default uuid_generate_v4(),
  code        text not null unique,          -- 'CBD', 'ORR', 'WF', 'North-BLR'
  name        text not null,
  city        text not null default 'Bengaluru',
  sort_order  int  not null default 100,
  created_at  timestamptz not null default now()
);

-- ------------------------------------------------- developers and operators
-- WeWork and Table Space operate; Prestige and Bagmane develop; some do both.
create table if not exists organisations (
  id          uuid primary key default uuid_generate_v4(),
  name        text not null,
  slug        text not null unique,
  role        org_role not null default 'developer',
  website     text,
  notes       text,
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now()
);
create index if not exists organisations_name_trgm on organisations using gin (name gin_trgm_ops);

-- ------------------------------------------------------------------ buildings
create table if not exists buildings (
  id                      uuid primary key default uuid_generate_v4(),
  name                    text not null,
  slug                    text unique,
  address                 text,
  locality                text,                -- raw locality as printed in the source
  city                    text not null default 'Bengaluru',
  micro_market_id         uuid references micro_markets(id) on delete set null,
  developer_id            uuid references organisations(id) on delete set null,
  operator_id             uuid references organisations(id) on delete set null,
  supply_type             supply_type not null default 'conventional',
  asset_type              asset_type  not null default 'office',

  structure               text,                -- '2B + G + 19'
  total_size_sqft         numeric,
  total_size_is_estimated boolean not null default false,
  total_size_basis        text,                -- which label/arithmetic produced it
  avg_floor_plate_sqft    numeric,
  floor_plate_efficiency  text,
  power_kva               text,
  power_backup            text,
  car_parking_ratio       text,
  oc_available            boolean,
  building_details        text,
  latitude                numeric,
  longitude               numeric,

  -- provenance: which document last told us about this building
  source_file             text,
  report_period           text,                -- 'July 2026'
  disclosure_mode         text,                -- full_stack | available_only | unknown

  is_verified             boolean not null default false,  -- a human has checked it
  created_at              timestamptz not null default now(),
  updated_at              timestamptz not null default now()
);
create index if not exists buildings_micro_market  on buildings(micro_market_id);
create index if not exists buildings_developer     on buildings(developer_id);
create index if not exists buildings_operator      on buildings(operator_id);
create index if not exists buildings_supply_type   on buildings(supply_type);
create index if not exists buildings_name_trgm     on buildings using gin (name gin_trgm_ops);

-- --------------------------------------------------------------------- spaces
-- One row per floor (conventional) or per offered option (managed office).
create table if not exists spaces (
  id                 uuid primary key default uuid_generate_v4(),
  building_id        uuid not null references buildings(id) on delete cascade,

  option_label       text,                    -- 'Option 1' on the managed sheet
  floor_label        text,                    -- 'GF', '12F', 'Balance Floors'
  area_sqft          numeric,
  seats              int,                     -- managed office sells seats
  condition          text,                    -- Warm Shell / Pre - Furnished / ...
  condition_detail   text,
  timeline           text,                    -- Immediate / Occupied / 'Q3 2026'
  occupancy          occupancy_status not null default 'unknown',

  -- commercials
  rent_psf           numeric,
  cam_psf            numeric,
  price_per_seat     numeric,
  parking_charges    text,
  rental_escalation  text,
  deposit_months     numeric,
  lease_tenure_months numeric,
  lock_in_months     numeric,
  notice_months      numeric,
  commercial_terms   text,

  -- a derived "Balance Floors" row is never a real listing; keep it labelled
  is_derived         boolean not null default false,
  derivation_note    text,

  source_file        text,
  evidence           text,                    -- 'p.12 availability table'
  notes              text,
  created_at         timestamptz not null default now(),
  updated_at         timestamptz not null default now()
);
create index if not exists spaces_building   on spaces(building_id);
create index if not exists spaces_occupancy  on spaces(occupancy);
create index if not exists spaces_derived    on spaces(is_derived);

-- --------------------------------------------------------------------- images
-- Photographs live in Supabase Storage; this table holds the pointer plus
-- whatever a human adds by hand afterwards.
create table if not exists building_images (
  id           uuid primary key default uuid_generate_v4(),
  building_id  uuid not null references buildings(id) on delete cascade,
  storage_path text not null,                 -- bucket-relative, e.g. 'buildings/<id>/img1.png'
  caption      text,
  kind         text default 'perspective',    -- perspective | floor_plan | location_map | other
  sort_order   int not null default 0,
  is_primary   boolean not null default false,
  width        int,
  height       int,
  bytes        bigint,
  source_file  text,
  created_at   timestamptz not null default now()
);
create index if not exists building_images_building on building_images(building_id);
-- at most one primary image per building
create unique index if not exists building_images_one_primary
  on building_images(building_id) where is_primary;

-- ------------------------------------------------------------------- contacts
create table if not exists contacts (
  id              uuid primary key default uuid_generate_v4(),
  organisation_id uuid references organisations(id) on delete cascade,
  building_id     uuid references buildings(id) on delete cascade,
  name            text,
  designation     text,
  phone           text,
  email           text,
  is_primary      boolean not null default false,
  created_at      timestamptz not null default now(),
  constraint contacts_need_an_owner
    check (organisation_id is not null or building_id is not null)
);
create index if not exists contacts_organisation on contacts(organisation_id);
create index if not exists contacts_building     on contacts(building_id);

-- ------------------------------------------------------------ ingestion jobs
-- Backs the progress UI for both the extraction run and the workbook import.
create table if not exists ingest_jobs (
  id            uuid primary key default uuid_generate_v4(),
  kind          text not null,                -- 'extraction' | 'managed_xlsx'
  status        job_status not null default 'queued',
  label         text,
  total_files   int  not null default 0,
  done_files    int  not null default 0,
  buildings_upserted int not null default 0,
  spaces_upserted    int not null default 0,
  images_uploaded    int not null default 0,
  stats         jsonb not null default '{}'::jsonb,
  error         text,
  log           text,
  started_at    timestamptz,
  finished_at   timestamptz,
  created_at    timestamptz not null default now()
);
create index if not exists ingest_jobs_kind_created on ingest_jobs(kind, created_at desc);

-- Every source document we have read, so coverage is auditable.
create table if not exists source_documents (
  id            uuid primary key default uuid_generate_v4(),
  job_id        uuid references ingest_jobs(id) on delete set null,
  filename      text not null,
  rel_path      text,
  sha1          text,
  kind          text,                          -- PDF | XLSX | PPTX | IMAGE
  developer     text,
  report_period text,
  status        text,                          -- EXTRACTED | NO DATA | DUPLICATE | ...
  detail        text,
  bytes         bigint,
  created_at    timestamptz not null default now()
);
create index if not exists source_documents_sha1 on source_documents(sha1);

-- --------------------------------------------------------------------- decks
create table if not exists decks (
  id             uuid primary key default uuid_generate_v4(),
  title          text not null,
  client_name    text,
  prompt         text,                         -- what the user actually typed
  criteria       jsonb not null default '{}'::jsonb,   -- parsed filters
  building_ids   uuid[] not null default '{}',
  template_name  text,
  storage_path   text,                         -- generated .pptx in Storage
  slide_count    int,
  status         job_status not null default 'queued',
  error          text,
  created_at     timestamptz not null default now()
);
create index if not exists decks_created on decks(created_at desc);

-- ----------------------------------------------------------------- timestamps
create or replace function touch_updated_at() returns trigger as $$
begin
  new.updated_at = now();
  return new;
end $$ language plpgsql;

do $$
declare t text;
begin
  foreach t in array array['organisations', 'buildings', 'spaces'] loop
    execute format(
      'drop trigger if exists %I_touch on %I;
       create trigger %I_touch before update on %I
       for each row execute function touch_updated_at();', t, t, t, t);
  end loop;
end $$;

-- ------------------------------------------------------------ derived views
-- The occupied/available split, per building, including derived balance rows.
create or replace view building_availability as
select
  b.id                                                        as building_id,
  b.name,
  b.supply_type,
  mm.code                                                     as micro_market,
  coalesce(dev.name, op.name)                                  as landlord,
  b.total_size_sqft,
  sum(s.area_sqft) filter (where s.occupancy = 'available')    as available_sqft,
  sum(s.area_sqft) filter (where s.occupancy = 'occupied')     as occupied_sqft,
  sum(s.seats)     filter (where s.occupancy = 'available')    as available_seats,
  count(*)         filter (where s.occupancy = 'available')    as available_units,
  count(*)                                                     as total_units
from buildings b
left join spaces s          on s.building_id = b.id
left join micro_markets mm  on mm.id = b.micro_market_id
left join organisations dev on dev.id = b.developer_id
left join organisations op  on op.id  = b.operator_id
group by b.id, b.name, b.supply_type, mm.code, dev.name, op.name;
