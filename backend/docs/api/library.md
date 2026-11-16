# Library API

Base path: `/api/v1/library`. Unless stated otherwise, routes require a bearer token,
`x-tenant-id`, and the tenant `chat:ask` permission.

## Space state

`GET /spaces` returns personal and team state, quota ledger values and request-time capabilities:

```json
{
  "items": [
    {
      "spaceType": "personal",
      "status": "full",
      "quotaBytes": 2147483648,
      "usedBytes": 1024,
      "reservedBytes": 0,
      "remainingBytes": 2147482624,
      "capabilities": {
        "list": true,
        "read": true,
        "upload": true,
        "rename": true,
        "delete": true,
        "promote": true,
        "useAgent": true
      }
    }
  ]
}
```

Team `status` is `full`, `read_only` or `none`. Clients must render the returned capabilities rather
than reproduce role/subscription policy locally.

## Listing

`GET /files` query parameters:

- `spaceType=personal|team` (default `personal`)
- `keyword`
- `type=all|image|file`
- `sort=updatedAt_desc|updatedAt_asc|name_asc|name_desc|size_desc|size_asc`
- `page`, `pageSize`
- `lifecycle=permanent|temporary` and optional `sessionId` (temporary is personal-only)

Each item includes `spaceType`, stable owner ids, nullable `uploadedByUserId`, lifecycle and per-file
capabilities.

## Upload

`POST /files/upload-url`:

```json
{
  "fileName": "roadmap.pdf",
  "mimeType": "application/pdf",
  "fileSizeBytes": 8192,
  "spaceType": "team"
}
```

The response contains a backend-generated object key, short-lived PUT URL, required headers,
`nameConflict` and `suggestedName`. The byte count is reserved before the response is committed.

After a successful PUT, call `POST /files/complete-upload`:

```json
{
  "uploadSessionId": "upl_...",
  "lifecycle": "permanent"
}
```

Completion reauthorizes access, rechecks the current quota against used plus reserved bytes, and
validates stored size plus actual content. It returns `201` with the durable `LibraryFile`.
`lifecycle=temporary` is accepted only for personal space. A contract/quota change releases the
reservation, removes the uploaded object and creates no permanent file row.

Batch routes accept 1-50 items:

- `POST /files/upload-urls` with `{ "items": [<upload-url request>, ...] }`
- `POST /files/complete-uploads` with `{ "items": [<complete request>, ...] }`

They are non-atomic; every result is `created|failed` or `completed|failed` with an item or typed
error.

## Rename, promotion and delete

- `PATCH /files/{file_id}` with `{ "name": "new-name.pdf" }`
- `POST /files/{file_id}/promote`
- `DELETE /files/{file_id}`

Upload completion auto-suffixes concurrent duplicate names. Rename is exact and returns
`LIBRARY_NAME_CONFLICT` rather than auto-suffixing. Team rename/delete is allowed to the uploader or
an admin while full; during read-only only an admin may delete.

## Preview and download

- `GET /files/{file_id}/preview`
- `GET /files/{file_id}/download`
- `GET /files/{file_id}/content?disposition=inline|attachment`

Text/DOCX preview may return extracted text. Other supported preview types and downloads return a
relative authenticated Backend content URL. The caller must include the same auth and tenant headers
when following it. Authorization is reloaded before bytes are streamed.
Each successful byte read writes a metadata-only `library.content_read` audit event.

## Agent-only delivery

`GET /delivery/{token}` is an unauthenticated bearer-capability endpoint used only by the Agent
runtime. Tokens are random, short-lived, turn-bound, limited-use and request-time reauthorized. They
must not be stored by clients, logs or audit events. Each successful consume writes a
`library.agent_delivery_consumed` event without token, URL, object key or content. ZIP/RAR files can
be stored and downloaded but are never accepted for Agent attachment or delivery.

## Important errors

| Code | Meaning |
| --- | --- |
| `LIBRARY_UNSUPPORTED_FORMAT` | Extension is outside the allowlist. |
| `LIBRARY_MIME_MISMATCH` | Declared MIME conflicts with extension. |
| `LIBRARY_CONTENT_MISMATCH` | Stored bytes fail actual-format validation. |
| `LIBRARY_FILE_TOO_LARGE` | Per-format maximum exceeded. |
| `LIBRARY_QUOTA_EXCEEDED` | Used + reserved + request exceeds entitlement. |
| `LIBRARY_QUOTA_CHANGED` | Current contract/quota no longer permits completion. |
| `LIBRARY_NAME_CONFLICT` | Exact rename or concurrent claim conflicts. |
| `LIBRARY_AGENT_FORMAT_UNSUPPORTED` | ZIP/RAR is valid Library content but not an Agent attachment. |
| `TEAM_LIBRARY_READ_ONLY` | Mutation/Agent use denied after expiry or downgrade. |
| `LIBRARY_ACTION_FORBIDDEN` | Role or current space state denies the action. |
| `LIBRARY_DELIVERY_REVOKED` | Delivery authorization no longer holds. |
| `LIBRARY_DELIVERY_EXPIRED` | Capability expired or exhausted. |

See [`../USER_LIBRARY_DESIGN.md`](../USER_LIBRARY_DESIGN.md) for authorization, quota and format
details.
