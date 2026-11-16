# Knowledge Bases API

Base path:

```text
/api/v1/knowledge-bases
```

Knowledge bases are **platform-authored resources**. They have **no tenant relationship**
at all: they carry no `tenant_id`, tenant roles hold no `kb:*` / `doc:*` permissions, and
tenants never own or operate them. Tenants consume knowledge bases only through product
workflows (chat).

All endpoints require a platform role and platform permissions:

```text
Authorization: Bearer <accessToken>
```

No `x-tenant-id` header is used. Metadata is stored in this project's database.
See the current
[Knowledge Base Indexing](../KNOWLEDGE_BASE_INDEXING.md).

## Resource shape

```json
{
  "id": "kb_123",
  "ownerUserId": "user_123",
  "ownerUserName": "Jane Expert",
  "name": "Amazon Reviews",
  "description": "Review analysis corpus",
  "status": "active",
  "indexStatus": "ready",
  "indexError": null,
  "indexWorkspace": "kb_123",
  "metadata": {},
  "createdAt": "2026-06-03T10:00:00Z",
  "updatedAt": "2026-06-03T10:00:00Z"
}
```

The shape is intentionally minimal:

- `status` is the lifecycle field. `active` permits management/serving and `archived` blocks
  active-only writes with `409 KB_ARCHIVED`.
- `indexStatus` and `indexError` report the isolated Controller instance lifecycle. Chat must not
  infer retrieval readiness from `status` alone.
- There is **no** `scope` / `visibility`. All knowledge bases are platform-owned; access is
  decided purely by the platform permission on each route. Any future sharing rules belong in
  a dedicated table, not in this business table.
- `ownerUserId` is **creator attribution only**, not an access-control input.
- `ownerUserName` is the current display name for `ownerUserId`; it may be `null` if the
  owner user is absent.

## Authorization

Who may act is decided entirely by the platform permission on the route (`kb:*` / `doc:*`).
There is no ownership or visibility check: any platform user holding the relevant permission
may operate any knowledge base. The only resource-level rule is the lifecycle one — an
`archived` knowledge base rejects writes (`409 KB_ARCHIVED`).

This is not tenant isolation — tenant principals cannot reach these routes at all.

## POST /

Create a knowledge base. Required permission: `kb:create`.

Request:

```json
{
  "name": "Amazon Reviews",
  "description": "Review analysis corpus",
  "metadata": {}
}
```

Response: `201 Created` with the resource shape above (`status` defaults to `active`).

## GET /

List active knowledge bases. Required permission: `kb:read`.

Response:

```json
{
  "items": [
    {
      "id": "kb_123",
      "ownerUserId": "user_123",
      "ownerUserName": "Jane Expert",
      "...": "..."
    }
  ]
}
```

## GET /{knowledge_base_id}

Get a knowledge base. Required permission: `kb:read`. Response: the resource shape.

## PATCH /{knowledge_base_id}

Update a knowledge base. Required permission: `kb:update`. All fields optional:

```json
{
  "name": "Updated Name",
  "description": "Updated description",
  "metadata": {}
}
```

`status` is **not** editable here — lifecycle transitions have their own endpoints below.
Rejected while the base is `archived` (`409 KB_ARCHIVED`).

## POST /{knowledge_base_id}/archive

Retire a knowledge base (`active` → `archived`). Required permission: `kb:update`.
Response: `200 OK` with the resource shape, `status: "archived"`. Archived bases disappear
from `GET /` but remain readable by id. Archiving an already-archived base returns
`409 KB_ARCHIVED` (not idempotent by design).

## POST /{knowledge_base_id}/activate

Restore a knowledge base (`archived` → `active`). Required permission: `kb:update`.
This is the one write allowed on an archived base — it bypasses the lifecycle gate.
Response: `200 OK` with the resource shape, `status: "active"`. Activating an already-active
base is an idempotent no-op (`200 OK`).

## DELETE /{knowledge_base_id}

Delete a knowledge base. Required permission: `kb:delete`. Response: `204 No Content`.

## Nested resources

- Documents: [documents API](./documents.md) under `/{knowledge_base_id}/docs/*`.
- Index approval: [knowledge index API](./knowledge-index.md) under
  `/{knowledge_base_id}/index-review*`.
