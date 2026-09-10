-- =============================================================================
-- Storage buckets and row-level security.
--
-- This is an internal tool: the whole team may read and write everything, but
-- only through an authenticated session. The FastAPI backend uses the
-- service_role key and bypasses RLS entirely, which is why bulk import and
-- deck generation still work regardless of the policies below.
-- =============================================================================

-- ------------------------------------------------------------------- buckets
insert into storage.buckets (id, name, public, file_size_limit)
values
  ('building-images', 'building-images', true,  20 * 1024 * 1024),
  ('decks',           'decks',           false, 100 * 1024 * 1024),
  ('source-files',    'source-files',    false, 400 * 1024 * 1024)
on conflict (id) do nothing;

-- Building photographs are served straight into the UI and into generated
-- decks, so the bucket is public-read but write-restricted.
drop policy if exists "building images are publicly readable" on storage.objects;
create policy "building images are publicly readable"
  on storage.objects for select
  using (bucket_id = 'building-images');

drop policy if exists "authenticated users manage building images" on storage.objects;
create policy "authenticated users manage building images"
  on storage.objects for all
  to authenticated
  using (bucket_id = 'building-images')
  with check (bucket_id = 'building-images');

drop policy if exists "authenticated users read decks" on storage.objects;
create policy "authenticated users read decks"
  on storage.objects for select
  to authenticated
  using (bucket_id in ('decks', 'source-files'));

-- ----------------------------------------------------------------------- RLS
alter table micro_markets     enable row level security;
alter table organisations     enable row level security;
alter table buildings         enable row level security;
alter table spaces            enable row level security;
alter table building_images   enable row level security;
alter table contacts          enable row level security;
alter table ingest_jobs       enable row level security;
alter table source_documents  enable row level security;
alter table decks             enable row level security;

do $$
declare t text;
begin
  foreach t in array array[
    'micro_markets', 'organisations', 'buildings', 'spaces',
    'building_images', 'contacts', 'ingest_jobs', 'source_documents', 'decks'
  ] loop
    execute format('drop policy if exists "read for authenticated" on %I;', t);
    execute format(
      'create policy "read for authenticated" on %I
         for select to authenticated using (true);', t);

    execute format('drop policy if exists "write for authenticated" on %I;', t);
    execute format(
      'create policy "write for authenticated" on %I
         for all to authenticated using (true) with check (true);', t);
  end loop;
end $$;
