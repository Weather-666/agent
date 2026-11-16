# Tenants API

Base path:

```text
/api/v1/tenants
```

Tenant management is a platform-side workflow for customer workspaces. All
endpoints require:

```text
Authorization: Bearer <accessToken>
```

Required platform permission:

```text
platform:tenant_manage
```

## Resource Shape

```json
{
  "id": "tenant_123",
  "type": "team",
  "name": "Acme Team",
  "slug": "acme-team",
  "ownerUserId": "user_123",
  "ownerUserName": "Alice",
  "status": "active",
  "memberCount": 3,
  "monthlyCredits": {
    "monthlyCreditLimit": 20000,
    "estimatedUsedCredits": 125,
    "deductedCredits": 0,
    "remainingCredits": 20000,
    "enforcementEnabled": true
  },
  "createdAt": "2026-06-03T00:00:00+00:00",
  "updatedAt": "2026-06-03T00:00:00+00:00"
}
```

## GET /

List tenants. Required permission: `platform:tenant_manage`.

Query parameters (all optional):

| Param | Description |
| --- | --- |
| `search` | Fuzzy match on name, slug, owner name/email, or plan name/code. |
| `type` | Tenant type. One of `personal`, `team`. |
| `subscriptionType` | Subscription billing period. One of `free`, `monthly`, `yearly`, `sales`. |
| `subscriptionStatus` | Tenant-management subscription status — see the vocabulary below. |
| `sort` | One of `expiresAt`, `monthlyCredits`, `subscriptionStart`, `name`. |
| `page` | 1-based page number (default `1`). |
| `pageSize` | Page size, `1`–`100` (default `50`). |

### Subscription status vocabulary

Tenant management preserves the persisted lifecycle state where it is operationally meaningful.
The `currentSubscription.status` response field and `subscriptionStatus` filter use this six-value
vocabulary:

| `status` (value) | Meaning |
| --- | --- |
| `active` | In good standing, not near expiry. |
| `expiring_soon` | Raw status is `active` and the period ends within 14 days, including the exact 14-day boundary. |
| `expired` | Raw status is `expired`, or the current period has ended. |
| `trialing` | Raw status is `trialing` and the period has not ended. |
| `past_due` | Raw status is `past_due` and the period has not ended. |
| `cancelled` | Raw status is `cancelled`. |

Status precedence is:

1. Raw `cancelled` remains `cancelled`.
2. Raw `expired`, or `currentPeriodEnd <= now`, is `expired`.
3. An unexpired raw `trialing` or `past_due` value is preserved.
4. An unexpired raw `active` subscription within 14 days of period end is `expiring_soon`.
5. Other raw `active` subscriptions are `active`.

`cancelAtPeriodEnd=true` only disables renewal. Before the period ends, it does not by itself make
the subscription `cancelled`.

These are stable English values; display text is the frontend's i18n concern. Invalid tenant
types, subscription types, or subscription statuses return FastAPI validation `422`.

`GET /api/v1/users` intentionally keeps its existing three-state
`active`/`expiring_soon`/`expired` display contract.

Response `200`:

```json
{
  "items": [
    {
      "id": "tenant_123",
      "type": "team",
      "name": "Acme Team",
      "slug": "acme-team",
      "ownerUserId": "user_123",
      "ownerUserName": "Alice",
      "status": "active",
      "memberCount": 3,
      "currentSubscription": {
        "billingPeriod": "monthly",
        "status": "trialing",
        "rawStatus": "trialing"
      },
      "monthlyCredits": {
        "monthlyCreditLimit": 20000,
        "estimatedUsedCredits": 125,
        "deductedCredits": 0,
        "remainingCredits": 20000,
        "enforcementEnabled": true
      },
      "createdAt": "2026-06-03T00:00:00+00:00",
      "updatedAt": "2026-06-03T00:00:00+00:00"
    }
  ]
}
```

Tenant list and detail reads use the newest real subscription ordered by
`currentPeriodStart DESC, createdAt DESC, id DESC`, including cancelled and expired history. They
never create or replace a subscription. A tenant with no subscription returns
`currentSubscription: null`, `currentPlan: null`, and a zero credit summary.
For an effective subscription, hydration lazily creates the current UTC-month
credit period when needed. `monthlyCredits` describes the shared pool for an
ordinary tenant. For `tenant_default`, it aggregates all active members'
independent accounts; `monthlyCreditLimit` is therefore the per-user plan limit
multiplied by the active-member count.

## POST /

Create a `team` tenant. The owner user must already exist and is automatically
added as tenant `admin`.

Request:

```json
{
  "name": "Acme Team",
  "slug": "acme-team",
  "ownerUserId": "user_123"
}
```

