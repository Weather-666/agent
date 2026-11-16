-- Personal and team Library metadata. Object storage owns bytes, never authorization.
create table if not exists library_files (
  id text primary key,
  -- Legacy attribution columns retained for compatibility reads. Team ownership never depends on
  -- user_id, and deleting an uploader must not delete a team file.
  user_id text references users(id) on delete set null,
  tenant_id text not null references tenants(id) on delete cascade,
  space_type text not null default 'personal' check (space_type in ('personal', 'team')),
  owner_user_id text references users(id) on delete cascade,
  owner_tenant_id text references tenants(id) on delete cascade,
  uploaded_by_user_id text references users(id) on delete set null,
  original_name text not null,
  safe_name text not null,
  display_name text not null,
  normalized_name text not null,
  mime_type text,
  file_type text not null check (file_type in ('image', 'file')),
  extension text,
  size_bytes bigint not null,
  storage_bucket text not null,
  storage_object_key text not null unique,
  content_hash text,
  preview_supported boolean not null default false,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  deleted_at timestamptz,
  -- Chat temporary-file lifecycle (docs/LIBRARY_FILE_LIFECYCLE.md). A chat upload is a user-owned
  -- file with a shorter life. Promotion flips it to permanent with no byte copy.
  source text not null default 'library' check (source in ('library', 'chat_upload')),
  lifecycle text not null default 'permanent' check (lifecycle in ('temporary', 'permanent')),
  expires_at timestamptz,
  promoted_at timestamptz,
  chat_session_id text references chat_sessions(id) on delete set null,
  -- Cross-column lifecycle invariant (§3.4): a temporary file always has a deadline. Its
  -- chat_session_id is null while unbound and set once on first turn use (§5/§7). A permanent
  -- file never has an expiry, so the GC expires_at filter cannot catch it. Named so the
  -- existing-PostgreSQL DO block below can update it in place.
  constraint library_files_lifecycle_invariant check (
    (lifecycle = 'temporary' and expires_at is not null)
    or (lifecycle = 'permanent' and expires_at is null)
  ),
  constraint library_files_owner_invariant check (
    (space_type = 'personal' and owner_user_id is not null and owner_tenant_id is null)
    or (space_type = 'team' and owner_user_id is null and owner_tenant_id is not null)
  )
);

create index if not exists idx_library_files_user_tenant_updated
  on library_files (user_id, tenant_id, updated_at desc)
  where deleted_at is null;

create index if not exists idx_library_files_user_tenant_type
  on library_files (user_id, tenant_id, file_type, updated_at desc)
  where deleted_at is null;

create unique index if not exists idx_library_files_storage_object_key
  on library_files (storage_object_key);

create table if not exists library_upload_sessions (
  id text primary key,
  file_id text not null,
  user_id text references users(id) on delete set null,
  tenant_id text not null references tenants(id) on delete cascade,
  space_type text not null default 'personal' check (space_type in ('personal', 'team')),
  owner_user_id text references users(id) on delete cascade,
  owner_tenant_id text references tenants(id) on delete cascade,
  uploaded_by_user_id text references users(id) on delete set null,
  original_name text not null,
  safe_name text not null,
  requested_name text not null,
  mime_type text,
  file_type text not null check (file_type in ('image', 'file')),
  extension text,
  file_size_bytes bigint not null,
  storage_bucket text not null,
  storage_object_key text not null unique,
  content_hash text,
  reserved_bytes bigint not null,
  status text not null default 'initiated' check (status in ('initiated', 'completed', 'expired', 'failed')),
  expires_at timestamptz not null,
  completed_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  -- Chat uploads carry their session context here and route complete-upload (§4). The
  -- on delete cascade is documentary only — chat sessions are soft-deleted, so it never fires.
  chat_session_id text references chat_sessions(id) on delete cascade,
  constraint library_upload_sessions_owner_invariant check (
    (space_type = 'personal' and owner_user_id is not null and owner_tenant_id is null)
    or (space_type = 'team' and owner_user_id is null and owner_tenant_id is not null)
  )
);

