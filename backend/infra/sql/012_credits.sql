-- Tenant-scoped optimistic product-credit ledger.
create table if not exists tenant_credit_periods (
  id text primary key,
  tenant_id text not null references tenants(id) on delete cascade,
  period_start timestamptz not null,
  highest_plan_credit_limit bigint not null check (highest_plan_credit_limit >= 0),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (tenant_id, period_start)
);

create index if not exists idx_tenant_credit_periods_tenant_period
  on tenant_credit_periods (tenant_id, period_start desc);

create table if not exists credit_ledger (
  id text primary key,
  period_id text not null references tenant_credit_periods(id) on delete cascade,
  tenant_id text not null references tenants(id) on delete cascade,
  beneficiary_user_id text references users(id) on delete cascade,
  entry_type text not null check (
    entry_type in ('monthly_grant', 'upgrade_grant', 'turn_charge', 'manual_adjustment')
  ),
  amount bigint not null check (amount <> 0),
  reference_id text,
  idempotency_key text,
  request_fingerprint text,
  actor_user_id text references users(id) on delete set null,
  reason text,
  created_at timestamptz not null default now(),
  unique (tenant_id, idempotency_key)
);

alter table credit_ledger
  add column if not exists beneficiary_user_id text references users(id) on delete cascade;

create index if not exists idx_credit_ledger_tenant_period_created
  on credit_ledger (tenant_id, period_id, created_at desc);

create index if not exists idx_credit_ledger_user_period_created
  on credit_ledger (tenant_id, beneficiary_user_id, period_id, created_at desc);

create unique index if not exists uq_credit_ledger_user_monthly_grant
  on credit_ledger (period_id, beneficiary_user_id, entry_type)
  where entry_type = 'monthly_grant' and beneficiary_user_id is not null;

create unique index if not exists uq_credit_ledger_turn_charge
  on credit_ledger (tenant_id, reference_id)
  where entry_type = 'turn_charge';

create table if not exists credit_usage_records (
  id text primary key,
  turn_id text not null unique references chat_turns(id) on delete cascade,
  period_id text not null references tenant_credit_periods(id) on delete cascade,
  tenant_id text not null references tenants(id) on delete cascade,
  user_id text not null references users(id) on delete cascade,
  session_id text not null references chat_sessions(id) on delete cascade,
  token_used bigint not null check (token_used >= 0),
  usage_source text not null,
  calculator_version text not null,
  tokens_per_credit integer not null check (tokens_per_credit > 0),
  rounding_mode text not null,
  token_usage_scope text,
  acp_session_id text,
  calculation_scale integer check (calculation_scale > 0),
  cached_input_weight_scaled integer check (cached_input_weight_scaled >= 0),
  previous_usage_size bigint check (previous_usage_size >= 0),
  current_usage_size bigint check (current_usage_size >= 0),
  cached_tokens bigint check (cached_tokens >= 0),
  uncached_tokens bigint check (uncached_tokens >= 0),
  effective_tokens_scaled bigint check (effective_tokens_scaled >= 0),
  calculated_credits bigint not null check (calculated_credits >= 0),
  deducted_credits bigint not null check (deducted_credits >= 0),
  -- Shadow values are retained only so immutable pre-cutover usage remains readable.
  settlement_mode text not null check (settlement_mode in ('shadow', 'enforced')),
  status text not null check (status in ('settled', 'shadow', 'unmetered', 'not_chargeable')),
  non_charge_reason text,
  created_at timestamptz not null default now()
);

alter table credit_usage_records add column if not exists token_usage_scope text;
alter table credit_usage_records add column if not exists acp_session_id text;
alter table credit_usage_records add column if not exists calculation_scale integer;
alter table credit_usage_records add column if not exists cached_input_weight_scaled integer;
alter table credit_usage_records add column if not exists previous_usage_size bigint;
alter table credit_usage_records add column if not exists current_usage_size bigint;
alter table credit_usage_records add column if not exists cached_tokens bigint;
alter table credit_usage_records add column if not exists uncached_tokens bigint;
alter table credit_usage_records add column if not exists effective_tokens_scaled bigint;

create index if not exists idx_credit_usage_records_tenant_period
  on credit_usage_records (tenant_id, period_id, created_at desc);
