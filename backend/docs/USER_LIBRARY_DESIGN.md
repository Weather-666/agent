# Personal and Team Library Design

> Status: the Backend contract is implemented and regression-tested in this checkout; external
> component rollout remains pending. The database is the authorization and metadata source of
> truth; object storage owns bytes only. API details are in [`api/library.md`](./api/library.md), temporary-file
> rules are in [`LIBRARY_FILE_LIFECYCLE.md`](./LIBRARY_FILE_LIFECYCLE.md), and deployment work that
> belongs outside Backend is recorded in
> [`PERSONAL_TEAM_LIBRARY_EXTERNAL_REQUIREMENTS.md`](./PERSONAL_TEAM_LIBRARY_EXTERNAL_REQUIREMENTS.md).

## Product contract

Every active user has a personal Library. The normal entitlement is 2 GiB and is represented by
`personalLibraryQuotaBytes` on the current plan. Personal files are owned by `owner_user_id` and are
available only to that user, independent of the active team's membership list.

A team Library belongs to `owner_tenant_id`, never to the uploader. It has three request-time states:

| State | Condition | Member behavior |
| --- | --- | --- |
| `full` | Current usable subscription has `teamLibraryEnabled=true` | List, read, upload and use in Agent turns. Admins or the uploader may rename/delete. |
| `read_only` | Team previously had the entitlement but the current subscription no longer has it | Members may list/read/download. Admins may delete. Upload, rename and Agent use are denied. |
| `none` | Team has never had the entitlement | No team Library access. |

The seeded Business plan enables a 20 GiB team Library and five seats. Renewal restores `full`
access to the same rows and objects; expiry or downgrade does not copy or delete bytes. The
monotonic `team_library_entitlement_history` row records acquisition and maximum historical quota,
so `read_only` never depends on a mutable current Plan document. Migration replay idempotently
backfills Business history even if an operator has since disabled that Plan key; custom plans are
backfilled from their current entitlement and are recorded whenever a live subscription acquires
the feature. User status, team membership, role and current subscription are reloaded on every
operation.

Team membership writes also enforce the current plan's `features.teamManagement` flag, `seatLimit`,
active-user status and the rule that a user may belong to at most one active non-system team.
PostgreSQL row locks and SQLite `BEGIN IMMEDIATE` serialize competing seat allocations.

## Ownership and schema

`library_files` and `library_upload_sessions` use explicit ownership fields:

- personal: `space_type='personal'`, `owner_user_id` set, `owner_tenant_id` null;
- team: `space_type='team'`, `owner_tenant_id` set, `owner_user_id` null;
- `uploaded_by_user_id` is attribution only and uses `ON DELETE SET NULL`;
- legacy `user_id` is nullable attribution and also uses `ON DELETE SET NULL`.

Deleting or disabling an uploader therefore never removes a team file. Tenant deletion still cascades
team-owned rows. Owner invariants are database checks on fresh databases and existing PostgreSQL;
the SQLite migrator rebuilds legacy Library tables once because SQLite cannot alter the old uploader
foreign key or nullability in place.

Object keys are backend-generated, ASCII-safe organization hints:

```text
personal: library/users/{user_id}/{file_id}/{safe_name}
team:     library/{tenant_id}/team/{file_id}/{safe_name}
```

Authorization never derives from a key or object-store URL.

## Quota accounting

`library_space_usage` is a transactional ledger keyed by `(space_type, owner_key)`:

- upload-url creation atomically reserves the declared byte count only when
  `used_bytes + reserved_bytes + request <= quota`;
- completion reauthorizes the current contract and rejects when the live quota is zero or the
  current ledger total exceeds it, even if the earlier reservation succeeded;
- completion atomically converts the reservation to used bytes;
- validation failure, upload-session expiry and failed completion release the reservation;
- soft delete and temporary-file expiry release used bytes immediately;
- object removal is a later idempotent GC operation.

`GET /api/v1/ops/storage/library-usage-reconciliation` compares the ledger with live file and upload
session rows without mutating either side. It is the operational proof for detecting drift.

## File and name validation

The Backend checks the declared extension, declared MIME (when present), maximum size, uploaded
object size and actual file signature/content before a row becomes visible.

| Group | Extensions | Maximum |
| --- | --- | ---: |
| Documents | `pdf doc docx xls xlsx ppt pptx txt md csv` | 20 MiB |
| Images | `jpg jpeg png webp` | 10 MiB |
| Archives | `zip rar` | 50 MiB |

Text must be bounded UTF-8 without NUL/control bytes. ZIP/OOXML containers must parse, and OOXML
must carry its type-specific directory plus `[Content_Types].xml`. Validation failure marks the
session failed, releases quota and removes the uploaded object on a best-effort basis.

ZIP and RAR are storage/download formats only. They are rejected with
`LIBRARY_AGENT_FORMAT_UNSUPPORTED` during turn preflight, actual binding, capability creation and
legacy capability consumption, so an archive never becomes an Agent attachment.

Permanent names are normalized with Unicode NFKC plus case-folding. `library_name_claims` supplies a
database uniqueness boundary under concurrency. Upload completion allocates `name (1).ext`,
`name (2).ext`, and so on; upload-url responses expose `nameConflict` and `suggestedName` as an early
hint only. Rename never silently changes the requested name and returns `LIBRARY_NAME_CONFLICT`.
Batch allocation/completion is deliberately non-atomic and reports success or failure per item.

## Delivery and audit

Browser preview/download responses point back to authenticated Backend `/content` routes. The
Backend reauthorizes the current user/team state and then streams bytes; it never gives the browser a
durable object-store GET capability.

Agent turns receive a random Backend delivery capability tied to file, actor, tenant and turn. The
capability is short-lived, limited to three successful consumes, and rechecks current user status,
membership, ownership and team `full` state on every GET before consuming the token. Removing a
member or downgrading a team therefore revokes an already issued URL immediately.

Successful upload completion, rename, delete, authenticated browser byte reads and Agent capability
consumes write metadata-only `library` audit events. Read events contain only file identity/type/size,
space, disposition or turn id. File content, object keys, credentials, signed object-store URLs and
delivery tokens are never written to audit data.

## Cleanup

`POST /api/v1/ops/storage/gc` expires pending upload sessions, purges soft-deleted Library objects,
and removes expired temporary chat files. The passes are idempotent and leave a row for retry when
object removal fails. Migration replay does not pre-mark expired upload sessions, because the normal
GC path must release their reserved quota first.

## Storage breakdown

GET /api/v1/library/spaces includes permanent/temporary fileCount, fileBytes,
imageCount and imageBytes across all completed, nondeleted files, independent of pagination.
Expired files count until GC; upload reservations remain separate in reservedBytes.
