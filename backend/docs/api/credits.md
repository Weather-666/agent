# Credits API

Credits normally belong to a tenant-owned shared pool. The configured default
tenant is the exception: each active member has an independent credit account
under the shared tenant. The MVP uses optimistic product credits, not
financial-grade billing or Provider-reported cache hits.

New chargeable Turns use `estimated-cache-v2`. For the same ACP session and
`token_usage_scope`, the previous final valid `usage.used` snapshot is estimated
as cached input and only the current growth is uncached. With defaults:

```text
cached = min(previous, current)
uncached = max(current - previous, 0)
effective = uncached + cached * 0.1
calculatedCredits = ceil(effective / 500)
```

No baseline or a changed ACP session means `previous = 0`. Search and
non-search scopes are independent. A non-growing context is charged again at
the cached weight, while a smaller snapshot treats the whole current value as
cached. Pre-v2 Turn rows have no durable ACP session id, so the first v2 Turn
after upgrade also uses a zero baseline. This split is a Backend estimate and
does not claim a real Provider cache hit.

## GET /api/v1/credits/current

Requires an authenticated tenant principal and `x-tenant-id`. Lazily creates
the current UTC-month period and the applicable monthly grant.

For `tenant_default`, this response is scoped to the authenticated user. Each
member receives the plan's monthly grant; another member's usage, adjustments,
or deductions do not change this response. Other tenants retain their
shared-pool behavior.

Response fields include `tenantId`, `planId`, `planCode`, `planName`,
`periodStart`, `periodEnd`, `monthlyCreditLimit`, `grantedCredits`, signed
`adjustmentCredits`, `estimatedUsedCredits`, `deductedCredits`,
`remainingCredits`, and `enforcementEnabled`.

`monthlyCreditLimit` and `grantedCredits` both report the effective plan credits
granted in the current UTC month: the base monthly grant plus any positive
same-month upgrade top-up. Manual adjustments are excluded. A same-month
downgrade does not reclaim or lower this effective limit; the next UTC month
starts from the then-current plan limit.

`enforcementEnabled` is retained for response compatibility and is always
`true`. Every new completed, metered, non-internal Turn uses enforced
settlement, writes one idempotent `turn_charge` when positive balance is
available, and reduces `remainingCredits`. Failed, cancelled, internal, and
unmetered Turns persist a zero-deduction usage record.

`EXPERT_CREDIT_TOKENS_PER_CREDIT` (default `500`) and
`EXPERT_CREDIT_CACHED_INPUT_WEIGHT` (default `0.1`) are read at Backend process
startup. The divisor must be positive and the cached weight must be in `[0, 1]`
with at most four decimal places. Changing either value requires a Backend
restart and affects only new Turns. Calculations use a fixed integer scale of
`10000`; each new usage record stores all applied inputs and derived values for
exact audit and replay. `calculatedCredits` remains the theoretical result and
`deductedCredits` remains capped to the positive balance available at
settlement.

## GET /api/v1/tenants/{tenant_id}/credits/current

Requires `platform:tenant_manage`. Returns the current summary plus signed
`ledgerBalance` and non-negative `overdrawnCredits`. Optional `userId` selects
one member account for `tenant_default`. Without `userId`, the default tenant
response aggregates all active member accounts by summing each member's
effective current-month plan grant. `userId` is rejected for other tenants
because they use a shared pool.

## GET /api/v1/tenants/{tenant_id}/credits/ledger

Requires `platform:tenant_manage`. Query parameters are `page` (default `1`),
`pageSize` (default `50`, maximum `100`), and optional `userId`. For
`tenant_default`, `userId` filters one member account; omitting it lists both
current user-scoped entries and any legacy shared entries. `userId` is rejected
for other tenants. Results are sorted by `createdAt desc, id desc`.

Each item contains the entry ID, period, tenant, optional
`beneficiaryUserId`, `entryType`, signed `amount`, optional `referenceId`,
optional idempotency key, optional actor, optional reason, and creation time.
Conversation text, reasoning, attachments, and signed URLs are never returned.

## POST /api/v1/tenants/{tenant_id}/credits/adjustments

Requires `platform:tenant_manage` and an `Idempotency-Key` header.

For `tenant_default`, query parameter `userId` is required and must identify an
active member. Missing it returns `400 CREDIT_USER_REQUIRED`. Other tenants do
not accept `userId` and continue adjusting the shared pool.

```json
{
  "amount": 100,
  "reason": "Support grant"
}
```

`amount` must be a non-zero integer. `reason` is required and trimmed. Reusing
the same key with the same request returns the first result without another
ledger entry. Reusing it with different input returns
`409 IDEMPOTENCY_KEY_REUSED`. A negative adjustment larger than the current
available balance returns `409 CREDIT_ADJUSTMENT_EXCEEDS_BALANCE`.

## Turn and expert errors

- `402 CREDIT_EXHAUSTED`: the applicable user or tenant balance is not positive
  before a new Turn starts.
- `403 EXPERT_NOT_INCLUDED_IN_PLAN`: the current plan does not include the
  selected Expert.
- `409 CHAT_TURN_ALREADY_RUNNING`: the Chat Session already has a running Turn.
- `409 PLAN_CREDIT_ENTITLEMENT_REQUIRED`: a subscription is being assigned to
  a plan without valid credit entitlements.

The migration repoints currently usable `plan_default` subscriptions to
`plan_free` without replacing their subscription rows. Historical terminal
subscriptions, pre-cutover Shadow usage, and historical `estimated-v1` records
remain unchanged. The cutover never recalculates old records or retroactively
creates Turn charges; v2 audit fields remain null on those historical rows.
