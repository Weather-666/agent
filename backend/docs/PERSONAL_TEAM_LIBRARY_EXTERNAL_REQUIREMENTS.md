# Personal and Team Library: External Requirements

> The Backend contract is implemented in this checkout, while cross-component rollout and live
> product acceptance remain pending. This file records required changes outside the authorized
> Backend-only scope. No Frontend, Gateway, AGW Manager, Compose or root configuration was changed
> by this delivery.

## Runtime and Compose

Set the Backend environment variable below to an origin that the Agent runtime can reach:

```text
EXPERT_LIBRARY_DELIVERY_PUBLIC_BASE_URL=http://backend:8000
```

The value must resolve to the Backend service from the Gateway/Agent network and must not point at
MinIO. Browser preview/download URLs remain relative and do not require this setting. Production
should use the protected internal Backend origin or an HTTPS route; do not publish a predictable
delivery token or log its path.

The existing upload flow still needs the browser to reach the returned PUT URL. Preserve the current
object-store CORS and public upload-origin settings. Agent attachment reads no longer require direct
MinIO reachability because they use the Backend delivery endpoint.

## Gateway and Agent runtime

- Permit the Agent runtime to make HTTP GET requests to the configured Backend origin.
- Do not rewrite `/api/v1/library/delivery/*` to MinIO or cache responses.
- Preserve the full random token path and do not add it to access logs if log redaction is available.
- A delivery GET may return `404` or `410` after membership removal, subscription downgrade, token
  expiry or use exhaustion; the runtime should surface this as an attachment-read failure.
- A legacy/archive delivery attempt returns `LIBRARY_AGENT_FORMAT_UNSUPPORTED`; the runtime must not
  retry ZIP/RAR as Agent-readable attachments.

No Gateway authorization rule should replace Backend request-time checks. The URL token is only a
bounded transport capability.

## Frontend

The Frontend should consume Backend capabilities rather than duplicate plan/role logic:

1. Load `GET /api/v1/library/spaces` and show personal/team tabs plus quota usage.
2. Hide the team tab when `status=none`; render `read_only` visibly and disable upload/rename/Agent
   selection according to `capabilities`.
3. Send `spaceType` on list and upload-url calls. Do not infer ownership from uploader.
4. Show `nameConflict`/`suggestedName` before PUT as a hint; use the completed file's returned name as
   final truth.
5. Support per-item batch results; a failed item must not roll back successful siblings.
6. Follow preview/download `url` values with the normal bearer token and `x-tenant-id` headers.
7. Treat `uploadedByUserId=null` as valid historical attribution, not a missing/corrupt file.
8. Refresh space/file capabilities after subscription or membership changes and after quota errors.
9. Allow ZIP/RAR upload, listing and download, but disable them in Agent attachment pickers and
   surface `LIBRARY_AGENT_FORMAT_UNSUPPORTED` if stale client state submits one.

The Agent turn request remains `attachmentFileIds`; the Frontend must never receive or persist the
Agent delivery token.

## Operations

- Schedule authenticated `POST /api/v1/ops/storage/gc` so failed/expired reservations and deleted
  objects are reclaimed.
- Monitor `GET /api/v1/ops/storage/library-usage-reconciliation`; alert when `mismatchCount > 0`.
- Keep migration startup serialized by the existing deployment procedure. Migrations are idempotent
  for both SQLite and PostgreSQL, but application replicas should not independently bypass the
  normal migration owner.
- Do not repair quota by patching object storage. Investigate database ledger/session/file rows and
  use a reviewed Backend repair path if reconciliation reports drift.