`slug` is optional. If omitted, the server generates a slug from `name`.

Response `201`: the resource shape.

Errors:

```text
404 USER_NOT_FOUND
409 TENANT_SLUG_EXISTS
```

## GET /filter-options

Options backing the tenant-list filter dropdowns. Required permission: `platform:tenant_manage`.

`tenantTypes` and `subscriptionStatuses` are fixed enums returned as bare value arrays.
`subscriptionTypes` is the fixed billing-period vocabulary. Each option's `value` can be passed
directly as `subscriptionType`; `label` is display-only.

Response `200`:

```json
{
  "tenantTypes": ["personal", "team"],
  "subscriptionStatuses": [
    "active",
    "expiring_soon",
    "expired",
    "trialing",
    "past_due",
    "cancelled"
  ],
  "subscriptionTypes": [
    { "value": "free", "label": "Free" },
    { "value": "monthly", "label": "Monthly" },
    { "value": "yearly", "label": "Yearly" },
    { "value": "sales", "label": "Sales" }
  ]
}
```

`subscriptionType=free` selects tenants whose newest management subscription has
`billingPeriod=free`, regardless of the plan code or display language.

## GET /{tenant_id}

Get a tenant.

Response `200`: the resource shape.

Errors:

```text
404 TENANT_NOT_FOUND
```

## PATCH /{tenant_id}

Update tenant name, slug, or owner. When `ownerUserId` changes, the new owner is
automatically added as tenant `admin`.

Request:

```json
{
  "name": "Acme Renamed",
  "slug": "acme-renamed",
  "ownerUserId": "user_456"
}
```

All fields are optional.

Response `200`: the resource shape.

Errors:

```text
404 TENANT_NOT_FOUND
404 USER_NOT_FOUND
409 TENANT_SLUG_EXISTS
```

## PATCH /{tenant_id}/status

Enable or disable a tenant.

Request:

```json
{
  "status": "disabled"
}
```

Allowed values:

- `active`
- `disabled`

Response `200`: the resource shape.

## GET /{tenant_id}/members

List tenant members.

Response `200`:

```json
{
  "items": [
    {
      "userId": "user_123",
      "email": "alice@example.com",
      "name": "Alice",
      "status": "active",
      "role": "admin",
      "joinedAt": "2026-06-03T00:00:00+00:00"
    }
  ]
}
```

## POST /{tenant_id}/members

Add a user to the tenant, or update the role if the membership already exists.
The user must already exist and be active. For non-system team tenants, the
current plan must enable `features.teamManagement`, the resulting member count
must not exceed `seatLimit`, and the user must not already belong to another
active non-system team. Competing additions are serialized in the database.

Request:

```json
{
  "userId": "user_123",
  "role": "member"
}
```

`role` defaults to `member`.

Response `201`: the member shape.

Errors:

```text
404 TENANT_NOT_FOUND
404 USER_NOT_FOUND
403 TENANT_TEAM_MANAGEMENT_NOT_ENTITLED
409 TENANT_MEMBER_USER_DISABLED
409 TENANT_SEAT_LIMIT_EXCEEDED
409 TENANT_USER_ALREADY_IN_TEAM
```

## PATCH /{tenant_id}/members/{user_id}

Update a tenant member role.

Request:

```json
{
  "role": "admin"
}
```

Allowed roles:

- `admin`
- `member`

Response `200`: the member shape.

Errors:

```text
404 TENANT_NOT_FOUND
404 MEMBER_NOT_FOUND
409 TENANT_LAST_ADMIN
```

## DELETE /{tenant_id}/members/{user_id}

Remove a tenant member.

Response:

```text
204 No Content
```

Errors:

```text
404 TENANT_NOT_FOUND
404 MEMBER_NOT_FOUND
409 TENANT_LAST_ADMIN
```

`TENANT_LAST_ADMIN` protects a tenant from ending up with no admin member.

## PATCH /{tenant_id}/subscription

Replace the tenant's effective subscription. The selected plan price must be
enabled and the plan must contain valid credit entitlements.

```json
{
  "planId": "plan_pro",
  "billingPeriod": "monthly",
  "status": "active",
  "currentPeriodStart": null,
  "currentPeriodEnd": null,
  "cancelAtPeriodEnd": false
}
```

The subscription change, any positive current-month credit top-up, and the
audit event commit together. Lower limits do not reclaim current-month credits.

Errors:

```text
404 PLAN_NOT_FOUND
409 PLAN_CREDIT_ENTITLEMENT_REQUIRED
400 PLAN_PRICE_NOT_AVAILABLE
```

Tenant credit summary, ledger, and adjustment endpoints are documented in
[`credits.md`](credits.md).
