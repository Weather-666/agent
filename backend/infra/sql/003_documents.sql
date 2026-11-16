-- Documents and upload sessions. Like knowledge_bases, these are platform-authored and carry
-- NO tenant_id (tenants never own/operate documents).
--
-- Chunking is decided at build time, so there are no chunk_strategy columns. Only storage_key
-- (plus object_bucket) locates the MinIO object. object_bucket comes from settings.minio_bucket
-- today but is persisted not null so historical objects stay locatable if the bucket changes.
create table if not exists documents (
  id text primary key,
  knowledge_base_id text not null references knowledge_bases(id) on delete cascade,
  file_name text not null,
  file_type text not null
    check (file_type in ('pdf', 'docx', 'pptx', 'xlsx', 'md', 'txt', 'html', 'csv', 'json')),
  mime_type text,
  storage_key text not null,
  object_bucket text not null,
  object_version text,
  content_hash text,
  -- source_sha256 is the server-computed hash of the immutable original object. The legacy
  -- content_hash remains readable during migration. Nullable values are repaired by startup
  -- reconciliation instead of making old rows fail migration.
  source_sha256 text,
  indexed_sha256 text,
  file_size_bytes bigint not null,
  language text check (language in ('zh', 'en', 'mixed')),
  parse_status text not null default 'pending'
    check (parse_status in ('pending', 'processing', 'ready', 'failed')),
  index_status text not null default 'pending'
    check (index_status in ('pending', 'processing', 'ready', 'failed', 'stale')),
  -- LightRAG linkage written by the automatic sync worker: the external document id (required for
  -- exact deletion), ingestion track id and durable errors.
  lightrag_track_id text,
  index_document_id text,
  markdown_storage_key text,
  markdown_sha256 text,
  index_pipeline_version text,
  parse_error text,
  last_error text,
  created_by text not null references users(id),
  deleted_at timestamptz,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists idx_documents_kb_status
  on documents (knowledge_base_id, parse_status, index_status)
  where deleted_at is null;

create unique index if not exists idx_documents_storage_key
  on documents (storage_key);

-- Support knowledge-base document list sorted by created_at.
create index if not exists idx_documents_kb_created
  on documents (knowledge_base_id, created_at desc);

-- document_upload_sessions tracks a MinIO direct-upload handshake for knowledge-base documents.
-- document_id is allocated at upload-url time (the object key depends on it) but the documents row
-- is only inserted at complete-upload, so document_id is plain text, not a foreign key.
create table if not exists document_upload_sessions (
  id text primary key,
  knowledge_base_id text not null references knowledge_bases(id) on delete cascade,
  document_id text not null,
  -- Non-null only for a source-replacement handshake. This prevents a doc:create completion
  -- endpoint from consuming a doc:update session (or an accidental id collision from replacing
  -- an existing Document).
  replaces_document_id text,
  actor_user_id text not null references users(id) on delete cascade,
  upload_mode text not null default 'single_put'
    check (upload_mode in ('single_put', 'multipart')),
  file_name text not null,
  file_type text not null
    check (file_type in ('pdf', 'docx', 'pptx', 'xlsx', 'md', 'txt', 'html', 'csv', 'json')),
  content_type text,
  file_size_bytes bigint not null,
  object_bucket text not null,
  object_key text not null unique,
  multipart_upload_id text,
  status text not null default 'initiated'
    check (status in ('initiated', 'completed', 'aborted', 'expired', 'failed')),
  expires_at timestamptz not null,
  completed_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists idx_document_upload_sessions_status
  on document_upload_sessions (status, expires_at);

create index if not exists idx_document_upload_sessions_document
  on document_upload_sessions (document_id);

-- Preserve deployments whose documents table predates the LightRAG linkage columns.
alter table documents add column if not exists lightrag_track_id text;
alter table documents add column if not exists parse_error text;
alter table documents add column if not exists source_sha256 text;
alter table documents add column if not exists indexed_sha256 text;
alter table documents add column if not exists index_document_id text;
alter table documents add column if not exists markdown_storage_key text;
alter table documents add column if not exists markdown_sha256 text;
alter table documents add column if not exists index_pipeline_version text;
alter table documents add column if not exists last_error text;
alter table document_upload_sessions add column if not exists replaces_document_id text;

alter table documents drop constraint if exists documents_index_status_check;
alter table documents add constraint documents_index_status_check check (
  index_status in ('pending', 'processing', 'ready', 'failed', 'stale')
);

-- Safe compatibility backfill. Rows with an old nullable content_hash remain nullable and are
-- repaired by the sync worker after it verifies the immutable object bytes.
update documents
set source_sha256 = content_hash
where source_sha256 is null and content_hash is not null;

-- Legacy name cleanup. Upload sessions are ephemeral handshake records (short TTL, GC'd), so the
-- old table is dropped rather than data-migrated after the rename to document_upload_sessions.
drop table if exists upload_sessions;
