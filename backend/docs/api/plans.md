# Plans API

Plan administration is platform-scoped. Reads require `plan:read`; writes require
`plan:write`. Plan-market reads require authentication. A self-service upgrade requires
the current tenant's `tenant:manage`; platform tenant subscription changes require
`platform:tenant_manage`.

## Entitlements

`PlanEntitlements` has this shape:

```json
{
  "id": "plan_entitlement_pro",
  "planId": "plan_pro",
  "monthlyCreditLimit": 20000,
  "allExperts": false,
  "seatLimit": 1,
  "personalLibraryQuotaBytes": 2147483648,
  "teamLibraryQuotaBytes": 0,
  "teamLibraryEnabled": false,
  "singleTurnTokenLimit": null,
  "modelTiers": ["core"],
  "features": {}
}
```

`monthlyQuestionLimit` and `monthlyTokenLimit` were removed without aliases.
`expertIds` remains on the plan itself. When `allExperts=false`, only IDs in
`expertIds` are accessible; an empty list grants no Expert access.

The seeded personal Library quota is 2 GiB on every core plan. Business also
enables a 20 GiB team Library, has five seats, and carries
`features.teamManagement=true`. When an older plan editor omits the three
Library fields from `PUT /entitlements`, Backend preserves their current values;
explicit zero/false values are retained rather than replaced by defaults.

## Core catalog

| ID | code | Monthly credits | Seats | Library | Enabled prices |
| --- | --- | ---: | ---: | --- | --- |
| `plan_free` | `free` | 2,000 | 1 | 2 GiB personal | USD 0 |
| `plan_pro` | `pro` | 20,000 | 1 | 2 GiB personal | USD 20 monthly; USD 200 yearly |
| `plan_max` | `max` | 50,000 | 1 | 2 GiB personal | USD 49 monthly; USD 490 yearly |
| `plan_business` | `business` | 130,000 | 5 | 2 GiB personal + 20 GiB team | USD 2,388 yearly |

Free and Pro include the system default Expert (`1825107e997dfde2`). This is a
reserved cross-environment ID seeded by database migration, not a machine- or
content-derived hash. It is a Runtime defaults template and is always excluded
from the user Expert Market, even if its status is changed to `published`.
Core IDs and codes are immutable; other plan fields remain editable.

Startup migrations insert missing core plans without overwriting an existing
core plan. An empty Free/Pro allowlist is backfilled with the default Expert;
non-empty allowlists are preserved. Existing development-cutover conflict
handling remains unchanged.

## Administration routes

```text
GET    /api/v1/plans
POST   /api/v1/plans
GET    /api/v1/plans/{plan_id}
PATCH  /api/v1/plans/{plan_id}
DELETE /api/v1/plans/{plan_id}
PUT    /api/v1/plans/{plan_id}/prices
PUT    /api/v1/plans/{plan_id}/entitlements
PUT    /api/v1/plans/{plan_id}/experts
```

Custom plans may be created without entitlements while being configured, but
cannot be assigned to a tenant until they have a valid non-negative
`monthlyCreditLimit` and boolean `allExperts`.

Core-plan protection errors:

```text
409 CORE_PLAN_CODE_IMMUTABLE
409 CORE_PLAN_DELETE_FORBIDDEN
```

## Plan market

```text
GET /api/v1/plan-market/plans
GET /api/v1/plan-market/current-subscription
PATCH /api/v1/plan-market/current-subscription
```

The current-subscription route preserves the existing fallback behavior: when
the tenant has no effective subscription, it creates an active Free
subscription. Registration and tenant creation also use Free.

The PATCH route accepts `{"planId": "plan_pro"}`. It selects the first enabled
price returned on that plan, matching the price displayed by the current
subscription page. The target must be an active, higher-level plan with a
non-sales price and credit entitlements. Repeating the request for the current
plan is a no-op and returns the existing subscription. The route activates the
plan directly; payment collection and order creation are outside the current
Backend contract.

## Tenant subscription change

```text
PATCH /api/v1/tenants/{tenant_id}/subscription
```

The selected price must be enabled and the target plan must have credit
entitlements. In the same request transaction, the Backend replaces the active
subscription, applies any positive current-month credit top-up, writes the
audit event, and commits. A higher monthly credit limit grants only the
difference above the month's historical highest limit. A lower limit does not
reclaim credits.

Missing entitlements return:

```text
409 PLAN_CREDIT_ENTITLEMENT_REQUIRED
```
