# Experts Backend Architecture

## 1. System boundary

Experts Backend is the product control plane. It owns identity, authorization, product records
and orchestration in its database. It delegates storage, parsing, retrieval and agent execution
to external systems without treating those systems as the authorization source of truth.

```text
Browser / API client
        |
        v
FastAPI Backend
  +-- auth, tenant and platform RBAC
  +-- experts, plans, credits and audit
  +-- knowledge bases, documents and builds
  +-- library and Skills
  +-- chat Session/Turn ownership and history
        |
        +--> PostgreSQL or SQLite       product source of truth
        +--> MinIO or local storage     file bytes
        +--> Docling                    source file -> Markdown
        +--> LightRAG                   indexing and retrieval context
        +--> Agent Gateway ACP          agent Turns and route history
        +--> Experts Builder            Runtime configuration generation
```

`GET /health` reports only that the FastAPI process is alive. It is not an aggregate readiness
probe for these dependencies.

## 2. Application structure

The normal request path is:

```text
app/domain/*
  Pydantic request/response models with camelCase public fields
        |
app/api/v1/routers/*
  HTTP routing, dependency injection and permission guards
        |
app/services/*_service.py
  authorization, orchestration, audit and transaction boundaries
        |
app/services/*_repository.py
  raw SQL through app/services/_sql.py
        |
SQLite or PostgreSQL
```

External calls live under `app/clients/*`. Services explicitly receive the relevant client or
construct it from `Settings`; routers do not own upstream protocol logic.

SQL uses `?` parameters. The shared SQL layer converts them to `%s` for PostgreSQL and adapts JSON
values. Schema files under `infra/sql/` are canonical, idempotent table definitions rather than a
historical migration stream: the runner reapplies every file on startup when auto-migration is
enabled.

## 3. Resource and isolation boundaries

| Resource | Scope and authorization | Durable owner |
| --- | --- | --- |
| Users, refresh tokens, roles | User plus current tenant/platform roles | Backend database |
| Knowledge bases, documents, Skills | Platform permissions; no tenant relationship | Backend database |
| Experts and publication state | Platform permissions | Backend database |
| Plans and configuration | Platform permissions | Backend database |
| Subscriptions, credits, library files | Active tenant and user checks | Backend database |
| Chat Sessions and Turns | Active tenant plus user ownership | Backend database |
| ACP process/session state | Route VirtualKey and workspace | Agent Gateway/runtime |
| File bytes | Signed object key or server-side access | MinIO/local store |
| Retrieval index | Selected LightRAG instance | LightRAG |

Access tokens are not trusted as a permanent permission snapshot. Auth dependencies reload the
user and current role/membership rows for each authenticated request before deriving exact-string
permissions.

Knowledge bases are platform-authored. `owner_user_id` records the creator but does not restrict
another platform principal with the required permission. Tenant users reach knowledge only through
an Expert-bound chat workflow; they do not call KB/document/build APIs.

## 4. Knowledge-base storage and automatic synchronization

Documents are nested under `/api/v1/knowledge-bases/{knowledge_base_id}/docs`. Upload is a
two-step handshake:

1. Backend creates an upload-session row and a signed PUT URL.
2. The client uploads directly to the configured object store.
3. `complete-upload` verifies exact size, reads the bytes server-side, computes SHA-256 and copies
   them from the expiring PUT key to an immutable version key.
4. Backend creates the Document and a deduplicated source-SHA sync job in the same transaction.

Batch URL creation and batch completion are deliberately non-atomic. Each item commits or reports
its own error so callers can retry only failed files.

Indexing is incremental and asynchronous:

```text
KB create -> binding.ensure outbox -> isolated Controller endpoint
Document complete/replace -> immutable source + document upsert job
FastAPI knowledge worker -> verify SHA -> Docling/OCR -> hashed Markdown
                         -> LightRAG insert -> terminal poll -> ready mapping
```

Create and replacement sessions are permission-separated. A replacement preserves the logical
Document id, stores both source generations, and makes retrieval fail closed until the new
`indexedSha` equals `sourceSha`. The old external document is deleted exactly.

The canonical workflow and current limitations are documented in
[Knowledge Base Indexing](KNOWLEDGE_BASE_INDEXING.md).

## 5. LightRAG Controller and retrieval

LightRAG 1.5.6 fixes `WORKSPACE` at process startup. The authenticated Controller therefore owns
one unique endpoint, workspace, provider reference and Docker volume per KB. Only the Controller
has the Docker socket; Backend has an idempotent ensure/health/delete/reconcile client. New KBs do
does not lease fixed slots, and capacity failure is explicit and retryable. There is no shared
endpoint or cross-KB fallback.