create table if not exists library_space_usage (
  space_type text not null check (space_type in ('personal', 'team')),
  owner_key text not null,
  owner_user_id text references users(id) on delete cascade,
  owner_tenant_id text references tenants(id) on delete cascade,
  used_bytes bigint not null default 0 check (used_bytes >= 0),
  reserved_bytes bigint not null default 0 check (reserved_bytes >= 0),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  primary key (space_type, owner_key),
  constraint library_space_usage_owner_invariant check (
    (space_type = 'personal' and owner_user_id is not null and owner_tenant_id is null and owner_key = owner_user_id)
    or (space_type = 'team' and owner_user_id is null and owner_tenant_id is not null and owner_key = owner_tenant_id)
  )
);

create table if not exists library_delivery_capabilities (
  token text primary key,
  file_id text not null references library_files(id) on delete cascade,
  actor_user_id text not null references users(id) on delete cascade,
  tenant_id text not null references tenants(id) on delete cascade,
  turn_id text not null references chat_turns(id) on delete cascade,
  use_count integer not null default 0 check (use_count >= 0),
  max_uses integer not null default 3 check (max_uses > 0),
  expires_at timestamptz not null,
  created_at timestamptz not null default now()
);

create index if not exists idx_library_delivery_capabilities_expiry
  on library_delivery_capabilities (expires_at);

create table if not exists library_name_claims (
  space_type text not null check (space_type in ('personal', 'team')),
  owner_key text not null,
  normalized_name text not null,
  file_id text not null unique references library_files(id) on delete cascade,
  created_at timestamptz not null default now(),
  primary key (space_type, owner_key, normalized_name)
);

create index if not exists idx_library_upload_sessions_status
  on library_upload_sessions (status, expires_at);

create index if not exists idx_library_upload_sessions_file
  on library_upload_sessions (file_id);

-- Backfill lifecycle columns on databases whose library_files predates this design. The create
-- table above is a no-op once the table exists, so new columns are added here. Existing rows
-- default to source='library', lifecycle='permanent', expires_at=null -- already invariant-valid.
alter table library_files add column if not exists source text not null default 'library' check (source in ('library', 'chat_upload'));
alter table library_files add column if not exists lifecycle text not null default 'permanent' check (lifecycle in ('temporary', 'permanent'));
alter table library_files add column if not exists expires_at timestamptz;
alter table library_files add column if not exists promoted_at timestamptz;
alter table library_files add column if not exists chat_session_id text references chat_sessions(id) on delete set null;
alter table library_files add column if not exists space_type text not null default 'personal' check (space_type in ('personal', 'team'));
alter table library_files add column if not exists owner_user_id text references users(id) on delete cascade;
alter table library_files add column if not exists owner_tenant_id text references tenants(id) on delete cascade;
alter table library_files add column if not exists uploaded_by_user_id text references users(id) on delete set null;
alter table library_files add column if not exists display_name text;
alter table library_files add column if not exists normalized_name text;

alter table library_upload_sessions add column if not exists chat_session_id text references chat_sessions(id) on delete cascade;
alter table library_upload_sessions add column if not exists space_type text not null default 'personal' check (space_type in ('personal', 'team'));
alter table library_upload_sessions add column if not exists owner_user_id text references users(id) on delete cascade;
alter table library_upload_sessions add column if not exists owner_tenant_id text references tenants(id) on delete cascade;
alter table library_upload_sessions add column if not exists uploaded_by_user_id text references users(id) on delete set null;
alter table library_upload_sessions add column if not exists requested_name text;
alter table library_upload_sessions add column if not exists reserved_bytes bigint not null default 0;

update library_files
set owner_user_id = coalesce(owner_user_id, user_id),
    uploaded_by_user_id = coalesce(uploaded_by_user_id, user_id),
    display_name = coalesce(display_name, original_name),
    normalized_name = coalesce(normalized_name, lower(original_name))
where space_type = 'personal';

update library_upload_sessions
set owner_user_id = coalesce(owner_user_id, user_id),
    uploaded_by_user_id = coalesce(uploaded_by_user_id, user_id),
    requested_name = coalesce(requested_name, original_name),
    reserved_bytes = case
      when status = 'initiated' and expires_at > CURRENT_TIMESTAMP and reserved_bytes = 0
      then file_size_bytes else reserved_bytes end
where space_type = 'personal';

insert into library_space_usage (
  space_type, owner_key, owner_user_id, owner_tenant_id, used_bytes, reserved_bytes
)
select
  'personal',
  u.owner_user_id,
  u.owner_user_id,
  null,
  u.used_bytes,
  coalesce(r.reserved_bytes, 0)
