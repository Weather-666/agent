# Experts Backend

FastAPI control plane for the Experts product. The service owns product metadata,
authorization and orchestration; Agent Gateway, Docling, LightRAG and object storage provide
runtime capabilities behind explicit clients.

## What the service owns

- Authentication, user and tenant lifecycle, platform/tenant RBAC and audit events.
- Expert categories, Experts, plan/subscription data and product credits.
- Platform knowledge bases, immutable document versions, isolated index bindings and durable
  automatic document-sync jobs.
- Personal library files and platform Skill packages in shared object storage.
- Tenant-owned chat Sessions and Turns as the durable authorization and history boundary.
- Expert publication: Builder input, fixed Runtime Homes, Gateway resources and live ACP
  validation. Public knowledge remains Backend-side and is never copied into Runtime Homes.

External systems are not the source of truth for these records:

- Agent Gateway executes ACP Turns and exposes route-scoped session history.
- Docling converts each completed upload to Markdown asynchronously.
- LightRAG indexes the Markdown and supplies retrieval context for Expert-bound chat.
- MinIO is the normal Docker object store; a local filesystem backend is available for
  development.

See [the architecture overview](docs/ARCHITECTURE.md) and [the API guide](docs/api/README.md)
for the current contracts.

## Local development

Requirements: Python 3.11 or newer. From this directory:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e ".[dev]"
cp .env.example .env
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 15000
```

The liveness endpoint is `http://127.0.0.1:15000/health`; Swagger UI is
`http://127.0.0.1:15000/docs`.

`Settings` reads variables prefixed with `EXPERT_` and loads `.env` and `.env.local` from the
working directory. The repository-level Docker Compose file supplies the service-to-service
addresses used by the full local stack; `.env.example` documents standalone defaults.

## LightRAG Controller

The independent `lightrag-builder` repository owns Controller source, service tests, image build
and deployment alongside Docling and LightRAG. Build and run the Controller from that repository;
its README contains the deployment commands and configuration.

Backend uses `app/clients/lightrag_provider.py` to call the authenticated lifecycle API. Configure
`EXPERT_LIGHTRAG_CONTROLLER_URL`, `EXPERT_LIGHTRAG_CONTROLLER_TOKEN`, and the client timeout here.
Controller process configuration and Docker lifecycle access belong to `lightrag-builder`.
Backend builds and tests without Controller source or Docker SDK dependencies.

## Required configuration groups

### Database

`EXPERT_DATABASE_URL` selects the backend from its URL scheme:

```text
sqlite:///./.data/experts-backend.sqlite3
postgresql://user:password@host:5432/database
```

When `EXPERT_DATABASE_AUTO_MIGRATE=true`, startup applies every `infra/sql/*.sql` file in
filename order. There is no applied-migration ledger: these files describe the canonical schema
and must remain idempotent because they run again on every startup. Both SQLite and PostgreSQL
enforce foreign keys at runtime.

### Object storage

`EXPERT_OBJECT_STORAGE_BACKEND` is `local` or `minio`. Documents, library files and Skill
packages share this backend.

For MinIO, configure at least:

```text
EXPERT_MINIO_ENDPOINT=minio:9000
EXPERT_MINIO_PUBLIC_ENDPOINT=objects.example.com
EXPERT_MINIO_PUBLIC_SECURE=true
EXPERT_MINIO_ACCESS_KEY=...
EXPERT_MINIO_SECRET_KEY=...
EXPERT_MINIO_BUCKET=expert-files
EXPERT_MINIO_SECURE=false
```

The internal endpoint and `EXPERT_MINIO_SECURE` are used only by Backend. The explicit public
`host[:port]` and `EXPERT_MINIO_PUBLIC_SECURE` are used to sign URLs that a deployed browser can
reach. There is no fallback from the public endpoint to the internal endpoint. Missing public
configuration, URL syntax with a scheme/path, loopback/private IPs and internal service names fail
closed with `OBJECT_STORE_UNAVAILABLE` instead of returning an unusable address to the browser.
Local development should use the `local` backend; its signed Backend routes under
`/api/v1/storage` are always same-origin relative URLs.

For Agent attachment delivery, configure an absolute Backend origin reachable from the Agent/Gateway
network (this is a Backend URL, not a MinIO URL):

```text
EXPERT_LIBRARY_DELIVERY_PUBLIC_BASE_URL=http://backend:8000
```

Browser Library downloads remain authenticated relative Backend URLs. See
`docs/PERSONAL_TEAM_LIBRARY_EXTERNAL_REQUIREMENTS.md` before changing Compose, Gateway or Frontend.

### Automatic knowledge indexing and retrieval

```text
EXPERT_DOCLING_BASE_URL=http://docling:5001
EXPERT_LIGHTRAG_CONTROLLER_URL=http://lightrag-controller:9630
EXPERT_LIGHTRAG_CONTROLLER_TOKEN=...
LIGHTRAG_CONTROLLER_NAMESPACE=deployment-name
LIGHTRAG_CONTROLLER_ADVERTISE_CONTAINER_IP=false
EXPERT_LIGHTRAG_API_KEY=...
EXPERT_LIGHTRAG_INSERT_TIMEOUT_SECONDS=60
EXPERT_LIGHTRAG_DELETE_TIMEOUT_SECONDS=180
EXPERT_LIGHTRAG_QUERY_TOP_K=10
EXPERT_LIGHTRAG_QUERY_CHUNK_TOP_K=8
EXPERT_LIGHTRAG_QUERY_ENABLE_RERANK=false
EXPERT_KNOWLEDGE_MCP_BASE_URL=http://127.0.0.1:8000/internal/mcp/knowledge
EXPERT_LIGHTRAG_CHUNK_TOKEN_SIZE=800
EXPERT_LIGHTRAG_CHUNK_OVERLAP_TOKEN_SIZE=100
EXPERT_DOCLING_DO_OCR=true
EXPERT_DOCLING_FORCE_OCR=false
EXPERT_KNOWLEDGE_INDEX_WORKER_POLL_SECONDS=3
EXPERT_KNOWLEDGE_INDEX_MAX_ATTEMPTS=5
EXPERT_KNOWLEDGE_INDEX_RETRY_BASE_SECONDS=5
EXPERT_KNOWLEDGE_INDEX_RETRY_MAX_SECONDS=300
EXPERT_KNOWLEDGE_INDEX_PIPELINE_VERSION=docling-page-ocr-locator-v3
```

