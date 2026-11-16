-- Chat turns: a durable local copy of one ACP turn (the question, the assembled reasoning,
-- answer, and the terminal status). The ACP data plane has no server turn id, so the id is
-- generated locally and emitted in the public turn_started stream event.
create table if not exists chat_turns (
  id text primary key,
  session_id text not null references chat_sessions(id) on delete cascade,
  tenant_id text not null references tenants(id) on delete cascade,
  user_id text not null references users(id) on delete cascade,
  request_text text not null,
  reasoning_text text,
  response_text text,
  event_seq bigint not null default 0,
  model text,
  query_rewrite boolean not null default false,
  multi_hop_config jsonb,
  status text not null check (status in ('running', 'completed', 'failed', 'cancelled')),
  stop_reason text,
  error_message text,
  -- ACP usage_update.used is the absolute context-window usage for the session, not a
  -- per-turn counter. Keep the final and previous snapshots for credit audit. The scope and
  -- ACP session id separate independent contexts used by normal and search turns.
  token_usage_scope text not null default '',
  token_usage_session_id text not null default '',
  token_usage_previous_snapshot bigint not null default 0,
  token_usage_snapshot bigint not null default 0,
  token_used bigint not null default 0,
  is_internal boolean not null default false,
  -- Per-turn attachment provenance snapshot (§9). Denormalized, mandatory-on-write for turns that
  -- reference files, so history/audit survive the referenced library_files row being GC-removed.
  -- Each
  -- element: {fileId, name, mimeType, sizeBytes, lifecycle, attachedAt}.
  attachments jsonb not null default '[]'::jsonb,
  -- LightRAG retrieval provenance snapshot. Each element mirrors a LightRAG /query reference:
  -- {referenceId, filePath, content}. Written at turn finalization, empty when the turn did no
  -- knowledge-base retrieval (no expert binding, no index, or retrieval failed).
  retrieval_refs jsonb not null default '[]'::jsonb,
  created_at timestamptz not null default now(),
  completed_at timestamptz
);

alter table chat_turns add column if not exists reasoning_text text;
alter table chat_turns add column if not exists attachments jsonb not null default '[]'::jsonb;
alter table chat_turns add column if not exists retrieval_refs jsonb not null default '[]'::jsonb;
alter table chat_turns add column if not exists token_usage_scope text not null default '';
alter table chat_turns add column if not exists token_usage_session_id text not null default '';
alter table chat_turns add column if not exists token_usage_previous_snapshot bigint not null default 0;
alter table chat_turns add column if not exists token_usage_snapshot bigint not null default 0;
alter table chat_turns add column if not exists token_used bigint not null default 0;

create index if not exists idx_chat_turns_session_created
  on chat_turns (session_id, created_at asc);

create index if not exists idx_chat_turns_tenant_user
  on chat_turns (tenant_id, user_id, created_at desc);

create index if not exists idx_chat_turns_usage_scope
  on chat_turns (session_id, token_usage_scope, created_at desc);

create index if not exists idx_chat_turns_usage_session_scope
  on chat_turns (
    session_id, token_usage_scope, token_usage_session_id, completed_at desc, created_at desc
  );

-- Preserve the newest running row if an existing database predates the one-running-Turn rule.
update chat_turns as older
set status = 'cancelled',
    stop_reason = coalesce(stop_reason, 'superseded'),
    error_message = coalesce(error_message, 'Superseded by a concurrent running Turn'),
    completed_at = coalesce(completed_at, CURRENT_TIMESTAMP)
where status = 'running'
  and exists (
    select 1
    from chat_turns as newer
    where newer.session_id = older.session_id
      and newer.status = 'running'
      and (
        newer.created_at > older.created_at
        or (newer.created_at = older.created_at and newer.id > older.id)
      )
  );

create unique index if not exists uq_chat_turns_session_running
  on chat_turns (session_id)
  where status = 'running';

-- Retire legacy task tables. Ordered replay now belongs to chat_turn_events below.
drop table if exists chat_task_events;
drop table if exists chat_tasks;

alter table chat_turns add column if not exists event_seq bigint not null default 0;

create table if not exists chat_turn_events (
  turn_id text not null references chat_turns(id) on delete cascade,
  seq bigint not null,
  event text not null,
  payload jsonb not null,
  primary key (turn_id, seq)
);
