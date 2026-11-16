# Expert Plans and Tenant Credits

The Backend models subscriptions at tenant scope. Credits are tenant-owned
shared pools for ordinary personal and team tenants. The configured default
tenant is a deliberate exception: every active member has an independent
user-scoped balance while sharing the tenant's subscription and Expert access.

## Core concepts

- `plans` stores display configuration, embedded price entries, embedded
  entitlements, and `expertIds`.
- `subscriptions` selects the effective plan for a tenant.
- `tenant_credit_periods` stores one UTC-calendar-month period per tenant and
  remembers the month's highest plan credit limit.
- `credit_ledger` stores monthly grants, upgrade grants, Turn charges, and
  manual adjustments as signed amounts. `beneficiary_user_id` is populated for
  default-tenant user accounts and remains null for ordinary shared pools.
- `credit_usage_records` stores one immutable settlement observation per Turn.

The current estimated cache-aware calculator is:

```text
previous_size = latest final usage.used for the same ACP session and token usage scope, else 0
current_size = this Turn's final valid ACP usage.used
cached_tokens = min(previous_size, current_size)
uncached_tokens = max(current_size - previous_size, 0)
effective_tokens = uncached_tokens + cached_tokens * cached_input_weight
calculated_credits = ceil(effective_tokens / tokens_per_credit)
usage_source = acp_context_snapshot_split
calculator_version = estimated-cache-v2
```

The defaults are `tokens_per_credit = 500` and `cached_input_weight = 0.1`, read
from `EXPERT_CREDIT_TOKENS_PER_CREDIT` and
`EXPERT_CREDIT_CACHED_INPUT_WEIGHT` when the Backend process starts. The token
divisor must be positive and the cached weight must be in `[0, 1]` with at most
four decimal places. Changes require a Backend restart and affect only new Turn
settlements.

The calculator uses an integer scale of `10000`, so the default weight is stored
as `1000` and ceiling does not depend on floating-point arithmetic. Each new
usage record persists the applied divisor, scale, scaled weight, scope, ACP
session id, previous/current snapshots, cached/uncached split, scaled effective
tokens, rounding mode, calculated credits, and deducted credits. A constant
context is charged again at the cached weight. If the snapshot shrinks, the
whole current snapshot is treated as cached. Search and non-search scopes remain
independent, and a new ACP session starts with a zero baseline. Pre-v2 Turn rows
have no durable ACP session id, so the first v2 Turn after upgrade also starts
with a zero baseline instead of assuming old context belongs to the current ACP
session.

This is a Backend estimate, not a Provider-reported cache hit or cost split. It
is an optimistic product-credit ledger. It intentionally has no balance
reservation, row lock, distributed lock, automatic compensation, historical
recalculation, Provider-cost settlement, or payment workflow. Crashes between
Turn persistence and settlement may miss a charge, missing usage may undercharge,
and Turns in different Chat Sessions under extreme concurrency may produce a
small overdraft.

## Entitlements and Expert access

Plan entitlements contain `monthlyCreditLimit`, `allExperts`, `seatLimit`,
`singleTurnTokenLimit`, `modelTiers`, and `features`. The old question and Token
monthly limits do not exist.

Expert access is:

```text
allExperts == true OR expertId in expertIds
```

It is enforced when an Expert Session is created and before every Expert Turn.
Marketplace expert items expose `isAccessible` for the active tenant.

## Monthly grants and plan changes

The first current-credit query or Turn preflight in a UTC month creates the
period and grants the whole monthly limit. For the default tenant, this grant
is created independently for each active member. Mid-month upgrades grant only
the positive difference already received by the shared pool or individual
account; downgrades do not reclaim credits.

## Enforced settlement

Settlement is unconditionally enforced. A new Turn is rejected when the
current balance is not positive. A completed chargeable Turn deducts at most
the positive balance observed during settlement. `enforcementEnabled` remains
in API responses for compatibility and is always `true`.

The schema and domain reader continue to accept the legacy `shadow` mode and
status so immutable pre-cutover usage can be read. New code never creates those
values, and the cutover does not retroactively charge or rewrite old records.

Turn finalization updates only a Turn that remains `running`. Once cancellation
sets `cancelled`, stream completion cannot overwrite it. Failed, cancelled,
internal, and unmetered Turns get usage records with zero deduction.

Only one `running` Turn is allowed per Chat Session. The Backend reserves the
Turn before starting the SSE response, and a database partial unique index maps
a concurrent request to `409 CHAT_TURN_ALREADY_RUNNING`. This also prevents two
same-session Turns from reading the same usage baseline.

During the development cutover, each currently usable `plan_default`
subscription is updated in place to `plan_free`, normalized to the Free billing
period, and kept under its existing subscription ID. Terminal subscription
history remains unchanged. Re-running the migration is a no-op for already
converted rows.

Historical `estimated-v1` and Shadow records are neither recalculated nor
charged. Their v2-only audit columns remain null and the compatibility reader
continues to expose the original calculator metadata.

## Interfaces and operations

See:

- [`docs/api/plans.md`](api/plans.md) for plan and subscription contracts;
- [`docs/api/credits.md`](api/credits.md) for credit APIs and errors.
