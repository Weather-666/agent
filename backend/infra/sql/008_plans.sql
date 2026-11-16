-- Expert plan configuration and subscriptions.
create table if not exists plans (
  id text primary key,
  code text not null unique,
  name text not null,
  level integer not null unique check (level >= 1 and level <= 99),
  description text not null,
  type_label text,
  subtitle text,
  badge_label text,
  highlight_items jsonb not null default '[]'::jsonb,
  localized_content jsonb not null default '{}'::jsonb,
  upgrade_rules jsonb not null default '{}'::jsonb,
  prices jsonb not null default '[]'::jsonb,
  entitlements jsonb,
  expert_ids jsonb not null default '[]'::jsonb,
  status text not null default 'active' check (status in ('active', 'disabled')),
  is_recommended boolean not null default false,
  sort_order integer not null default 0 check (sort_order >= 0 and sort_order <= 9999),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists subscriptions (
  id text primary key,
  tenant_id text not null references tenants(id) on delete cascade,
  plan_id text not null references plans(id) on delete restrict,
  status text not null check (status in ('active', 'trialing', 'past_due', 'cancelled', 'expired')),
  billing_period text not null check (billing_period in ('free', 'monthly', 'yearly', 'sales')),
  current_period_start timestamptz not null,
  current_period_end timestamptz,
  cancel_at_period_end boolean not null default false,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

-- Monotonic acquisition fact for Team Library downgrade behavior. Access to historical files
-- must not be inferred from the mutable current Plan JSON after a subscription ends.
create table if not exists team_library_entitlement_history (
  tenant_id text primary key references tenants(id) on delete cascade,
  max_quota_bytes bigint not null default 0 check (max_quota_bytes >= 0),
  first_entitled_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists idx_plans_status_sort
  on plans (status, sort_order, level);

create index if not exists idx_subscriptions_tenant_status
  on subscriptions (tenant_id, status, current_period_start desc);

alter table plans add column if not exists type_label text;
alter table plans add column if not exists subtitle text;
alter table plans add column if not exists badge_label text;
alter table plans add column if not exists highlight_items jsonb not null default '[]'::jsonb;
alter table plans add column if not exists localized_content jsonb not null default '{}'::jsonb;
alter table plans add column if not exists upgrade_rules jsonb not null default '{}'::jsonb;
alter table plans add column if not exists prices jsonb not null default '[]'::jsonb;
alter table plans add column if not exists entitlements jsonb;
alter table plans add column if not exists expert_ids jsonb not null default '[]'::jsonb;

alter table plans drop constraint if exists plans_level_check;
alter table plans add constraint plans_level_check check (level >= 1 and level <= 99);
alter table plans drop constraint if exists plans_sort_order_check;
alter table plans add constraint plans_sort_order_check check (sort_order >= 0 and sort_order <= 9999);

-- The development cutover may find a legacy plan occupying a core code or level.
-- Remove only conflicts for a missing core plan so the seed is complete and deterministic.
delete from subscriptions
where plan_id in (
  select p.id
  from plans p
  where
    (
      not exists (select 1 from plans core where core.id = 'plan_free')
      and p.id <> 'plan_free'
      and (p.code = 'free' or p.level = 10)
    )
    or (
      not exists (select 1 from plans core where core.id = 'plan_pro')
      and p.id <> 'plan_pro'
      and (p.code = 'pro' or p.level = 20)
    )
    or (
      not exists (select 1 from plans core where core.id = 'plan_max')
      and p.id <> 'plan_max'
      and (p.code = 'max' or p.level = 30)
    )
    or (
      not exists (select 1 from plans core where core.id = 'plan_business')
      and p.id <> 'plan_business'
      and (p.code = 'business' or p.level = 40)
    )
);

delete from plans
where id in (
  select p.id
  from plans p
  where
    (
      not exists (select 1 from plans core where core.id = 'plan_free')
      and p.id <> 'plan_free'
      and (p.code = 'free' or p.level = 10)
    )
    or (
      not exists (select 1 from plans core where core.id = 'plan_pro')
      and p.id <> 'plan_pro'
      and (p.code = 'pro' or p.level = 20)
    )
    or (
      not exists (select 1 from plans core where core.id = 'plan_max')
      and p.id <> 'plan_max'
      and (p.code = 'max' or p.level = 30)
    )
    or (
      not exists (select 1 from plans core where core.id = 'plan_business')
      and p.id <> 'plan_business'
      and (p.code = 'business' or p.level = 40)
    )
);

insert into plans (
  id,
  code,
  name,
  level,
  description,
  type_label,
  subtitle,
  badge_label,
  highlight_items,
  upgrade_rules,
  prices,
  entitlements,
  expert_ids,
  status,
  is_recommended,
  sort_order
)
values
  (
    'plan_free',
    'free',
    'Free',
    10,
    'Entry plan with a monthly tenant credit pool.',
    'Free',
    'Explore WinWise',
    null,
    '["2,000 monthly credits"]'::jsonb,
    '{}'::jsonb,
    '[{"id": "plan_price_free", "planId": "plan_free", "billingPeriod": "free", "currency": "USD", "amountCents": 0, "discountLabel": null, "isEnabled": true}]'::jsonb,
    '{"id": "plan_entitlement_free", "planId": "plan_free", "monthlyCreditLimit": 2000, "allExperts": false, "seatLimit": 1, "personalLibraryQuotaBytes": 2147483648, "teamLibraryQuotaBytes": 0, "teamLibraryEnabled": false, "singleTurnTokenLimit": null, "modelTiers": ["core"], "features": {}}'::jsonb,
    '["1825107e997dfde2"]'::jsonb,
    'active',
    false,
    10
  ),
  (
    'plan_pro',
    'pro',
    'Pro',
    20,
    'Individual plan with a larger monthly tenant credit pool.',
    'Pro',
    'For regular individual use',
    null,
    '["20,000 monthly credits"]'::jsonb,
    '{}'::jsonb,
    '[{"id": "plan_price_pro_monthly", "planId": "plan_pro", "billingPeriod": "monthly", "currency": "USD", "amountCents": 2000, "discountLabel": null, "isEnabled": true}, {"id": "plan_price_pro_yearly", "planId": "plan_pro", "billingPeriod": "yearly", "currency": "USD", "amountCents": 20000, "discountLabel": "Save 2 months", "isEnabled": true}]'::jsonb,
    '{"id": "plan_entitlement_pro", "planId": "plan_pro", "monthlyCreditLimit": 20000, "allExperts": false, "seatLimit": 1, "personalLibraryQuotaBytes": 2147483648, "teamLibraryQuotaBytes": 0, "teamLibraryEnabled": false, "singleTurnTokenLimit": null, "modelTiers": ["core"], "features": {}}'::jsonb,
    '["1825107e997dfde2"]'::jsonb,
    'active',
    true,
    20
  ),
  (
    'plan_max',
    'max',
    'Max',
    30,
    'Individual plan with access to all experts.',
    'Max',
    'For intensive individual use',
    null,
    '["50,000 monthly credits", "All experts"]'::jsonb,
    '{}'::jsonb,
    '[{"id": "plan_price_max_monthly", "planId": "plan_max", "billingPeriod": "monthly", "currency": "USD", "amountCents": 4900, "discountLabel": null, "isEnabled": true}, {"id": "plan_price_max_yearly", "planId": "plan_max", "billingPeriod": "yearly", "currency": "USD", "amountCents": 49000, "discountLabel": "Save 2 months", "isEnabled": true}]'::jsonb,
    '{"id": "plan_entitlement_max", "planId": "plan_max", "monthlyCreditLimit": 50000, "allExperts": true, "seatLimit": 1, "personalLibraryQuotaBytes": 2147483648, "teamLibraryQuotaBytes": 0, "teamLibraryEnabled": false, "singleTurnTokenLimit": null, "modelTiers": ["core"], "features": {}}'::jsonb,
    '[]'::jsonb,
    'active',
    false,
    30
  ),
  (
    'plan_business',
    'business',
    'Business',
    40,
    'Annual team plan with a shared tenant credit pool.',
    'Business',
    'Five-seat annual team plan',
    null,
    '["130,000 monthly credits", "All experts", "5 seats"]'::jsonb,
    '{}'::jsonb,
    '[{"id": "plan_price_business_yearly", "planId": "plan_business", "billingPeriod": "yearly", "currency": "USD", "amountCents": 238800, "discountLabel": "Equivalent to USD 199/month", "isEnabled": true}]'::jsonb,
    '{"id": "plan_entitlement_business", "planId": "plan_business", "monthlyCreditLimit": 130000, "allExperts": true, "seatLimit": 5, "personalLibraryQuotaBytes": 2147483648, "teamLibraryQuotaBytes": 21474836480, "teamLibraryEnabled": true, "singleTurnTokenLimit": null, "modelTiers": ["core"], "features": {"teamManagement": true}}'::jsonb,
    '[]'::jsonb,
    'active',
    false,
    40
  )
on conflict (id) do nothing;

-- Existing core plans predate Library entitlements. Merge the new keys without replacing plan
-- editor-managed values. Replaying this migration is safe because every assignment is idempotent.
update plans
set entitlements = case
    when id = 'plan_business' then
      '{"personalLibraryQuotaBytes": 2147483648, "teamLibraryQuotaBytes": 21474836480, "teamLibraryEnabled": true}'::jsonb || entitlements
    else
      '{"personalLibraryQuotaBytes": 2147483648, "teamLibraryQuotaBytes": 0, "teamLibraryEnabled": false}'::jsonb || entitlements
  end,
  updated_at = CURRENT_TIMESTAMP
where id in ('plan_free', 'plan_pro', 'plan_max', 'plan_business')
  and entitlements is not null;

-- Repoint only currently usable legacy default subscriptions to the seeded Free plan.
-- Historical terminal subscriptions remain unchanged and the update is idempotent.
update subscriptions
set
  plan_id = 'plan_free',
  billing_period = 'free',
  current_period_end = null,
  cancel_at_period_end = false,
  updated_at = CURRENT_TIMESTAMP
where plan_id = 'plan_default'
  and status in ('active', 'trialing', 'past_due')
  and (current_period_end is null or current_period_end > CURRENT_TIMESTAMP);

-- Backfill the default Expert for existing Free/Pro plans with an empty allowlist.
update plans
set
  expert_ids = '["1825107e997dfde2"]'::jsonb,
  updated_at = CURRENT_TIMESTAMP
where id in ('plan_free', 'plan_pro')
  and expert_ids = '[]'::jsonb;

-- Idempotently recover existing acquisitions. Business is an immutable historical product fact,
-- so it remains recoverable even if an operator later disables the mutable Plan entitlement.
-- Custom plans are only backfilled while the subscription is currently usable. A later Plan edit
-- must not turn an already-ended subscription into a historical acquisition.
insert into team_library_entitlement_history (tenant_id, max_quota_bytes)
select
  s.tenant_id,
  max(
    case
      when s.plan_id = 'plan_business' then 21474836480
      else coalesce(
        cast(p.entitlements ->> 'teamLibraryQuotaBytes' as bigint),
        21474836480
      )
    end
  ) as max_quota_bytes
from subscriptions s
inner join plans p on p.id = s.plan_id
where s.plan_id = 'plan_business'
   or (
     s.status in ('active', 'trialing', 'past_due')
     and (s.current_period_end is null or s.current_period_end > CURRENT_TIMESTAMP)
     and lower(coalesce(cast(p.entitlements ->> 'teamLibraryEnabled' as text), 'false'))
       in ('true', '1')
   )
group by s.tenant_id
on conflict (tenant_id) do update
set max_quota_bytes = case
      when excluded.max_quota_bytes > team_library_entitlement_history.max_quota_bytes
        then excluded.max_quota_bytes
      else team_library_entitlement_history.max_quota_bytes
    end,
    updated_at = CURRENT_TIMESTAMP;
