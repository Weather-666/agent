# Public Knowledge Index Lifecycle

This is the Backend contract for public knowledge sources, isolated LightRAG indexes, automatic
parsing, size-gated indexing and citation provenance.

## Source of truth and ownership

- `knowledge_bases` and live `documents` are the only public-knowledge source of truth.
- An Expert stores only rows in `expert_knowledge_bases`; publication never copies KB Markdown into
  its Runtime Home and never pins a Build/release.
- An original object is immutable. `source_sha256` is computed by Backend from uploaded bytes.
- Replacing a logical Document writes a new immutable source-version row; old citation downloads
  continue to resolve by `(document_id, source_sha256)` until deletion and GC.
- A new Document is retrievable only after it has a ready indexed generation. During replacement,
  the previous indexed SHA remains the published generation until the new one succeeds.
- LightRAG output is untrusted external data. It cannot grant access or establish provenance.

`KnowledgeBase.indexStatus` is `provisioning`, `ready`, `failed`, or `deleting`. `indexError` is the
retryable provisioning failure visible to callers. `Document` exposes `sourceSha`, `indexedSha`,
`indexDocumentId`, `parseStatus`, `indexStatus`, and `lastError`; parsing and indexing are separate
document states.

## Binding lifecycle and durable recovery

Creating a KB writes both its source row and a deduplicated `binding.ensure` event in one database
transaction. Deletion soft-deletes the source and writes `binding.delete` the same way.

`knowledge_index_outbox` is a durable wake-up queue. On startup Backend:

1. changes interrupted `processing` work back to `pending`;
2. derives missing ensure/delete events from source rows;
3. compares all live KB ids with Controller-managed instances;
4. recreates missing instances and reclaims Controller orphans through label-checked deletion.

Archived KBs cannot generate or claim upserts or receive index approval. Archive supersedes
in-flight upserts; activation lets ordinary reconciliation re-enter the same size gate.

An event may be delivered more than once. Controller operations and database upserts are
idempotent, so loss after an external ensure but before a database commit is recoverable.

## Privileged Controller boundary

LightRAG Server 1.5.6 selects `WORKSPACE` when the process starts. It has no safe per-query
workspace selector. Each KB therefore owns one unique endpoint, workspace, provider reference and
storage namespace. There is no cross-KB shared endpoint or capacity fallback.

The independent `lightrag-builder` repository owns Controller source, service tests, image build
and deployment. Backend keeps the authenticated HTTP client and its contract tests; it does not
import Controller source or require the Controller repository to build or test.

Backend calls the independently deployed Controller through an authenticated narrow API:

| Operation | Contract |
| --- | --- |
| `PUT /v1/instances/{kbId}` | idempotent ensure and readiness wait |
| `GET /v1/instances/{kbId}` | health and immutable identity |
| `DELETE /v1/instances/{kbId}` | idempotent exact deletion |
| `POST /v1/instances/reconcile` | report managed, missing and orphan KB ids |

The response fixes `provider`, `providerRef`, `baseUrl`, `workspace`, and `status`. Backend has no
Docker dependency or socket mount. The optional local Docker Controller is the only Compose service
with the socket. It derives deterministic names from the KB id, validates ownership/workspace
labels before every mutation, pins the official v1.5.6 image by OCI digest
`sha256:ab23a9c83a73...`, and exposes no arbitrary Docker operation.

Every KB uses the Controller. If the Controller cannot ensure an isolated instance, the KB is
`failed` with a retryable provisioning error; Backend never shares an endpoint or silently queries
another KB.

## Automatic parsing and gated indexing

Upload completion stores the immutable source row and one deduplicated upsert job for that source
SHA in the same transaction. `knowledge_document_sync_jobs` also holds exact delete jobs.
Concurrent completion/reconciliation collapses to one job per immutable generation.

Create and replacement handshakes are distinguished in `document_upload_sessions`. Creation
requires `doc:create`; replacement uses `/{documentId}/upload-url` and
`/{documentId}/complete-upload`, requires `doc:update`, preserves the logical Document id and
cannot be completed through the create endpoint. A replacement SHA preserves the previous ready
index pointer while the new source is parsed, reviewed and indexed. A newly created Document has no
old pointer and remains unqueryable while it is waiting.

The worker performs this sequence for active, non-deleted KBs:

1. read the original and verify its SHA against the recorded source SHA;
2. convert through Docling/OCR and store content-addressed Markdown;
3. aggregate the active KB's pending source generations. At most `5 * 1024 * 1024` bytes proceeds
   automatically; a larger aggregate pauses after parsing until the index approval action is
   invoked for that exact batch token;
4. require the ready isolated binding;
5. call LightRAG 1.5.6 `POST /documents/text` with a stable KB/document/SHA file source and the
   configured fixed-token chunk size/overlap;
