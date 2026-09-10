-- =============================================================================
-- Authentication, roles and per-role permissions.
--
-- Migration 0004 granted the `anon` role full read and write on every table so
-- the browser could work without a login screen. That is now replaced: every
-- policy below requires an authenticated session, and what that session may do
-- is decided by the permissions attached to its role.
--
-- Three moving parts:
--
--   permissions  a fixed catalogue of the things this app can do. Seeded here
--                so the user-management screen can list them with descriptions
--                rather than hard-coding a list in the browser bundle.
--
--   roles        a named set of permissions. `admin` holds the wildcard '*' and
--                is marked is_system, so it can never be edited or deleted into
--                a state where nobody can administer the tool. Every other role
--                is created and edited by an admin at runtime.
--
--   profiles     one row per auth user, carrying the role and an active flag.
--                Created automatically by a trigger when a user is added.
--
-- The permission check runs inside Postgres, not in the browser. Hiding a
-- button is a courtesy; `has_perm` is the thing that actually stops a viewer
-- deleting a building from the browser console.
-- =============================================================================

-- ----------------------------------------------------------- the catalogue
create table if not exists public.permissions (
  key         text primary key,
  label       text not null,
  description text not null,
  category    text not null default 'General',
  sort_order  int  not null default 0
);

insert into public.permissions (key, label, description, category, sort_order) values
  ('supply.read',    'View supply',        'See buildings, availability, photographs and contacts.', 'Supply', 10),
  ('supply.write',   'Edit supply',        'Add and change buildings, availability, contacts and photographs.', 'Supply', 20),
  ('supply.delete',  'Delete supply',      'Permanently remove buildings and availability rows.', 'Supply', 30),
  ('supply.import',  'Import workbooks',   'Load a supply workbook, including its embedded photographs.', 'Supply', 40),
  ('supply.merge',   'Merge landlords',    'Fold duplicate landlord and operator records into one.', 'Supply', 50),
  ('intake.run',     'Run document intake','Upload landlord documents and run the extraction pipeline.', 'Intake', 60),
  ('proposals.read', 'View proposals',     'See proposals that have been built.', 'Proposals', 70),
  ('proposals.write','Build proposals',    'Match a requirement and produce a PowerPoint or Excel proposal.', 'Proposals', 80),
  ('users.manage',   'Manage user access', 'Create users, assign roles, and define what each role may do.', 'Administration', 90)
on conflict (key) do update
  set label = excluded.label,
      description = excluded.description,
      category = excluded.category,
      sort_order = excluded.sort_order;

-- ---------------------------------------------------------------- the roles
create table if not exists public.roles (
  key         text primary key,
  name        text not null,
  description text,
  -- '*' means every permission, present and future. Only `admin` holds it.
  permissions text[] not null default '{}',
  -- A system role cannot be renamed, re-scoped or deleted. Without this, an
  -- admin could remove their own last route back into user management.
  is_system   boolean not null default false,
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now()
);

insert into public.roles (key, name, description, permissions, is_system) values
  ('admin', 'Administrator',
   'Full access to everything, including user management. Cannot be edited or deleted.',
   array['*'], true),
  ('editor', 'Editor',
   'Reads and edits supply, runs document intake, and builds proposals. Cannot delete or manage users.',
   array['supply.read', 'supply.write', 'supply.import', 'supply.merge',
         'intake.run', 'proposals.read', 'proposals.write'], false),
  ('viewer', 'Viewer',
   'Read-only. Sees supply and proposals but changes nothing.',
   array['supply.read', 'proposals.read'], false)
on conflict (key) do nothing;

-- Keep the wildcard on admin even if an earlier run seeded it differently.
update public.roles set permissions = array['*'], is_system = true where key = 'admin';

