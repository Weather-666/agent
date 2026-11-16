-- Immutable original-object generations for one logical Document.
--
-- The live documents row points at the current generation. Historical citation download resolves
-- document_id + source_sha256 here, so replacing a source never rewrites old provenance.
create table if not exists knowledge_document_source_versions (
  document_id text not null references documents(id) on delete cascade,
  source_sha256 text not null,
  knowledge_base_id text not null,
  file_name text not null,
  file_type text not null,
  mime_type text,
  storage_key text not null,
  object_bucket text not null,
  file_size_bytes bigint not null,
  created_at timestamptz not null default now(),
  primary key (document_id, source_sha256)
);

create unique index if not exists uq_knowledge_document_source_version_storage
  on knowledge_document_source_versions (storage_key);

create index if not exists idx_knowledge_document_source_versions_kb
  on knowledge_document_source_versions (knowledge_base_id, document_id);

-- Preserve all pre-cutover originals without requiring a non-null historical SHA migration.
insert into knowledge_document_source_versions (
  document_id, source_sha256, knowledge_base_id, file_name, file_type, mime_type,
  storage_key, object_bucket, file_size_bytes, created_at
)
select id, coalesce(source_sha256, content_hash), knowledge_base_id, file_name, file_type,
       mime_type, storage_key, object_bucket, file_size_bytes, created_at
from documents
where coalesce(source_sha256, content_hash) is not null
on conflict (document_id, source_sha256) do nothing;

alter table documents add column if not exists index_pipeline_version text;

-- Content-addressed Markdown generations remain reachable for exact object GC after a source
-- replacement. They are index artifacts, not a second knowledge source.
create table if not exists knowledge_document_markdown_artifacts (
  document_id text not null references documents(id) on delete cascade,
  source_sha256 text not null,
  markdown_storage_key text not null,
  markdown_sha256 text not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  primary key (document_id, source_sha256)
);

create unique index if not exists uq_knowledge_document_markdown_artifact_storage
  on knowledge_document_markdown_artifacts (markdown_storage_key);

insert into knowledge_document_markdown_artifacts (
  document_id, source_sha256, markdown_storage_key, markdown_sha256, created_at, updated_at
)
select id, indexed_sha256, markdown_storage_key, markdown_sha256, created_at, updated_at
from documents
where indexed_sha256 is not null
  and markdown_storage_key is not null
  and markdown_sha256 is not null
on conflict (document_id, source_sha256) do nothing;
