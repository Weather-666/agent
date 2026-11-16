# Knowledge Index Review API

Base path:

```text
/api/v1/knowledge-bases/{knowledge_base_id}
```

Documents synchronize automatically after upload or replacement. When the active pending batch is
larger than the configured cost threshold, parsing completes but indexing pauses until the exact
batch is approved.

## GET /index-review

Required permission: `kb:read`.

The response reports `not_required`, `pending_parse`, `review_required`, or `approved`, plus the
threshold, aggregate size, batch token and documents in the current batch.

## POST /index-review/approve

Required permission: `kb:build`.

```json
{
  "batchToken": "stable-token-from-index-review"
}
```

The token must match the current paused batch. Approval releases only that batch to the ordinary
automatic index worker; it does not create a second index lifecycle or copy knowledge into an
Expert Runtime.

See [Knowledge Base Indexing](../KNOWLEDGE_BASE_INDEXING.md) for the full lifecycle.
