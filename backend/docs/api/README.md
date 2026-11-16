# Experts Backend API

Base path:

```text
/api/v1
```

Health check:

```text
GET /health
```

Swagger UI is available when the FastAPI app is running:

```text
GET /docs
```

The generated OpenAPI schema can be exported locally to the ignored file:

```text
docs/api/openapi.json
```

Run `python scripts/export_api_docs.py` to refresh it and the checked-in
`docs/api/API_REFERENCE.md` from the current FastAPI application.

## Authentication

Most APIs require:

```text
Authorization: Bearer <accessToken>
```

Tenant-scoped product APIs also require:

```text
x-tenant-id: <tenant_id>
```

Platform-scoped APIs do not require `x-tenant-id`; they require current platform
roles and derived permissions.

For authenticated requests, the API decodes the access token and then reloads
the user, tenant roles and platform roles from the database before checking
permissions. Role changes, tenant membership removal and user disablement
therefore apply immediately even when an existing access token has not expired.

## Permission Scopes

Tenant permissions are resolved from `tenant_members.role`:

- `admin`
- `member`

Platform permissions are resolved from `platform_user_roles.role`:

- `admin`
- `expert`
- `operator`

See [auth.md](./auth.md) for token details and [rbac.md](./rbac.md) for
permission management.

Access tokens contain roles only. Expanded permission lists are never used as
token claims; they are derived server-side from the current role mapping.

## API Groups

- [Auth](./auth.md)
- [Users](./users.md)
- [Tenants](./tenants.md)
- [RBAC](./rbac.md)
- [Knowledge Bases](./knowledge-bases.md) (platform-owned lifecycle and isolated index state)
- [Documents](./documents.md) (nested under a knowledge base; shared object storage upload)
- [Experts](./experts.md) (platform-owned expert categories, experts and expert groups)
- [Featured Examples](./featured-examples.md) (ordered questions, review, expiry and accepted-use counts)
- [Expert Runtime publication](./expert-runtime.md) (Builder, Gateway and real ACP validation)
- [Plans](./plans.md) (plan configuration, plan market and current subscription)
- [Credits](./credits.md) (tenant credit summary, ledger and manual adjustments)
- [Knowledge index](./knowledge-index.md) (automatic sync and explicit approval for large batches)
- [Chat](./chat.md) (byte-current isolated retrieval, finalized source roles and citation preview/download)
- [Library](./library.md) (personal/team spaces, quota, upload, secure delivery and lifecycle)
- [Skills](./skills.md)
- [Models and Ops](./models-ops.md)

Knowledge-base storage, object upload, indexing and chat-time retrieval are described in the
[Knowledge Base Indexing](../KNOWLEDGE_BASE_INDEXING.md).

## Response Format

Successful responses generally return JSON, except:

- `204` responses have no body.
- `GET /skills/{slug}/file` returns `text/markdown`.
- `POST /chat/sessions/{session_id}/turns` and `GET /chat/turns/{turn_id}/events`
  return `text/event-stream`.

Errors are raised through the project API error handler and include an error
code and message.