-- ------------------------------------------------------------- the profiles
create table if not exists public.profiles (
  id         uuid primary key references auth.users(id) on delete cascade,
  email      text not null,
  full_name  text,
  role_key   text not null default 'viewer' references public.roles(key) on update cascade,
  -- Deactivating keeps the audit trail that deleting would destroy, and takes
  -- effect immediately: every policy below tests it.
  is_active  boolean not null default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists profiles_role_idx on public.profiles (role_key);

-- A user created through the Supabase Admin API gets a profile automatically,
-- so the two can never drift apart. The role travels in user metadata.
create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
  insert into public.profiles (id, email, full_name, role_key)
  values (
    new.id,
    coalesce(new.email, ''),
    nullif(new.raw_user_meta_data ->> 'full_name', ''),
    coalesce(
      (select key from public.roles
        where key = new.raw_user_meta_data ->> 'role'),
      'viewer')
  )
  on conflict (id) do update
    set email = excluded.email,
        full_name = coalesce(excluded.full_name, public.profiles.full_name);
  return new;
end;
$$;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
  after insert on auth.users
  for each row execute function public.handle_new_user();

-- Backfill anyone who signed up before this migration ran.
insert into public.profiles (id, email, role_key)
select u.id, coalesce(u.email, ''), 'viewer'
  from auth.users u
 where not exists (select 1 from public.profiles p where p.id = u.id);

-- ------------------------------------------------------- the permission check
--
-- SECURITY DEFINER matters here. These functions read `profiles` and `roles`,
-- and the policies on `profiles` call them in turn. Running as the table owner
-- bypasses RLS inside the function, which is what stops that becoming infinite
-- recursion.

create or replace function public.current_permissions()
returns text[]
language sql
stable
security definer
set search_path = public
as $$
  select coalesce(r.permissions, '{}')
    from public.profiles p
    join public.roles r on r.key = p.role_key
   where p.id = auth.uid()
     and p.is_active;
$$;

create or replace function public.has_perm(perm text)
returns boolean
language sql
stable
security definer
set search_path = public
as $$
  select coalesce(
    exists (
      select 1
        from public.profiles p
        join public.roles r on r.key = p.role_key
       where p.id = auth.uid()
         and p.is_active
         and (r.permissions @> array['*'] or r.permissions @> array[perm])
    ), false);
$$;

create or replace function public.is_admin()
returns boolean
language sql
stable
security definer
set search_path = public
as $$
  select public.has_perm('users.manage');
$$;

grant execute on function public.current_permissions() to authenticated;
grant execute on function public.has_perm(text) to authenticated;
grant execute on function public.is_admin() to authenticated;

-- ============================================================== the policies
--
-- Everything 0004 opened to `anon` is closed again first.

do $$
declare t text;
begin
  foreach t in array array[
    'micro_markets', 'organisations', 'buildings', 'spaces',
    'building_images', 'contacts', 'ingest_jobs', 'source_documents', 'decks'
  ] loop
    execute format('drop policy if exists "read for anon" on %I;', t);
    execute format('drop policy if exists "write for anon" on %I;', t);
    execute format('drop policy if exists "read for authenticated" on %I;', t);
    execute format('drop policy if exists "write for authenticated" on %I;', t);
    execute format('drop policy if exists "all for authenticated" on %I;', t);
  end loop;
end $$;

drop policy if exists "anon manages building images" on storage.objects;

-- Supply tables: read, write and delete are three separate permissions, so a
-- role can be given editing rights without the ability to destroy anything.
do $$
declare t text;
begin
  foreach t in array array[
    'micro_markets', 'organisations', 'buildings', 'spaces',
    'building_images', 'contacts', 'source_documents'
  ] loop
    execute format('drop policy if exists "supply read" on %I;', t);
    execute format(
      'create policy "supply read" on %I for select to authenticated
         using (public.has_perm(''supply.read''));', t);

    execute format('drop policy if exists "supply insert" on %I;', t);
    execute format(
      'create policy "supply insert" on %I for insert to authenticated
         with check (public.has_perm(''supply.write''));', t);

    execute format('drop policy if exists "supply update" on %I;', t);
    execute format(
      'create policy "supply update" on %I for update to authenticated
         using (public.has_perm(''supply.write''))
         with check (public.has_perm(''supply.write''));', t);

    execute format('drop policy if exists "supply delete" on %I;', t);
    execute format(
      'create policy "supply delete" on %I for delete to authenticated
         using (public.has_perm(''supply.delete''));', t);
  end loop;
end $$;

-- Job history is a read-only record in the browser; the backend writes it with
-- the secret key, which bypasses RLS entirely.
drop policy if exists "jobs read" on ingest_jobs;
create policy "jobs read" on ingest_jobs for select to authenticated
  using (public.has_perm('supply.read') or public.has_perm('intake.run'));

drop policy if exists "decks read" on decks;
create policy "decks read" on decks for select to authenticated
  using (public.has_perm('proposals.read'));

drop policy if exists "decks write" on decks;
create policy "decks write" on decks for all to authenticated
  using (public.has_perm('proposals.write'))
  with check (public.has_perm('proposals.write'));

-- ------------------------------------------------------- roles and profiles
grant select on public.permissions to authenticated;
grant select on public.roles to authenticated;
grant insert, update, delete on public.roles to authenticated;
grant select, insert, update, delete on public.profiles to authenticated;

alter table public.permissions enable row level security;
alter table public.roles       enable row level security;
alter table public.profiles    enable row level security;

drop policy if exists "permissions are readable" on public.permissions;
create policy "permissions are readable" on public.permissions
  for select to authenticated using (true);

-- Every signed-in user may read the roles: the UI needs the current user's own
-- permission list to decide what to render. Only user managers may change them.
drop policy if exists "roles are readable" on public.roles;
create policy "roles are readable" on public.roles
  for select to authenticated using (true);

drop policy if exists "roles are managed by admins" on public.roles;
create policy "roles are managed by admins" on public.roles
  for all to authenticated
  using (public.has_perm('users.manage') and not is_system)
  with check (public.has_perm('users.manage') and not is_system);

-- A user always sees their own profile - that is how the app knows who they
-- are. Seeing everyone else requires the user-management permission.
drop policy if exists "profiles are self-readable" on public.profiles;
create policy "profiles are self-readable" on public.profiles
  for select to authenticated
  using (id = auth.uid() or public.has_perm('users.manage'));

drop policy if exists "profiles are managed by admins" on public.profiles;
create policy "profiles are managed by admins" on public.profiles
  for all to authenticated
  using (public.has_perm('users.manage'))
  with check (public.has_perm('users.manage'));

-- ------------------------------------------------------------------ storage
drop policy if exists "authenticated users manage building images" on storage.objects;
drop policy if exists "building images are written by editors" on storage.objects;
create policy "building images are written by editors"
  on storage.objects for insert to authenticated
  with check (bucket_id = 'building-images' and public.has_perm('supply.write'));

drop policy if exists "building images are replaced by editors" on storage.objects;
create policy "building images are replaced by editors"
  on storage.objects for update to authenticated
  using (bucket_id = 'building-images' and public.has_perm('supply.write'))
  with check (bucket_id = 'building-images' and public.has_perm('supply.write'));

drop policy if exists "building images are removed by deleters" on storage.objects;
create policy "building images are removed by deleters"
  on storage.objects for delete to authenticated
  using (bucket_id = 'building-images' and public.has_perm('supply.delete'));

drop policy if exists "authenticated users read decks" on storage.objects;
create policy "authenticated users read decks"
  on storage.objects for select to authenticated
  using (
    (bucket_id = 'decks' and public.has_perm('proposals.read'))
    or (bucket_id = 'source-files' and public.has_perm('supply.read'))
  );

-- ------------------------------------------------------------- housekeeping
create or replace function public.touch_updated_at()
returns trigger language plpgsql as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

drop trigger if exists roles_touch on public.roles;
create trigger roles_touch before update on public.roles
  for each row execute function public.touch_updated_at();

drop trigger if exists profiles_touch on public.profiles;
create trigger profiles_touch before update on public.profiles
  for each row execute function public.touch_updated_at();

comment on table public.roles is
  'A named set of permissions. admin holds the wildcard and is immutable.';
comment on table public.profiles is
  'One row per auth user: which role they hold and whether they are still active.';
comment on function public.has_perm(text) is
  'True when the current session holds this permission, or the admin wildcard.';