Set `LIGHTRAG_CONTROLLER_NAMESPACE` on each Controller process when multiple stacks share one
Docker daemon. Reconcile and delete operations only manage resources with the exact namespace;
leaving it empty preserves the legacy unnamespaced resource set.

Containerized Backends should keep Docker DNS addresses. A host-native Backend on Linux may set
`LIGHTRAG_CONTROLLER_ADVERTISE_CONTAINER_IP=true` only when the Controller-managed bridge subnet
is directly reachable; every ensure/health response then refreshes the owned container address.

Creating a knowledge base transactionally creates a durable ensure event. The independent,
authenticated Controller provisions one startup-fixed LightRAG 1.5.6 workspace and endpoint per
KB; only the Controller has Docker lifecycle permission. Upload completion computes a server-side
SHA-256 and transactionally queues that immutable generation. The worker verifies source bytes,
runs Docling/OCR, stores hashed Markdown, inserts incrementally and polls to terminal state. Startup
reconciliation reconstructs lost wake-ups and missing instances. There is no global/shared
fallback. The detailed contract is in
[KNOWLEDGE_BASE_INDEXING.md](docs/KNOWLEDGE_BASE_INDEXING.md).

### Chat and Expert Runtime

Chat uses Agent Gateway's ACP data plane. Unbound Sessions use the configured default route;
Expert-bound Sessions derive their fixed route from `expertId` and `runtimeType`. Backend keeps
the local Session/Turn rows as the ownership and durable-history boundary.

Expert publication additionally requires the Builder executable, Gateway admin API, shared
Runtime/workspace roots and the existing Backend ACP VirtualKey. Publication writes `published`
only after Builder/Gateway validation and a real ACP Turn. It sends an empty `knowledge` input; KB
document changes do not require republishing.

Knowledge-bound Expert Runtimes receive one read-only `search_expert_knowledge` MCP tool. The model
decides whether to use it, so greetings and general questions do not query LightRAG. A tool call
fails closed on an unready binding, network failure, or incomplete source mapping. Valid `sources`
persist KB/document ids, `sourceSha`, `indexDocumentId`, filename, hit text, locator and stable
preview/download routes. Backend uses exact `/query/data` chunks and keeps retrieval scope fixed by
the Expert relation.

See [Expert Runtime publication](docs/api/expert-runtime.md) for the exact contract and
deployment requirements.

## Authorization boundaries

- Platform resources use platform roles and exact permissions. Knowledge bases, documents and
  Skills have no `tenant_id`.
- Tenant product APIs require `x-tenant-id` and verify current membership on every authenticated
  request.
- Knowledge-base `ownerUserId` is creator attribution, not resource ownership.
- Tenant users consume knowledge bases only through an entitled, published Expert in chat.

Access tokens contain identity and roles. Backend reloads the user and current role mappings
before authorization, so disablement and role or membership changes apply without waiting for an
existing access token to expire.

## Startup behavior

The FastAPI lifespan performs the following work before serving requests:

1. Applies the database schema when auto-migration is enabled.
2. Reconciles every Expert recorded as `published`; startup fails if drift cannot be made
   fail-closed.
3. Recreates interrupted/missing index work, reconciles Controller instances, and starts the
   automatic knowledge-index worker.

`GET /health` is a process-liveness response only. It does not prove that PostgreSQL, MinIO,
Docling, LightRAG, Gateway or an ACP Runtime can complete a workflow.

## Development checks

```bash
python -m pytest tests/test_app.py -q
python -m pytest tests/test_audit.py tests/test_credits.py tests/test_mcp_gateway.py \
  tests/test_expert_runtime.py -q
ruff check app/ tests/
```

The tests use temporary SQLite databases and dependency overrides for external systems. A real
ACP integration smoke is available separately:

```bash
python scripts/acp_smoke.py --help
```

It requires a running Gateway route and valid credentials; unit tests with fakes are not live
Gateway proof.

`kb_auto_sync_e2e.py` creates three disposable KBs, uploads two same-name documents through the
public API, waits for real Docling + LightRAG indexing, checks unique endpoints/workspaces,
isolated queries, replaces one source in place, verifies old citation provenance and immediate
delete filtering, then cleans every source, instance and object in
`finally`. Run it where the Backend URL, returned upload URL and dynamic
LightRAG container names are all reachable (normally a disposable Backend container on the
Compose network):

```bash
export KB_AUTO_E2E_ADMIN_EMAIL='admin@example.com'
export KB_AUTO_E2E_ADMIN_PASSWORD='...'
python scripts/kb_auto_sync_e2e.py
```

This proves the source/index lifecycle, not Expert publication or ACP citation delivery. Full
product acceptance additionally uses a disposable published Expert and tenant entitlement, checks
citation preview/download, adds a document without republishing, and restores the Plan in
`finally`. `kb_knowledge_e2e.py` extends this with Expert publication and chat citation delivery.

To refresh the generated API reference after an API contract change:

```bash
python scripts/export_api_docs.py
```
