# AGENTS.md

Self-readme for AI agents working in `experts-backend`.

## What this is

FastAPI control-plane backend. It owns auth/RBAC, knowledge bases, documents, chat and skills.
ngent / Codex are upstream/optional integrations, not the source of truth.

## Conventions

- All code text (comments, messages, identifiers, commit messages) is in **English**.
- Layering (see `skills` / `knowledge_bases` for the canonical pattern):
  `app/domain/*` (pydantic models, camelCase fields) → `app/services/*_repository.py`
  (raw SQL, `?` placeholders) → `app/services/*_service.py` (orchestration + `commit`) →
  `app/api/v1/routers/*` (`Depends(get_database)` + `Depends(require_platform_permission(...))`).
- Shared SQL helpers: `app/services/_sql.py` (`execute`/`fetch_one`/`fetch_all`/`json_param`/`json_load`).
  `prepare_sql` rewrites `?`→`%s` for Postgres; pass JSON via `json_param`.

## Database & migrations (read before touching `infra/sql/`)

- Backends: SQLite (default/tests) and PostgreSQL. `app/db.py` migrates both.
- **Foreign keys are enforced at runtime on both backends**: `_open_sqlite` sets
  `pragma foreign_keys = on` per connection (off by default in SQLite), matching PostgreSQL.
  So `ON DELETE CASCADE` and FK constraints fire at runtime — rely on cascade instead of
  manually deleting child rows. Note soft-deleted parents (e.g. knowledge bases) never trigger
  cascade; filter `deleted_at is null` on reads instead.
- **The runner re-runs every `infra/sql/*.sql` on each boot and has NO applied-migrations
  table.** Idempotency is mandatory: use `create table if not exists` / `add column if not
  exists` / `drop ... if exists`. **Never** write an unconditional `drop table + create table`
  — it wipes data on every restart.
- SQLite quirks the runner imposes: one `add column if not exists` per `ALTER`; no
  `DROP TABLE ... CASCADE`; statements split on `;`, so **no `;` inside SQL comments**;
  `alter column` / `add constraint` are skipped on SQLite.
- Each file is the canonical (final) shape of its tables, with every column/index/constraint
  folded into the `create table if not exists`. Files are numbered only to order FK dependencies
  (`sorted(glob)`), not as a migration history — there are no incremental patch files. When you
  evolve a table, edit its `create table` in place (dev rebuilds the DB); add an idempotent
  `alter ... if [not] exists` only when an existing deployment must be preserved.

## Auth model

- Platform roles (`admin`/`expert`/`operator`) vs tenant roles (`admin`/`member`).
- Knowledge bases, documents and skills are **platform-authored and have no tenant relationship**
  (no `tenant_id`). Tenants hold no `kb:*`/`doc:*`/`skill:*` and consume only via chat.
- Permission checks are exact-string membership (`app/api/deps.py`), no wildcard/prefix hierarchy.
- Knowledge bases are platform-owned with no tenant scope/visibility. Their public state is
  `status` (`active`/`archived`) plus automatic parsing and `indexStatus`/`indexError`; immutable
  source and indexed generations are pinned by each Document's SHA fields. A pending batch up to
  5 MiB is indexed automatically; a larger batch is parsed and paused until the existing rebuild
  action releases that exact batch. Paused Documents use `indexStatus=stale`; durable Jobs remain
  `pending` with a held schedule so existing database constraints do not need a new state. Archived
  KBs cannot create or claim upserts; activation reconciles them through the same cost gate. Access is
  decided purely by the route permission; `owner_user_id` is creator attribution, not access
  control. The only
  resource-level rule (an archived KB rejects writes) lives in `app/services/kb_authz.py`.
  Lifecycle transitions are explicit endpoints, not `PATCH` (which cannot touch `status`):
  `POST /{id}/archive` (active→archived) and `POST /{id}/activate` (archived→active). `activate`
  is the one write allowed on an archived base — `kb_authz` keeps it out of `_WRITE_ACTIONS` so it
  bypasses the gate; `archive` is gated, so re-archiving returns `409 KB_ARCHIVED`.
- **KB and document delete are soft deletes** (`deleted_at`), so the `documents`/`upload_sessions`
  ON DELETE CASCADE never strands MinIO objects (a hard cascade drops the rows that hold the
  `storage_key` needed to reclaim them). `DocumentService` GC reclaims objects then hard-deletes:
  `purge_deleted_objects` (docs) and `purge_deleted_knowledge_bases` (KBs). All reads must filter
  `deleted_at is null`. Upload completion transactionally queues its immutable SHA generation;
  delete is filtered immediately and queues exact external cleanup. The index worker/Controller
  own instance release, after which object GC may hard-delete the KB regardless of published
  Expert relations (those relations no longer copy/pin knowledge). GC has no scheduler/entry point
  yet — call it directly. complete-upload guards concurrent completion via the
  `documents` PK and maps the collision to 409, not 500.
