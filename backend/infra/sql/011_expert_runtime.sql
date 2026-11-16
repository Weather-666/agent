-- Expert Runtime identity is derived from experts.id plus runtime_type. There is no
-- deployment Binding table or persisted Gateway/build snapshot.

-- Preserve deployments whose experts table predates Runtime configuration.
alter table experts add column if not exists instructions text not null default '';
alter table experts add column if not exists runtime_config jsonb not null default
  '{"codex":{"enabled":true,"maxInstances":20,"idleTtlSeconds":900,"turnTimeoutSeconds":900,"permissionMode":"auto_approve","requireVirtualKey":true},"opencode":{"enabled":false,"maxInstances":20,"idleTtlSeconds":900,"turnTimeoutSeconds":900,"permissionMode":"auto_approve","requireVirtualKey":true}}'::jsonb;
alter table experts alter column runtime_config set default
  '{"codex":{"enabled":true,"maxInstances":20,"idleTtlSeconds":900,"turnTimeoutSeconds":900,"permissionMode":"auto_approve","requireVirtualKey":true},"opencode":{"enabled":false,"maxInstances":20,"idleTtlSeconds":900,"turnTimeoutSeconds":900,"permissionMode":"auto_approve","requireVirtualKey":true}}'::jsonb;
alter table experts add column if not exists mcp_connector_ids jsonb not null default '[]'::jsonb;
alter table experts add column if not exists skill_runtime_targets jsonb not null default '{}'::jsonb;

drop index if exists idx_experts_expert_key;
drop table if exists expert_runtime_bindings;
alter table experts drop column if exists expert_key;

-- Historical sessions remain NULL and continue through the explicit legacy ACP route.
alter table chat_sessions add column if not exists expert_id text references experts(id);
alter table chat_sessions add column if not exists runtime_type text;
alter table chat_sessions drop column if exists runtime_build_id;
alter table chat_sessions drop column if exists runtime_service_id;
alter table chat_sessions drop column if exists runtime_route_id;
alter table chat_sessions drop column if exists runtime_route_prefix;
alter table chat_sessions drop column if exists runtime_search_route_prefix;

drop index if exists idx_chat_turns_expert_usage;
alter table chat_turns add column if not exists expert_id text references experts(id);
alter table chat_turns add column if not exists runtime_type text;
alter table chat_turns drop column if exists runtime_build_id;
alter table chat_turns drop column if exists runtime_service_id;

create index if not exists idx_chat_sessions_expert_runtime
  on chat_sessions (expert_id, runtime_type, updated_at desc);

create index if not exists idx_chat_turns_expert_usage
  on chat_turns (expert_id, runtime_type, created_at desc);

-- Permission decisions return through the same expert Route that emitted the request.
create table if not exists chat_pending_permissions (
  id text primary key,
  session_id text not null references chat_sessions(id) on delete cascade,
  tenant_id text not null references tenants(id) on delete cascade,
  user_id text not null references users(id) on delete cascade,
  route_prefix text not null,
  status text not null default 'pending' check (status in ('pending', 'resolved')),
  created_at timestamptz not null default now(),
  resolved_at timestamptz
);

create index if not exists idx_chat_pending_permissions_owner
  on chat_pending_permissions (tenant_id, user_id, status, created_at desc);
