-- Auth and RBAC. Users, tenants, memberships, platform roles, and the token tables.
-- Platform roles (admin/expert/operator) are distinct from tenant roles (admin/member).
create table if not exists users (
  id text primary key,
  email text not null unique,
  password_hash text not null,
  name text not null,
  preferred_locale text check (preferred_locale in ('zh-CN', 'en-US')),
  avatar_object_key text,
  status text not null check (status in ('pending_activation', 'active', 'disabled')),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

-- Backfill global profile columns on databases created before account profiles existed.
alter table users add column if not exists preferred_locale text;
alter table users add column if not exists avatar_object_key text;

-- Existing SQLite tables cannot add this CHECK without a rebuild, so request/service validation
-- remains authoritative there. The runner strips this block for SQLite and applies it to existing
-- PostgreSQL tables.
do $$
begin
  alter table users drop constraint if exists users_preferred_locale_check;
  alter table users add constraint users_preferred_locale_check check (
    preferred_locale is null or preferred_locale in ('zh-CN', 'en-US')
  );
end $$;

create table if not exists tenants (
  id text primary key,
  type text not null default 'personal' check (type in ('personal', 'team')),
  name text not null,
  slug text not null unique,
  owner_user_id text references users(id) on delete set null,
  status text not null check (status in ('active', 'disabled')),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists tenant_members (
  id text primary key,
  tenant_id text not null references tenants(id) on delete cascade,
  user_id text not null references users(id) on delete cascade,
  role text not null check (role in ('admin', 'member')),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (tenant_id, user_id)
);

-- Shared fallback tenant for active users who otherwise have no valid tenant context.
-- Membership is attached lazily by AuthService and existing tenant configuration is preserved.
insert into tenants (id, type, name, slug, owner_user_id, status)
values ('tenant_default', 'team', 'Default Workspace', 'system-default-workspace', null, 'active')
on conflict (id) do nothing;

create table if not exists platform_user_roles (
  id text primary key,
  user_id text not null references users(id) on delete cascade,
  role text not null check (role in ('admin', 'expert', 'operator')),
  assigned_by text references users(id) on delete set null,
  created_at timestamptz not null default now(),
  unique (user_id, role)
);

create table if not exists refresh_tokens (
  id text primary key,
  user_id text not null references users(id) on delete cascade,
  token_hash text not null,
  expires_at timestamptz not null,
  revoked_at timestamptz,
  created_at timestamptz not null default now()
);

create table if not exists platform_activation_tokens (
  id text primary key,
  user_id text not null references users(id) on delete cascade,
  token_hash text not null unique,
  expires_at timestamptz not null,
  used_at timestamptz,
  created_at timestamptz not null default now()
);

create table if not exists password_reset_codes (
  id text primary key,
  user_id text not null references users(id) on delete cascade,
  code_hash text not null,
  expires_at timestamptz not null,
  attempt_count integer not null default 0 check (attempt_count >= 0),
  used_at timestamptz,
  created_at timestamptz not null default now()
);

-- Indexes for auth/RBAC hot lookups.
create index if not exists idx_refresh_tokens_user_token
  on refresh_tokens (user_id, token_hash);

create index if not exists idx_tenant_members_user
  on tenant_members (user_id);

create index if not exists idx_platform_user_roles_user
  on platform_user_roles (user_id);

create index if not exists idx_password_reset_codes_user_created
  on password_reset_codes (user_id, created_at desc);
