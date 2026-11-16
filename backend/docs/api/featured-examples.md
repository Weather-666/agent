# Featured Examples API

Featured examples are platform-authored questions in real, ordered categories. The Backend
stores the catalog in `featured_example_categories` and `featured_examples`, independently
of Experts and Chat. Migrations do not seed examples.

All paths below have the `/api/v1` prefix.

## Authentication and permissions

Management requests require `Authorization: Bearer <accessToken>` and exact platform
permissions. They do not require a tenant header.

| Platform role | featured_example:read | featured_example:write | featured_example:publish |
| --- | --- | --- | --- |
| admin | Yes | Yes | Yes |
| expert | Yes | Yes | No |
| operator | Yes | No | No |

Market list and use requests require `Authorization`, the current `x-tenant-id`, and
tenant permission `chat:ask`. Example use grants no additional access to Experts or Chat.

## Management endpoints

| Method and path | Permission suffix | Request | Successful response |
| --- | --- | --- | --- |
| GET /featured-categories | read | None | 200 `{items}` |
| POST /featured-categories | write | `{name, tone}` | 201 category |
| PATCH /featured-categories/{id} | write | `{name?, tone?}` | 200 category |
| DELETE /featured-categories/{id} | write | None | 204 |
| PUT /featured-categories/order | write | `{ids: [...]}` | 200 `{items}` of categories |
| GET /featured-examples | read | Optional filters below | 200 `{items, counts}` |
| POST /featured-examples | write | `{categoryId, question, reviewCycleDays?}` | 201 example |
| GET /featured-examples/{id} | read | None | 200 example |
| PATCH /featured-examples/{id} | write | `{categoryId?, question?, reviewCycleDays?}` | 200 example |
| DELETE /featured-examples/{id} | write | None | 204 |
| PUT /featured-categories/{id}/examples/order | write | `{ids: [...]}` | 200 `{items}` of examples |
| POST /featured-examples/{id}/review | publish | Review request below | 200 example |
| POST /featured-examples/{id}/unlist | publish | None | 200 example |

Categories use trimmed names of 1-60 characters and a `tone` of `blue`, `green`,
`violet`, or `orange`. Category responses contain `id`, `name`, `short`, `tone`,
`sortOrder`, `createdAt`, and `updatedAt`. The server derives `short` from the first
two characters of the name.

Questions are trimmed and must contain 1-4000 characters. A referenced category must exist.
`reviewCycleDays` accepts only integer `30`, `60`, `90`, or `null`; creation defaults to
`null` (no expiry). Request models reject unknown fields, including client-supplied
`status`, `clickCount`, author identifiers, and timestamps.

PATCH distinguishes omission from explicit null: omitted fields remain unchanged, and
`reviewCycleDays: null` clears the cycle. `name`, `tone`, `categoryId`, and `question`
cannot be explicitly null. An empty or unchanged PATCH preserves state and `updatedAt`.

New categories and examples append to their respective lists. Moving an example appends it
to its destination category. Each order request must contain every ID in the target
collection exactly once. Missing, duplicate, or foreign IDs reject the entire request.
Management transactions serialize catalog edits so concurrent inserts, moves, or deletes
cannot invalidate full-set order checks. Categories containing examples cannot be deleted.
Deleting an example does not affect existing Chat history.

## Example response and filters

```json
{
  "id": "featured_example_123",
  "categoryId": "featured_category_123",
  "question": "What could cause advertising ACOS to increase?",
  "sortOrder": 0,
  "status": "live",
  "reviewCycleDays": 60,
  "reviewState": "normal",
  "reviewedAt": "2026-09-08T08:00:00.000000+00:00",
  "expiresAt": "2026-11-07T08:00:00.000000+00:00",
  "rejectReason": null,
  "clickCount": 0,
  "createdBy": "user_123",
  "authorName": "Current author name",
  "updatedBy": "user_123",
  "reviewedBy": "admin_123",
  "createdAt": "2026-09-08T07:00:00.000000+00:00",
  "updatedAt": "2026-09-08T08:00:00.000000+00:00"
}
```

Actor identifiers come from authenticated actions. `authorName` is the creating user's
current stored name. Deleting that user preserves examples and sets the affected actor
identifiers to null; `authorName` is also null when the creating user no longer exists.

`GET /featured-examples` accepts `categoryId`, `status`, `reviewState`, and `keyword`.
Keyword matching is case-insensitive against the question. The response is a full list
without pagination. Results follow category order, category ID, example order, and example
ID.

`counts` contains `total`, `live`, `pending`, `reviewing`, `rejected`, `unlisted`,
`expiring`, and `expired`. Counts cover the selected category, or every category when
none is selected. Status, review-state, and keyword filters affect `items` only.
`expiring` and `expired` count their respective derived review states separately.

## Review, expiry, and content changes