6. persist and reuse the returned track id, polling `GET /documents/track_status/{track_id}`
   across worker iterations until it reaches a terminal state;
7. atomically publish the new pointer and queue exact cleanup of the previous generation.

The insert request timeout covers only acquiring the durable track id; it is not the ingestion
deadline. A 409 first resolves the same file source: processing is polled/backed off, completed is
mapped directly, and only failed/stale/hash-mismatched data is deleted. Every delete waits until
the external document is absent before insertion continues. A replacement publishes the new
pointer before queuing deletion of the exact old external id. Source and Markdown generation tables
preserve exact citation downloads and complete GC ownership. A failure keeps the source immutable,
records `lastError`, and retries with bounded backoff. Startup repairs interrupted jobs without
bypassing the 5 MiB cost gate. Paused documents expose `indexStatus=stale` rather than a false
failure; `GET /{id}/index-review` returns the exact pending batch and
`POST /{id}/index-review/approve` releases it when the user approves the exact batch.

## Chat and citation rules

For a bound Expert, the Runtime exposes one read-only `search_expert_knowledge` MCP tool. The model
calls it only when the question needs facts from the Expert's reference documents; greetings,
casual conversation and general reasoning bypass LightRAG. A tool call resolves:

`Expert -> expert_knowledge_bases -> live active KB -> ready isolated binding`.

Backend queries each endpoint separately with LightRAG `POST /query/data` and returns only exact
mapped chunks to the Runtime. A candidate reference is
usable only if it maps unambiguously to the live Document's currently published indexed generation.
Stable external document id or stable KB/document/SHA file source is required. Any context with
missing, stale, deleted, ambiguous, or unmapped references makes the tool fail closed. Valid
sources are persisted on the running Turn and emitted before completion; the tool result asks the
model to cite their `[cite_N]` ids.

Each persisted internal citation snapshot fixes:

- KB id/name and Document id;
- `sourceSha` and `indexDocumentId`;
- filename, MIME type, bounded hit text and locator. PDF page/PPT slide locators are emitted only
  when Docling returned the configured page-boundary marker; a missing marker is never guessed;
- stable owner-authorized preview/download routes.

The caller-facing `retrievalRefs` and SSE `sources.documents` projection is deliberately smaller:
it contains the stable Backend `documentId`, authorized `fileName`, nullable one-based
`pageNumber`, display locator, hit text and citation routes. It never contains the LightRAG
`file_source`, SHA, object key, chunk id or
index document id. Duplicate sources for the same Document/page are collapsed in first-retrieval
order while retaining all `citationIds`.

LightRAG 1.5.6 `/query/data` does not carry page metadata. A page is therefore public only when
every returned chunk in that file-level reference contains the same Backend-authored Docling
boundary marker. The marker is generated one-based. Missing or ambiguous markers produce
`pageNumber: null`; higher page coverage requires the parsing/indexing contract to propagate a
trusted page value to every chunk.

Preview uses the persisted hit snapshot. Download re-authorizes the Turn owner and resolves the
same immutable source SHA. Renames cannot rewrite citation history. Deleted/permission-revoked
knowledge is filtered immediately from new retrieval; delayed external cleanup never controls
authorization.

## Delete and garbage collection

Document delete first writes `deleted_at`, so it disappears from retrieval in the committing
transaction. A durable delete job removes only its exact `index_document_id`, clears its mapping,
then object GC removes both source and generated Markdown.

KB delete immediately removes the KB from chat resolution and queues binding deletion. Controller
first requires a complete authenticated LightRAG workspace clear, then deletes the exact managed
container/volume.
Only after the binding is absent does KB GC remove owned objects and rows. Cleanup failure keeps the
source tombstone and retries; it never releases an identity for reuse prematurely.

## Existing-data upgrade

Schema changes are additive and rerunnable. Existing nullable SHA rows do not fail migration:
`content_hash` is copied when available, otherwise the worker computes SHA from the immutable
object. Existing non-null originals are backfilled into the source-version table; nullable rows
are added when startup verification computes their SHA. A binding without the Controller provider,
provider reference and workspace is not accepted; reconciliation ensures the Controller-owned
instance and persists the current identity.

Runtime contract v6 has no `~/knowledge` read permission. KB changes do not alter Runtime state and
do not trigger publication.

## Verification boundaries

- Source/unit proof: migrations rerun, queue/reconcile races, provider contract, same-name KB
  isolation, retry, deletion, citation mapping, nullable-SHA migration and Runtime contract tests.
- Health: Backend and Controller liveness plus each provisioned instance's authenticated
  `/health`, including its expected workspace when reported.
- Real E2E: disposable KBs/documents/Expert, real MinIO + Docling + LightRAG 1.5.6 parsing,
  automatic-at-boundary and manual-over-threshold indexing, safe replacement and query, no
  republish after a new document, exact citation fields, then `finally` cleanup. Process health or
  `tools/list` is not E2E proof.