from (
  select owner_user_id, coalesce(sum(size_bytes), 0) as used_bytes
  from library_files
  where space_type = 'personal' and deleted_at is null
    and (lifecycle = 'permanent' or expires_at > CURRENT_TIMESTAMP)
  group by owner_user_id
) u
left join (
  select owner_user_id, coalesce(sum(reserved_bytes), 0) as reserved_bytes
  from library_upload_sessions
  where space_type = 'personal' and status = 'initiated' and expires_at > CURRENT_TIMESTAMP
  group by owner_user_id
) r on r.owner_user_id = u.owner_user_id
where u.owner_user_id is not null
on conflict (space_type, owner_key) do nothing;

-- Reservation-only owners have no row in the file-derived aggregate above. Keep their ledger row
-- so completion and the normal expired-session GC can settle the reservation atomically.
insert into library_space_usage (
  space_type, owner_key, owner_user_id, owner_tenant_id, used_bytes, reserved_bytes
)
select
  'personal',
  owner_user_id,
  owner_user_id,
  null,
  0,
  coalesce(sum(reserved_bytes), 0)
from library_upload_sessions
where space_type = 'personal' and status = 'initiated' and expires_at > CURRENT_TIMESTAMP
  and owner_user_id is not null
group by owner_user_id
on conflict (space_type, owner_key) do nothing;

insert into library_name_claims (space_type, owner_key, normalized_name, file_id)
select
  space_type,
  case when space_type = 'personal' then owner_user_id else owner_tenant_id end,
  normalized_name,
  id
from library_files
where deleted_at is null and normalized_name is not null
  and (space_type = 'team' or lifecycle = 'permanent')
on conflict do nothing;

-- Temporary-file lifecycle indexes (§3.2): expiry sweep and per-session listing.
create index if not exists idx_library_files_temporary_expiry
  on library_files (lifecycle, expires_at)
  where deleted_at is null;

create index if not exists idx_library_files_chat_session
  on library_files (chat_session_id, created_at desc)
  where deleted_at is null;

-- Land the cross-column lifecycle invariant on existing PostgreSQL tables (create table if not
-- exists never alters an existing table, and the runner skips bare ADD CONSTRAINT under SQLite).
-- _sqlite_compatible_sql strips this DO block. SQLite uses the canonical table check, while legacy
-- Library tables are rebuilt before migrations run.
do $$
begin
  -- Drop-then-add so the definition is updated in place on existing PostgreSQL tables (the
  -- invariant was relaxed to allow unbound temporary files: chat_session_id may be null).
  alter table library_files drop constraint if exists library_files_lifecycle_invariant;
  alter table library_files add constraint library_files_lifecycle_invariant check (
    (lifecycle = 'temporary' and expires_at is not null)
    or (lifecycle = 'permanent' and expires_at is null)
  );
  alter table library_files drop constraint if exists library_files_user_id_fkey;
  alter table library_files alter column user_id drop not null;
  alter table library_files add constraint library_files_user_id_fkey
    foreign key (user_id) references users(id) on delete set null;
  alter table library_files alter column display_name set not null;
  alter table library_files alter column normalized_name set not null;
  alter table library_files drop constraint if exists library_files_owner_invariant;
  alter table library_files add constraint library_files_owner_invariant check (
    (space_type = 'personal' and owner_user_id is not null and owner_tenant_id is null)
    or (space_type = 'team' and owner_user_id is null and owner_tenant_id is not null)
  );

  alter table library_upload_sessions drop constraint if exists library_upload_sessions_user_id_fkey;
  alter table library_upload_sessions alter column user_id drop not null;
  alter table library_upload_sessions add constraint library_upload_sessions_user_id_fkey
    foreign key (user_id) references users(id) on delete set null;
  alter table library_upload_sessions alter column requested_name set not null;
  alter table library_upload_sessions drop constraint if exists library_upload_sessions_owner_invariant;
  alter table library_upload_sessions add constraint library_upload_sessions_owner_invariant check (
    (space_type = 'personal' and owner_user_id is not null and owner_tenant_id is null)
    or (space_type = 'team' and owner_user_id is null and owner_tenant_id is not null)
  );
end $$;