An Expert-bound Runtime exposes one read-only knowledge MCP tool. The model decides when to call
it; the tool resolves current KB relations and queries each ready endpoint separately.
Mapped sources must resolve to a live Document in that KB with `indexedSha == sourceSha`; every
LightRAG reference is treated as untrusted. Missing/stale/deleted/ambiguous references, binding
failure or query failure returns a tool error. Valid citations persist KB/document/source SHA/index
document id, filename, bounded hit text, locator and preview/download routes.

The public Turn request deliberately does not expose knowledge-base IDs or retrieval tuning.
Retrieval scope comes from the Expert relation, and mode/top-k come from server settings.

## 6. Chat and ACP execution

Chat Sessions and Turns are always authorized against local rows by `tenant_id` and `user_id`.
The local Session id is generated before any upstream call; Agent Gateway materializes its own ACP
session lazily on the first Turn, and Backend persists that returned ACP session id for resume.

Turn execution is a single streaming request. Backend:

1. Reserves a local running Turn using a database uniqueness guard.
2. Authorizes and snapshots requested library attachments.
3. Sends a route-scoped ACP Turn with the resolved workspace and current Turn id metadata.
4. Lets the model call the read-only knowledge tool when reference evidence is needed.
5. Translates ACP events and any persisted sources to the public SSE contract and assembles the
   durable local Turn.

Expert-bound Sessions derive `/acp/expert-{runtimeType}-{expertId}` and use Backend-prepared
tenant/user workspaces. Unbound legacy Sessions use the configured default route and workspace.
Gateway permission requests are held in memory by the serving Gateway replica, so the data plane
must remain single-replica or session-affine for permission resolution.

## 7. Expert publication

Backend owns the published/unlisted transition. For every enabled Runtime it:

1. Resolves Expert Skills and enabled MCP Connectors; KBs remain relationship ids only.
2. Generates Build Input Schema v2 with `knowledge: []`, plus the internal knowledge MCP client for
   a knowledge-bound Expert, and invokes the local Builder.
3. Validates and installs Builder-managed files into the fixed Runtime Home.
4. Creates or updates Gateway Service/Route and VirtualKey allowlists.
5. Reads Gateway resources back and performs a real ACP Turn.
6. Persists `published` only after every Runtime succeeds.

Unlisting disables fixed Expert resources. Startup reconciliation revalidates every published
Runtime against contract v6, including absence of copied Runtime Knowledge. KB changes do not
alter Runtime files or require republishing.

See [Expert Runtime publication](api/expert-runtime.md) for the complete contract.

## 8. File lifecycle and garbage collection

Documents, library files and Skill packages share the configured object-store abstraction.
Knowledge-base/document deletes are soft deletes so the object key remains available for cleanup.
`POST /api/v1/ops/storage/gc` removes expired upload objects and soft-deleted objects before
hard-deleting their rows.

Source replacement or deletion stops new retrieval in the committing transaction before
asynchronous index cleanup. Citation preview reads the persisted hit snapshot. Citation download
resolves exact `(documentId, sourceSha)` source-version provenance; it remains available until
Document deletion and object GC reclaim all generations.

Chat attachments reuse the library tables. Temporary files are owner-scoped before first use,
bind once to a Session, retain a provenance snapshot on the Turn and are reclaimed by TTL unless
promoted to permanent. See [Library File Lifecycle](LIBRARY_FILE_LIFECYCLE.md).

## 9. Startup and process model

FastAPI lifespan runs database schema application, published-Expert reconciliation, repairs
interrupted binding/document jobs, reconstructs missing source-derived work, reconciles Controller
instances and starts the asynchronous knowledge-index worker. Claims use durable status updates;
external operations are idempotent and restart recovery returns interrupted jobs to pending.

## 10. Verification boundary

The pytest suite exercises API, database, authorization and orchestration behavior with temporary
SQLite databases and fakes for external services. That evidence is distinct from live proof:

- `/health` proves Backend liveness only.
- MinIO health does not prove signed browser upload/download.
- Docling health does not prove conversion of a real uploaded file.
- LightRAG health does not prove ingestion completion or retrieval.
- Gateway route discovery does not prove a real ACP Turn.

End-to-end acceptance must exercise provision/upload/automatic sync/retrieval and a fresh ACP Turn
against the running stack. `scripts/kb_auto_sync_e2e.py` is disposable source/index acceptance;
full product acceptance additionally publishes one temporary Expert once, verifies citation
preview/download across later document changes, and cleans all temporary resources in `finally`.
