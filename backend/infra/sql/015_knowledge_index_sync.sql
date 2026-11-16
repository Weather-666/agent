-- Durable automatic knowledge indexing queues.
--
-- knowledge_index_outbox is written in the same transaction as KB lifecycle changes. Startup
-- reconciliation recreates a missing ensure/delete event from source-of-truth rows, so a lost
-- wake-up or process restart cannot strand a knowledge base.
create table if not exists knowledge_index_outbox (
  id text primary key,
  dedupe_key text not null unique,
  knowledge_base_id text not null,
  event_type text not null check (event_type in ('binding.ensure', 'binding.delete')),
  status text not null default 'pending'
    check (status in ('pending', 'processing', 'processed', 'failed')),
  attempts bigint not null default 0,
  available_at timestamptz not null default now(),
  last_error text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  processed_at timestamptz
);

create index if not exists idx_knowledge_index_outbox_pending
  on knowledge_index_outbox (status, available_at, created_at);

-- One immutable source SHA + index pipeline version is one upsert generation (the version is
-- encoded in dedupe_key). Delete jobs snapshot the external document id before GC removes the live
-- Document row. dedupe_key makes concurrent completion/reconciliation idempotent on both SQLite
-- and PostgreSQL while still allowing a new parser/chunker pipeline to reindex unchanged bytes.
create table if not exists knowledge_document_sync_jobs (
  id text primary key,
  dedupe_key text not null unique,
  knowledge_base_id text not null,
  document_id text not null,
  operation text not null check (operation in ('upsert', 'delete')),
  source_sha256 text,
  index_document_id text,
  index_approved_at timestamptz,
  status text not null default 'pending'
    check (status in (
      'pending', 'processing', 'succeeded', 'failed', 'superseded'
    )),
  attempts bigint not null default 0,
  available_at timestamptz not null default now(),
  last_error text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  completed_at timestamptz
);

create index if not exists idx_knowledge_document_sync_jobs_pending
  on knowledge_document_sync_jobs (status, available_at, created_at);

create index if not exists idx_knowledge_document_sync_jobs_document
  on knowledge_document_sync_jobs (document_id, status, created_at);

alter table knowledge_document_sync_jobs drop constraint if exists knowledge_document_sync_jobs_status_check;
alter table knowledge_document_sync_jobs add constraint knowledge_document_sync_jobs_status_check check (
  status in ('pending', 'processing', 'succeeded', 'failed', 'superseded')
);

-- Manual approvals are one row per confirmed batch. The per-job approval timestamp keeps the gate
-- restart-safe without a second approval-document table. Automatic batches need no record.
create table if not exists knowledge_index_approvals (
  batch_token text primary key,
  knowledge_base_id text not null references knowledge_bases(id) on delete cascade,
  document_count bigint not null,
  total_size_bytes bigint not null,
  approved_by text references users(id) on delete set null,
  approved_at timestamptz not null default now()
);

create index if not exists idx_knowledge_index_approvals_kb_time
  on knowledge_index_approvals (knowledge_base_id, approved_at desc);

alter table knowledge_document_sync_jobs
  add column if not exists index_approved_at timestamptz;
