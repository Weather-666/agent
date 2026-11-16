-- One Controller-provisioned LightRAG instance per knowledge base. The Controller owns process
-- lifecycle. Backend persists only the endpoint and identities required to reconcile that instance.
create table if not exists knowledge_base_lightrag_instances (
  knowledge_base_id text primary key references knowledge_bases(id) on delete cascade,
  base_url text not null,
  workspace text,
  provider text,
  provider_ref text,
  status text,
  last_error text,
  retry_count bigint not null default 0,
  last_healthy_at timestamptz,
  deletion_requested_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

alter table knowledge_base_lightrag_instances add column if not exists workspace text;
alter table knowledge_base_lightrag_instances add column if not exists provider text;
alter table knowledge_base_lightrag_instances add column if not exists provider_ref text;
alter table knowledge_base_lightrag_instances add column if not exists status text;
alter table knowledge_base_lightrag_instances add column if not exists last_error text;
alter table knowledge_base_lightrag_instances add column if not exists retry_count bigint not null default 0;
alter table knowledge_base_lightrag_instances add column if not exists last_healthy_at timestamptz;
alter table knowledge_base_lightrag_instances add column if not exists deletion_requested_at timestamptz;

create unique index if not exists uq_lightrag_instance_binding_base_url
  on knowledge_base_lightrag_instances (base_url);

create unique index if not exists uq_lightrag_instance_binding_workspace
  on knowledge_base_lightrag_instances (workspace)
  where workspace is not null;

create unique index if not exists uq_lightrag_instance_binding_provider_ref
  on knowledge_base_lightrag_instances (provider, provider_ref)
  where provider is not null and provider_ref is not null;