- **Batch upload endpoints (`/docs/upload-urls`, `/docs/complete-uploads`) are non-atomic**: each
  file is its own transaction (`DocumentService` loops the single-item method). They never abort
  mid-batch — each `items[]` entry reports `status` (`created`/`completed` vs `failed`) and a
  per-item `error`, so callers retry only failures. Both return `200` (not `201`).

## Chat (ngent integration)

- **ngent is a compute engine, not the source of truth.** Its store is single-node SQLite,
  unbacked, and enforces **no tenant/user isolation** (any bearer token can read/delete any
  thread/turn by id). So the **local DB is the system of record**: `chat_sessions` / `chat_turns`
  mirror ngent's thread/turn shape plus ownership (`tenant_id`, `user_id`) and product fields
  (pin) ngent lacks. Session/turn ids equal ngent's thread/turn ids.
- Every chat endpoint authorizes by **local ownership** (caller's tenant+user) before calling
  ngent — never trust ngent to scope. Flat `/turns/{id}/*` ops check `chat_turns` ownership.
- **Per-tenant working dir**: when `EXPERT_NGENT_CWD_BASE` is set, `NgentClient.prepare_cwd`
  gives each session `cwd = <base>/<tenant_id>` (created on demand, since ngent requires cwd to
  exist); empty base shares `ngent_default_cwd`. This is soft filesystem separation, not a
  sandbox — the real boundary is ngent's `allowedRoots`. Backend and ngent must share the host so
  the mkdir is visible to ngent.
- Turn creation reserves the local Turn and starts application-owned execution before SSE.
  Browser disconnect only detaches the subscription. Durable chat_turn_events provide ordered replay
  and live progress. Explicit cancel terminates upstream execution; restart preserves partial text
  and marks the Turn interrupted. Run one Backend worker.
- **Auto session title**: persisted via `repo.update_session_title` and re-emitted to the caller
  as a unified `session_title_updated` SSE frame. Fill-only-when-empty: written solely while the
  local title is blank, so a user's manual rename (`PATCH /sessions/{id}/title`) is never
  clobbered. Source differs per backend:
  - ngent: rides the turn stream as a `session_info_update` event (title at `data.title`). Note
    `GET /v1/threads/{id}` returns the manual `thread.title`, a *separate* field from this evolving
    session title.
  - ACP: **codex-acp does NOT emit `session_info_update`**, so the live `session_info` SSE event
    never fires for it — codex's title is only on the route-scoped `session/list`
    (`GET {prefix}/sessions` → `sessions[].title`, auto-derived from the first user message).
    `stream_turn` reconciles it after the turn via `_fetch_acp_title` (`AcpGatewayClient.list_sessions`),
    matching `sessions[].session_id` to `chat_sessions.acp_session_id`. The inline `session_info`
    branch is kept for agents that *do* emit it (e.g. opencode).
- The turn request body is **`question` plus `attachmentFileIds`** (and `webSearchEnabled`).
  ngent's turn API takes just the prompt (`{input, stream}`), so model / knowledge-base / retrieval
  options are not accepted and the `chat_turns` option columns are stored as defaults — do not
  re-add request fields without wiring them into the outgoing payload. `attachmentFileIds` *is*
  wired (see Chat attachments below). The streaming handler opens its own DB connection
  (`open_database_connection`) inside the generator, since the request-scoped `get_database`
  connection is closed before the `StreamingResponse` body runs; a route-level pre-flight
  (`validate_turn_preconditions`) authorizes the session + attachments before the stream starts,
  so denials are clean HTTP errors rather than an empty 200 stream.

### Chat attachments & library file lifecycle

- Temporary chat files reuse `library_files`. The database invariant is `temporary => expires_at`
  and `permanent => no expires_at`; SQLite legacy tables are rebuilt before migrations run.
- Upload uses `/library/files/upload-url` and `/complete-upload`. Temporary files start unbound and
  bind once, by conditional update, when first used in a turn.
- Object keys are backend-generated ASCII hints, never authorization. Display names remain separate.
- Turn preflight checks attachments without binding; the streaming connection rechecks and binds.
  Do not remove either trust boundary or silently drop denied attachments.
- Personal reads require the current owner. Team reads also reload membership, role and subscription.
  Agent delivery uses a short-lived Backend capability and rechecks those facts on every consume.
- ZIP/RAR are storage/download only. Reject them during turn resolution and legacy capability
  consumption with `LIBRARY_AGENT_FORMAT_UNSUPPORTED`.
- Turns persist metadata provenance, never object keys, signed URLs or delivery tokens. Read audits
  follow the same metadata-only rule.
- `docs/USER_LIBRARY_DESIGN.md` owns policy, quota, naming and format rules;
  `docs/LIBRARY_FILE_LIFECYCLE.md` owns temporary binding, delivery and GC details.
- GC expires temporary files and deleted objects. Deleting a chat session does not delete attachments.
- **Expert marketplace (`/expert-market/*`) requires sign-in** (`require_principal`, any
  authenticated caller) but no specific permission; it lists only `published` experts/categories.

### Pluggable compute backend (`EXPERT_CHAT_BACKEND` = `ngent` | `acp`)

- `ChatService` is backend-agnostic; the local DB stays the source of truth either way. The
  router (`build_chat_service`) injects both clients and the configured backend. ngent is the
  default and unchanged; `acp` targets the agent-gateway ACP data plane (`AcpGatewayClient`).
- **ACP exposes four route-scoped data-plane endpoints**: `POST {prefix}/turn` (SSE),
  `POST {prefix}/permission`, `GET {prefix}/sessions`, and `GET {prefix}/sessions/{id}/transcript`
  — all authenticated by the route's VirtualKey (`acp_auth_token`), no admin plane. There is
  **no thread/turn lifecycle, no cancel, no event-replay**.
  Consequences, all hidden behind the same public chat API:
  - `create_session` mints the `thread_id` locally (no upstream call); the agent materializes the
    session lazily on the first turn.
  - The agent-assigned ACP session id arrives via a `session` event on the first turn and is
    stored in `chat_sessions.acp_session_id`, then echoed back as `TurnRequest.session_id` on
    follow-up turns so the gateway resumes the same pooled instance (scope keys on
    `service|cwd|thread_id|session_id|model`, so cwd/model must stay stable per thread).
  - A turn has no server id, so `ChatService` generates one locally and emits `turn_started`
    before any text. ACP events are **translated to the same public contract** ngent exposes
    (`reasoning`/`tool_call`→`reasoning_delta`, `delta`→`message_delta`, `done`→`turn_completed`,
    `permission`→`permission_required`, `error`→`error`), so the frontend is unchanged.
    `rename`/`delete` are local-only; `cancel` closes upstream execution;
    turn-event replay reads durable ordered events.
- Chat does not accept or forward client-selected knowledge-base scope to ACP. A knowledge-bound
  Expert Runtime receives one read-only `search_expert_knowledge` MCP tool. The model decides
  whether the question needs that tool; greetings and general reasoning do not query LightRAG.
  When called, Backend requires every live bound KB and binding to be ready, queries each isolated
  endpoint, maps every reference to a live Document whose `indexed_sha256 == source_sha256`, and
  persists owner-authorized `retrievalRefs`. Workspace/network or provenance failures are returned
  as tool errors; there is no cross-KB or stale-content fallback.
- **ACP cwd isolation is persisted in `agent_options.workspaceScope` plus `expert_id`**:
  every new bound Expert Session and shared-default-tenant Session uses
  `<EXPERT_ACP_CWD_BASE>/<tenant_id>/users/<user_id>` and persists `workspaceScope=user`.
  Before a legacy bound Session executes again, Backend clears both ACP session ids and moves
  its cwd to this user scope; it preserves local chat history and old files without copying
  shared files into the user workspace. Legacy shared-workspace transcript reads use local
  owner-scoped history. Other unbound Sessions retain the legacy/default Route and
  `EXPERT_ACP_DEFAULT_CWD`. Bound Sessions derive the Route from `expertId + runtimeType`.
  Backend creates the
  configured tenant root and child, rejects unsafe path segments or symlinks, and prepares
  empty `.git`, `.agents`, and `.codex` Bubblewrap mount targets. These directories are sandbox
  infrastructure, not Git metadata or application data. Bound requests explicitly send only
  the user `cwd`; model, environment, `HOME`, `CODEX_HOME`, permission mode, and other
  defaults come from the Expert Gateway Service.
- **Permission resolution is in-memory on the gateway**: the answer (`POST {prefix}/permission`,
  request id in the body) must reach the same gateway replica holding the pending request — keep
  the ACP gateway single-replica or session-affine.
- **History replay** uses local owner-scoped Turns for bound Experts, so internal capability
  prompts cannot escape through raw agent transcripts. Default sessions also replay local history because they receive Library Turn capabilities.

- **Live smoke test**: `python scripts/acp_smoke.py` drives the real `AcpGatewayClient`
  against a running gateway (config from env/.env or `--base-url` etc.). It runs a
  turn and prints the translated events, with `--resume` (session resume), `--transcript` /
  `--list-sessions` (route history APIs), and `--auto-permission` (answer prompts). Use it to validate the
  integration against a real gateway before relying on the backend — the pytest suite only covers
  fakes.

### Expert publication ownership

- Backend owns publish/unpublish. It calls Builder `build`, installs only Builder-managed
  files into the fixed `<EXPERT_ACP_CONFIG_BASE>/expert-<runtimeType>-<expertId>` Home, manages
  Gateway Service/Route and the existing Backend VirtualKey allowlist, performs a real ACP Turn,
  and writes `published` only after every enabled Runtime succeeds. Publication sends no public KB
  files to Builder; KB changes never require a republish.
- Backend startup reconciles all rows marked `published` before serving requests. It validates the
  managed layout, Service, Route, Runtime contract version, and a live smoke; drift is first made
  `unlisted` and only a complete successful republish restores `published`. A failed repair must
  confirm both the non-published database state and disabled Gateway resources before health. Bump
  `_RUNTIME_CONTRACT_VERSION` and update the installed-layout check together whenever a
  Backend/Builder/bundled-adapter change requires existing Runtime Homes or Gateway resources to
  be rebuilt.
- Codex uses `approval_policy=never` to reject sandbox escalation before ACP approval. Gateway
  retains `permissionMode` (default `auto_approve`) for legitimate bound MCP calls. Writable cwd
  AGENTS files are not auto-loaded (`project_doc_max_bytes=0`).
  Install `runtime/expert-runtime-network.service` before publication; the wrapper requires its
  dedicated-group management-port rules and clears inherited Gateway environment variables.
  See `docs/RUNTIME_SANDBOX.md`. The helper is a host prerequisite, not Builder output.
- Builder is an independent repository and a pure local configuration generator. Backend requires
  its executable through `EXPERT_BUILDER_EXECUTABLE`; do not vendor a Builder copy here. Do not reintroduce Runtime Bindings,
  `expertKey`, generic Bundle/archive or deployment records, Publisher, or Builder-managed Gateway
  resources or a Runtime knowledge-version pin.
- Chat persists only `expert_id`, `runtime_type`, and ACP session ids. A previously created
  Session resumes the same `acp_session_id` after unlist/edit/republish because the derived Route
  and fixed Runtime Home do not change.

## Featured examples

- Backend owns the shared question catalog in two independent tables; no Expert binding,
  cached answer, Chat schema change, or startup seed. See `docs/api/featured-examples.md`.
- Management permissions are exact `featured_example:read/write/publish`: admin has all,
  expert has read/write, operator has read. Management changes and their audit commit together.
- Approval makes an example live. Actual question/category/cycle edits reset it to pending.
  UTC expiry derives `reviewing` on reads without mutations; review requires an
  `expectedUpdatedAt` compare-and-set. Complete collection reorders are transactional.
- Market GET and POST use require tenant `chat:ask`. Use atomically checks availability,
  increments clicks, and returns the same update's question without changing `updatedAt`.
  The caller sends that question through existing Chat with the selected Expert; clicks count
  accepted use requests regardless of subsequent model success.

## LightRAG Controller ownership

`lightrag-builder` owns Controller source, service tests, image build and deployment.
Backend owns business records, indexing jobs and the authenticated HTTP client
(`app/clients/lightrag_provider.py`). Keep client contract tests here; do not import
Controller source or require the Controller repository to build or test Backend.

## Tests & lint

- `python -m pytest tests/test_app.py -q` and `ruff check app/ tests/`. Run both before finishing.
- Tests use a TestClient + temp SQLite; inject fakes (e.g. MinIO) via `app.dependency_overrides`.

## Key designs

- `docs/KNOWLEDGE_BASE_INDEXING.md` (current architecture and technical contract)
- `docs/USER_TENANT_RBAC_DESIGN.md`
- `docs/LIBRARY_FILE_LIFECYCLE.md` (chat temporary files & promotion, reflects shipped code).
- API reference under `docs/api/`.

Default ACP sessions support personal Library through a separately authenticated /internal/mcp/library/default endpoint. See docs/DEFAULT_LIBRARY_RUNTIME.md for the default service configuration and acceptance procedure. Preserve the default Codex Home and installed Skills.
