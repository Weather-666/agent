# Library File Lifecycle

> Status: implemented. This document is the current lifecycle contract for both personal and team
> Library files. Ownership, quota and team subscription behavior are defined in
> [`USER_LIBRARY_DESIGN.md`](./USER_LIBRARY_DESIGN.md).

## States

Completed rows use one of two lifecycle values:

- `permanent`: normal personal or team Library content; `expires_at` must be null.
- `temporary`: personal chat upload; `expires_at` must be set. Team temporary uploads are rejected.

The invariant is enforced by the canonical table check and an idempotent PostgreSQL migration block.
Existing SQLite Library tables are rebuilt once so their checks, uploader foreign keys and owner
columns match the canonical schema.

Upload sessions use `initiated`, `completed`, `failed` or `expired`. An initiated session owns a quota
reservation. A session may become completed only after the Backend has reauthorized the actor,
rechecked the current quota against the full ledger, and verified object size and actual format.
Contract/quota change, validation failure or expiry releases the reservation before object cleanup.

## Unified upload

There are no `/chat/attachments/*` endpoints. Both permanent and temporary files use:

```text
POST /api/v1/library/files/upload-url
PUT  <returned uploadUrl>
POST /api/v1/library/files/complete-upload
```

`complete-upload` defaults to `lifecycle=permanent`; passing `temporary` creates a personal,
unbound chat file. Batch forms (`upload-urls`, `complete-uploads`) are non-atomic and report each item.

An upload URL is only a write capability. Reading never uses the upload URL, and object storage never
decides whether a user may list, preview, download, delete or use a file in an Agent turn.

## Temporary binding and promotion

A new temporary file has `chat_session_id=null`. The first authorized turn that references its id
binds it exactly once with a conditional update. Subsequent turns in that same session may reuse it;
another session receives `LIBRARY_FILE_FORBIDDEN`. Temporary listing is owner-scoped and excludes
expired rows:

```text
GET /api/v1/library/files?lifecycle=temporary
GET /api/v1/library/files?lifecycle=temporary&sessionId={session_id}
```

`POST /api/v1/library/files/{id}/promote` changes a live personal temporary row to permanent without
copying bytes. Promotion verifies the file is still temporary and unexpired before claiming a unique
permanent display name. Re-promotion and expired promotion return `LIBRARY_FILE_NOT_PROMOTABLE`.

## Turn authorization and provenance

`attachmentFileIds` may reference:

- the actor's permanent personal files;
- the actor's unexpired temporary personal files, subject to session binding;
- files in the active team's Library only while current membership and team `full` entitlement hold.

ZIP and RAR files remain valid Library storage/download content but are never valid
`attachmentFileIds`; preflight, bind and delivery-consume paths reject them
with `LIBRARY_AGENT_FORMAT_UNSUPPORTED`.

The turn route performs an authorization-only preflight before opening SSE, then the streaming path
rechecks and binds. A denial is an HTTP error rather than an empty successful stream.

Each turn stores a metadata snapshot in `chat_turns.attachments` containing file id, display name,
MIME, byte size, lifecycle, space type, team owner, uploader and attachment time. This provenance
survives file GC and never contains content or delivery tokens.

## Agent delivery

After turn creation, the Backend mints one `library_delivery_capabilities` row per attachment. Its
URL is built from `EXPERT_LIBRARY_DELIVERY_PUBLIC_BASE_URL` and must resolve to Backend from the
Agent runtime:

```text
GET {backend-origin}/api/v1/library/delivery/{random-token}
```

The capability is tied to the file, actor, active tenant and turn, expires according to
`attachment_delivery_url_ttl_seconds`, and allows at most three successful reads. Every GET checks
the current file owner, active user, team membership and team entitlement before atomically
incrementing its use count. Authorization loss returns a generic revoked/expired response without
exposing storage metadata.

Each successful capability consume writes a metadata-only audit event in the same transaction as
the use-count increment. If object read or audit persistence fails, the consume is rolled back.

## Deletion and GC

User deletion is a soft delete: the name claim and used quota are released in the same transaction,
while object removal is deferred. `POST /api/v1/ops/storage/gc` performs three relevant passes:

1. expire initiated Library upload sessions and release reservations;
2. remove objects for soft-deleted Library files and hard-delete rows only after successful removal;
3. soft-delete, de-account and remove expired temporary files.

Deleting a chat session does not delete its temporary files early. Their independent retention
deadline and the GC pass are the cleanup contract.

## Agent filename reads

Published Experts expose find_personal_file and read_personal_file through personal_library MCP.
Only the current owner's permanent personal files are eligible. A unique exact name reads text;
ambiguous matches return candidates for clarification. Reads accept offset and return nextOffset,
with at most 12000 characters per call and a 20 MiB object limit. Each call validates the running
Turn capability and rechecks access after parsing. Read provenance and audits contain metadata only.

Default ACP sessions also receive owner-scoped Library Turn authorization. Configure the existing default service using [DEFAULT_LIBRARY_RUNTIME.md](DEFAULT_LIBRARY_RUNTIME.md); bound Expert publication is unchanged.
