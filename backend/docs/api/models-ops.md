# Models and Ops API

## Models

Base path:

```text
/api/v1/models
```

All model APIs are tenant-scoped and require:

```text
Authorization: Bearer <accessToken>
x-tenant-id: <tenant_id>
```

### GET /llm

List available LLM models.

Current response:

```json
{
  "models": [
    {
      "id": "codex/gpt-5",
      "isDefault": true
    }
  ]
}
```

### GET /embedding

Get embedding or retrieval model metadata.

Current response:

```json
{
  "provider": null,
  "model": null
}
```

## Ops

Base path:

```text
/api/v1/ops
```

Ops APIs are platform-scoped.

### GET /metrics

Auth:

```text
Authorization: Bearer <accessToken>
```

Required platform permission:

```text
system:ops
```

Current response:

```json
{
  "counters": {},
  "gauges": {},
  "derived": {
    "external": {
      "acpConfigured": false
    }
  }
}
```

### POST /storage/gc

Run the object-storage garbage-collection passes. Intended to be called periodically (e.g. from
a cron job).

Auth:

```text
Authorization: Bearer <accessToken>
```

Required platform permission:

```text
system:ops
```

Each pass is idempotent and best-effort by object key, so repeated runs are safe and a partial
failure is retried on the next call. Reclaims, in order: expired document upload-session objects,
soft-deleted document objects, soft-deleted knowledge-base objects, expired library upload-session
objects, soft-deleted library file objects, and expired temporary Library files.

Current response (counts reclaimed by each pass):

```json
{
  "expiredSessions": 0,
  "purgedDocuments": 0,
  "purgedKnowledgeBases": 0,
  "expiredLibrarySessions": 0,
  "purgedLibraryFiles": 0,
  "purgedTemporaryFiles": 0
}
```

### GET /storage/library-usage-reconciliation

Compare Library quota ledger values with active file rows and unexpired initiated upload sessions.
This endpoint is read-only and requires platform permission `system:ops`.

```json
{
  "items": [
    {
      "spaceType": "team",
      "ownerKey": "tenant_example",
      "ledgerUsedBytes": 1024,
      "ledgerReservedBytes": 0,
      "actualUsedBytes": 1024,
      "actualReservedBytes": 0,
      "matches": true
    }
  ],
  "mismatchCount": 0
}
```
