-- Append-only platform operation audit events. Historical snapshots deliberately have no
-- foreign keys so deleting or renaming business resources cannot erase audit readability.
create table if not exists audit_events (
  id text primary key,
  request_id text not null,
  occurred_at timestamptz not null,
  category text not null,
  action text not null,
  operation_type text not null
    check (operation_type in ('create', 'read', 'update', 'delete', 'login', 'grant', 'revoke', 'upload')),
  actor_user_id text not null,
  actor_name text not null,
  actor_email text not null,
  actor_platform_roles jsonb not null default '[]'::jsonb,
  tenant_id text,
  tenant_name text,
  resource_type text not null,
  resource_id text not null,
  resource_name text,
  changes jsonb not null default '{}'::jsonb,
  metadata jsonb not null default '{}'::jsonb,
  client_ip text
);

create index if not exists idx_audit_events_occurred
  on audit_events (occurred_at desc, id desc);

create index if not exists idx_audit_events_category_occurred
  on audit_events (category, occurred_at desc);

create index if not exists idx_audit_events_operation_occurred
  on audit_events (operation_type, occurred_at desc);

create index if not exists idx_audit_events_actor_occurred
  on audit_events (actor_user_id, occurred_at desc);

create index if not exists idx_audit_events_resource_occurred
  on audit_events (resource_type, resource_id, occurred_at desc);

create index if not exists idx_audit_events_request
  on audit_events (request_id);

alter table audit_events drop constraint if exists audit_events_operation_type_check;
alter table audit_events add constraint audit_events_operation_type_check
  check (operation_type in ('create', 'read', 'update', 'delete', 'login', 'grant', 'revoke', 'upload'));
