-- =============================================================================
-- Let the browser read and write.
--
-- Migration 0002 granted every policy `to authenticated`. The control panel has
-- no sign-in screen, so the browser connects with the publishable key as the
-- `anon` role and matched no policy at all: PostgREST answered 200 with zero
-- rows and the UI reported "the database is empty" while 413 buildings sat in
-- the table. Only the backend, which uses the secret key and bypasses RLS,
-- could see anything.
--
-- READ THIS BEFORE RUNNING IT
-- ---------------------------
-- Granting `anon` full access means anyone holding the publishable key can read
-- and write this data. That key ships inside the browser bundle, so treat the
-- database as readable by anyone who can reach the app. That is usually fine
-- for an internal tool on a private network; it is not fine on the public
-- internet.
--
-- To lock it down later, either:
--   a) add Supabase Auth, drop the `anon` policies below, and keep 0002's
--      `authenticated` ones - the app then needs a login screen; or
--   b) route every write through the FastAPI backend (which already holds the
--      secret key) and leave the browser with read-only access.
-- =============================================================================

do $$
declare t text;
begin
  foreach t in array array[
    'micro_markets', 'organisations', 'buildings', 'spaces',
    'building_images', 'contacts', 'ingest_jobs', 'source_documents', 'decks'
  ] loop
    execute format('drop policy if exists "read for anon" on %I;', t);
    execute format(
      'create policy "read for anon" on %I
         for select to anon using (true);', t);

    execute format('drop policy if exists "write for anon" on %I;', t);
    execute format(
      'create policy "write for anon" on %I
         for all to anon using (true) with check (true);', t);
  end loop;
end $$;

-- The building editor uploads and deletes photographs straight from the
-- browser, so the same reasoning applies to the storage bucket.
drop policy if exists "anon manages building images" on storage.objects;
create policy "anon manages building images"
  on storage.objects for all
  to anon
  using (bucket_id = 'building-images')
  with check (bucket_id = 'building-images');

-- Generated decks stay private: they are downloaded through the backend, which
-- has the secret key, so `anon` gets no policy on that bucket.