| Action | Allowed current status | Result |
| --- | --- | --- |
| Create | None | pending |
| Change question, category, or cycle | Any | pending; clear previous review, expiry, and rejection reason |
| Approve | pending, rejected, unlisted, reviewing | live; calculate review time and expiry |
| Reject | pending, reviewing | rejected; record reviewer, review time, and reason; clear expiry |
| Unlist | live or reviewing | unlisted; preserve previous review details and expiry |

Unchanged content and reordering preserve review status. Reordering changed positions
updates `updatedAt` and therefore invalidates older review requests. Valid live examples
cannot be approved again to extend their expiry. Unlisted examples return through approval.

Approval request:

```json
{"decision": "approve", "expectedUpdatedAt": "2026-09-08T07:00:00.000000+00:00"}
```

Rejection request:

```json
{
  "decision": "reject",
  "expectedUpdatedAt": "2026-09-08T07:00:00.000000+00:00",
  "reason": "Please make the question more specific."
}
```

Rejection reasons are trimmed, nonempty, and limited to 4000 characters. Send the detail
response's `updatedAt` as `expectedUpdatedAt`. It must include a timezone; offsets are
normalized to UTC. The service checks it and conditionally updates the matching stored
timestamp and status in the same transaction. A changed example returns
`409 FEATURED_EXAMPLE_CHANGED`; reload before reviewing it again.

All returned timestamps use UTC with a `+00:00` offset and microseconds. Approval computes
`expiresAt = reviewedAt + reviewCycleDays`, or null for no expiry. An expiry equal to the
server's current time is already expired. Stored `live` records past expiry return the
derived `status: reviewing`; this value is never stored or accepted from clients.

Derived `reviewState` values are `none` for no expiry, `expired` for expiry at or before
now, `expiring` for a future expiry within seven days inclusive, and `normal` otherwise.
Reads derive these values with one server time and never update records. There is no expiry
scheduler. Expiry closes the example entry point; an existing Chat turn continues normally.

## Market list and use

`GET /featured-market/examples` accepts optional `categoryId` and returns only valid live
examples in the same stable category/example order:

```json
{
  "items": [{
    "id": "featured_example_123",
    "question": "What could cause advertising ACOS to increase?",
    "categoryId": "featured_category_123",
    "categoryName": "Operations",
    "categoryTone": "blue",
    "sortOrder": 0,
    "clickCount": 0
  }]
}
```

Management details, draft content, rejection reasons, and actor identifiers are absent.

`POST /featured-market/examples/{id}/use` has no request body. It atomically checks that
the current record is live and unexpired, increments `click_count`, and returns that
update's question with `200`:

```json
{
  "id": "featured_example_123",
  "question": "What could cause advertising ACOS to increase?",
  "clickCount": 1
}
```

Only after use succeeds should the caller submit the returned question through existing
`POST /chat/sessions` and `POST /chat/sessions/{sessionId}/turns`, retaining the user's
selected Expert and normal Chat authorization. No example identifier, cached answer, or
new model field is added to Chat. The returned question is the accepted snapshot; subsequent
edits do not rewrite the conversation.

Every accepted use request counts once. The count measures accepted requests, not unique
users or successful model turns; later model failure does not undo it. Do not automatically
retry use. GETs, reviews, and failed use requests do not increment it. Click updates do not
change content `updatedAt` or invalidate review requests. Concurrent increments are not
overwritten by content edits.

## Audit and errors

Actual management changes use the existing audit transaction with category
`featured_example`. Actions are `featured_category.create/update/delete/reorder` and
`featured_example.create/update/delete/reorder/review/unlist`. Business data and audit
events commit or roll back together. Audit fields contain necessary identifiers, state,
cycle, order, and a question-change flag; question text and rejection reasons are not copied
into audit records. Reads, unchanged updates/orders, and use requests produce no management
audit event.

Business errors use the existing `{code, message, details?}` envelope and request-ID
middleware. Authentication and authorization retain existing `401`/`403` codes.
Invalid request fields return the existing `422 {detail: [...]}` validation response.

| Status | Code | Meaning |
| --- | --- | --- |
| 404 | FEATURED_CATEGORY_NOT_FOUND | The referenced category does not exist |
| 409 | FEATURED_CATEGORY_NOT_EMPTY | Move or delete its examples before deleting the category |
| 404 | FEATURED_EXAMPLE_NOT_FOUND | The referenced example does not exist |
| 409 | FEATURED_EXAMPLE_UNAVAILABLE | Use was denied because the example is not currently valid live content |
| 409 | FEATURED_INVALID_TRANSITION | Review or unlist is invalid for the current state |
| 409 | FEATURED_EXAMPLE_CHANGED | Review timestamp or current-state condition no longer matches |
| 409 | FEATURED_ORDER_INVALID | The submitted order does not exactly cover its target collection |
