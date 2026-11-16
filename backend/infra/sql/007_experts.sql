-- Experts are platform-authored capability bundles. They can combine one category,
-- multiple skills, multiple knowledge bases, and optional prompt guide questions.
create table if not exists expert_categories (
  id text primary key,
  name text not null unique,
  description text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

-- Remove the abandoned category-level single-label experiment.
alter table expert_categories drop column if exists market_label;

create table if not exists experts (
  id text primary key,
  category_id text not null references expert_categories(id) on delete restrict,
  name text not null,
  ability_intro text not null,
  localized_content jsonb not null default '{}'::jsonb,
  tags jsonb not null default '[]'::jsonb,
  market_labels jsonb not null default '[]'::jsonb,
  status text not null default 'draft' check (status in ('published', 'draft', 'unlisted')),
  guide_questions jsonb not null default '[]'::jsonb,
  summon_button_text text,
  instructions text not null default '',
  runtime_config jsonb not null default
    '{"codex":{"enabled":true,"maxInstances":20,"idleTtlSeconds":900,"turnTimeoutSeconds":900,"permissionMode":"auto_approve","requireVirtualKey":true},"opencode":{"enabled":false,"maxInstances":20,"idleTtlSeconds":900,"turnTimeoutSeconds":900,"permissionMode":"auto_approve","requireVirtualKey":true}}'::jsonb,
  mcp_connector_ids jsonb not null default '[]'::jsonb,
  skill_runtime_targets jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

-- Preserve deployments whose experts table predates marketplace labels.
alter table experts add column if not exists market_labels jsonb not null default '[]'::jsonb;
alter table experts add column if not exists localized_content jsonb not null default '{}'::jsonb;

create table if not exists expert_skills (
  id text primary key,
  expert_id text not null references experts(id) on delete cascade,
  skill_id text not null references skills(id) on delete cascade,
  created_at timestamptz not null default now(),
  unique (expert_id, skill_id)
);

create table if not exists expert_knowledge_bases (
  id text primary key,
  expert_id text not null references experts(id) on delete cascade,
  knowledge_base_id text not null references knowledge_bases(id) on delete cascade,
  created_at timestamptz not null default now(),
  unique (expert_id, knowledge_base_id)
);

create index if not exists idx_experts_category_status
  on experts (category_id, status);

create index if not exists idx_experts_status_created
  on experts (status, created_at desc);

create index if not exists idx_expert_skills_skill
  on expert_skills (skill_id);

create index if not exists idx_expert_knowledge_bases_kb
  on expert_knowledge_bases (knowledge_base_id);

insert into expert_categories (id, name, description)
values ('expert_category_default', '默认分类', '系统默认专家分类')
on conflict (name) do nothing;

insert into experts (
  id,
  category_id,
  name,
  ability_intro,
  tags,
  status,
  guide_questions,
  summon_button_text
)
select
  '1825107e997dfde2',
  'expert_category_default',
  '默认专家',
  '系统默认专家，用于初始化套餐访问能力。',
  '["默认"]'::jsonb,
  'unlisted',
  '["我可以咨询哪些问题？"]'::jsonb,
  '咨询默认专家'
where not exists (
  select 1 from experts
  where id = '1825107e997dfde2'
)
on conflict (id) do nothing;
