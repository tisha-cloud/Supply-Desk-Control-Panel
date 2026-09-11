-- =============================================================================
-- Pincode to micro-market, as data rather than as code.
--
-- Demography profiling turns a list of employee pincodes into the micro-market
-- most of them live nearest. That mapping started as a table inside
-- services/demography.py, which was fine for getting it working and wrong to
-- keep: the desk knows Bengaluru far better than the code does, the list needs
-- extending as areas are added, and a correction should not need a deploy.
--
-- The Python table remains as the seed. It is copied in on first use and never
-- again, so anything edited here stands.
-- =============================================================================

create table if not exists public.pincode_areas (
  pincode      text primary key,
  -- What the area is commonly called. Shown beside every classification so a
  -- wrong one is visible on screen rather than buried in a total.
  locality     text not null,
  -- Must name a row in micro_markets. A pincode pointing at a market that does
  -- not exist is a recommendation pointing nowhere.
  micro_market text not null references public.micro_markets(code)
               on update cascade,
  -- 'seed' for the rows copied from the code, 'import' for a bulk upload,
  -- 'manual' for a row edited by hand. Lets a re-seed leave real edits alone.
  source       text not null default 'manual',
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now()
);

create index if not exists pincode_areas_market_idx
  on public.pincode_areas (micro_market);

comment on table public.pincode_areas is
  'Employee pincode to micro-market, used by demography profiling to pick the '
  'location most of a workforce lives nearest.';

drop trigger if exists pincode_areas_touch on public.pincode_areas;
create trigger pincode_areas_touch before update on public.pincode_areas
  for each row execute function public.touch_updated_at();

-- ----------------------------------------------------------------- access
alter table public.pincode_areas enable row level security;

grant select on public.pincode_areas to authenticated;
grant insert, update, delete on public.pincode_areas to authenticated;

-- Anyone who can build a proposal needs to read the mapping, because it is
-- what turns their pincode list into an answer.
drop policy if exists "pincode areas are readable" on public.pincode_areas;
create policy "pincode areas are readable" on public.pincode_areas
  for select to authenticated
  using (public.has_perm('proposals.read') or public.has_perm('proposals.write'));

-- Changing it changes where clients are told to sit, so it is an edit to the
-- supply data rather than a proposal action.
drop policy if exists "pincode areas are edited by editors" on public.pincode_areas;
create policy "pincode areas are edited by editors" on public.pincode_areas
  for all to authenticated
  using (public.has_perm('supply.write'))
  with check (public.has_perm('supply.write'));
