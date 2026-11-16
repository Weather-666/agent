# Chat API

Base path:

```text
/api/v1/chat
```

All APIs in this group are tenant-scoped and require:

```text
Authorization: Bearer <accessToken>
x-tenant-id: <tenant_id>
```

Required tenant permission for all endpoints:

```text
chat:ask
```

Execution is delegated to the agent-gateway ACP data plane, but the **local database is
the system of record**. Sessions and turns are mirrored into `chat_sessions` /
`chat_turns` so reads are tenant/user-scoped and survive agent restarts. Every endpoint
authorizes by local ownership (the caller's tenant + user) before touching ACP. Session
and turn ids are generated locally; `chat_sessions.acp_session_id` stores the
agent-assigned session id after the first turn so later turns resume the same instance.

Turn creation is **single-step streaming**: `POST /sessions/{session_id}/turns` returns
an SSE stream directly. The backend emits `turn_started` with a locally generated
`turnId` before forwarding translated ACP events. There is no separate "create then
subscribe" step. Use `GET /turns/{turn_id}/events` to replay durable events and subscribe to live progress.

There are no `/chat/tasks` endpoints in the current backend. Clients should create or
select a session first, then post the user's message to `/sessions/{session_id}/turns`.

## GET /search

Search the current user's active, non-deleted chat sessions. Matching is limited to
`chat_turns.request_text` and `chat_turns.response_text`; titles, reasoning, errors,
attachments, internal turns, archived sessions and deleted sessions are excluded.

Query parameters:

- `keyword` (required): trimmed length 1–200.
- `scope` (optional, default `all`): `all`, `question`, or `answer`.
- `limit` (optional, default 20): 1–100.
- `offset` (optional, default 0): integer greater than or equal to 0.

Each matching session appears at most once.

## POST /sessions

Create a chat session.

ACP working-directory selection uses the persisted Expert identity and user workspace scope:

- New bound Expert sessions and new shared-default-tenant sessions persist
  `agent_options.workspaceScope=user` and use
  `<EXPERT_ACP_CWD_BASE>/<tenant_id>/users/<user_id>`. Members of the same team have separate
  task files. Two Experts used by the same user share that user's workspace.

- Any other legacy/unbound session (`expert_id IS NULL`, created without `expertId`) keeps the
  default ACP Route. It uses `EXPERT_ACP_DEFAULT_CWD` when non-empty; an empty value omits
  `cwd` and lets the default Service decide. Configuring
  `EXPERT_ACP_CWD_BASE` does not move it.
- A bound Expert session (`expert_id IS NOT NULL`, created with `expertId`) uses its
  derived `/acp/expert-{runtimeType}-{expertId}` Route. Backend creates the configured root and
  user directory at Session creation and prepares it idempotently before execution. It also
  creates empty `.git`, `.agents`, and `.codex` directories in the workspace as required
  Bubblewrap mount targets; these are directories only and are not Git repositories or runtime
  data stores.
- An existing bound session that used the old tenant-wide directory switches to user scope
  before its next execution. Both ACP session IDs are cleared so the next turn materializes
  a fresh agent session. Local chat history and old files are retained; shared files are not
  copied into any user's directory. Until then, transcript reads use owner-scoped local history.

Names and display text do not affect isolation. The configured roots must be visible on the Backend/Gateway
shared filesystem and allowed by the corresponding ACP Service's `allowedRoots`.

The bound Expert request still omits the model override so the Expert Gateway Service
continues to supply its model, runtime environment, `HOME`, `CODEX_HOME`, permission
mode, and other defaults. Only `cwd` is explicitly set by the Backend.

Deployment example:

```text
EXPERT_ACP_DEFAULT_CWD=/usr/local/amazon/workspace
EXPERT_ACP_CWD_BASE=/usr/local/amazon/tenant-workspaces
```

Backend/Gateway contract: every published Expert Service uses and allows the same
`EXPERT_ACP_CWD_BASE` root at the same filesystem path. Backend creates the root and each
`<base>/<tenant_id>/users/<user_id>` directory and sends that exact cwd.

Request:

```json
{
  "title": "Review analysis"
}
```

To create a bound Expert session:

```json
{
  "expertId": "0123456789abcdef",
  "runtimeType": "codex"
}
```

The reserved system-default Expert is a Runtime configuration template, not a
user-selectable Expert. Passing its id returns `409 EXPERT_NOT_SELECTABLE`.

Response `201` (a session object):

```json
{
  "id": "thread_1",
  "title": "Review analysis",
  "status": "active",
  "isPinned": false,
  "expertId": "0123456789abcdef",
  "runtimeType": "codex",
  "createdAt": "2026-06-07T00:00:00+00:00",
  "updatedAt": "2026-06-07T00:00:00+00:00"
}
```

## GET /sessions

List chat sessions.

Response `200`:

```json
{
  "items": [
    {
      "id": "thread_1",
      "title": "Review analysis",
      "status": "active",
      "createdAt": "2026-06-03T00:00:00+00:00",
      "updatedAt": "2026-06-03T00:00:00+00:00",
      "isPinned": false,
      "expertId": "0123456789abcdef",
      "runtimeType": "codex"
    }
  ]
}
```

## GET /sessions/{session_id}/messages

List the turns of a session (the conversational record), read from the local store.

Response:

```json
{
  "items": [
    {
      "id": "turn_1",
      "sessionId": "thread_1",
      "requestText": "Analyze recent review trends",
      "reasoningText": "...",
      "responseText": "...",
      "model": "codex/gpt-5",
      "expertId": "0123456789abcdef",
      "runtimeType": "codex",
      "status": "completed",
      "stopReason": "end_turn",
      "errorMessage": null,
      "retrievalRefs": [
        {
          "citationId": "cite_1",
          "knowledgeBaseId": "kb_123",
          "knowledgeBaseName": "Policies",
          "documentId": "doc_123",
          "fileName": "scanned-policy.pdf",
          "filePath": "scanned-policy.pdf",
          "pageNumber": 1,
          "hitText": "Approval code ALPHA 84A1",
          "locator": {"type": "pdf", "pageNumber": 1},
          "citationIds": ["cite_1"],
          "previewUrl": "/api/v1/chat/turns/turn_1/citations/cite_1/preview",
          "downloadUrl": "/api/v1/chat/turns/turn_1/citations/cite_1/download",
          "available": true
        }
      ],
      "createdAt": "2026-06-07T00:00:00+00:00",
      "completedAt": "2026-06-07T00:00:05+00:00"
    }
  ]
}
```

## GET /sessions/{session_id}

Get a single session.

Response is a session object.

## DELETE /sessions/{session_id}

Delete a session locally.

Response `200`:

```json
{
  "id": "thread_1",
  "status": "deleted"
}
```

## PATCH /sessions/{session_id}/title

Rename a session.

Request:

```json
{
  "title": "New title"
}
```

Response is a session object.

## PATCH /sessions/{session_id}/pin

Pin or unpin a session.

Request:

```json
{
  "isPinned": true
}
```

Response is a session object:

```json
{
  "id": "thread_1",
  "title": "Review analysis",
  "isPinned": true,
  "createdAt": "2026-06-07T00:00:00+00:00",
  "updatedAt": "2026-06-07T00:00:05+00:00"
}
```

## POST /sessions/{session_id}/turns

Create a turn and stream its events. The session (thread) id is taken from the path.

Request:

```json
{
  "question": "Analyze recent review trends",
  "webSearchEnabled": true
}
```

`question` is required. `webSearchEnabled` is optional and only applies to the ACP
agent-gateway backend: `true` routes to the configured search ACP prefix with
`search_mode: "auto"`, while `false` or omitted routes to the default ACP prefix with
`search_mode: "off"`. Model / knowledge-base / retrieval options are not accepted here.

Response content type:

```text
text/event-stream
```

The response is the live SSE stream translated from ACP `POST {prefix}/turn`. The first
event is `turn_started`, carrying `turnId`, followed by `reasoning_delta` (model
thinking), `message_delta` (assistant answer), tool / usage / `turn_completed` events.
A mid-turn
`permission_required` event must be answered via `POST /permissions/{permission_id}`.
The backend owns this separation: process output (thinking, retrieval, tool progress)
is emitted only as `reasoning_delta` or structured tool/usage events, while
`message_delta` carries only the final user-facing answer. `message_delta.delta` is
normalized Markdown, so clients should render it as Markdown rather than infer headings
or list structure themselves. Both `reasoning_delta` and `message_delta` are emitted as
smoothed incremental deltas; clients should append each delta to the relevant buffer and
render progressively.
For `reasoning_delta`, `reasoningId` is stable for the turn and `mode` is `append`;
clients must update one reasoning block keyed by `reasoningId`, not create a new
reasoning item for each event.

The public backend request field is `question`. Internally, the backend sends it as ACP
turn `input`.

### Knowledge release and `sources`

For a knowledge-bound Expert, retrieval is a read-only MCP tool rather than an unconditional
pre-turn step. The model decides whether the question needs Expert reference documents. When it
calls `search_expert_knowledge`, Backend requires a ready isolated KB binding, queries exact chunks
through LightRAG `/query/data`, and maps every returned reference to a live byte-current Document
whose indexing pipeline version matches Backend.

Any binding/Workspace/network retrieval error, or incomplete/ambiguous reference
coverage returns a fail-closed MCP tool error. The main binding error is:

```json
{
  "code": "KNOWLEDGE_INDEX_NOT_READY",
  "message": "A bound knowledge base index is not ready",
  "details": {
    "knowledgeBaseId": "kb_123",
    "indexStatus": "provisioning",
    "retryable": true
  }
}
```

A valid retrieval is persisted on the Turn and emitted before the Turn completes:

```json
{
  "knowledgeBaseIds": ["kb_123"],
  "knowledgeBaseId": "kb_123",
  "documents": [
    {
      "citationId": "cite_1",
      "citationIds": ["cite_1"],
      "knowledgeBaseId": "kb_123",
      "knowledgeBaseName": "Policies",
      "documentId": "doc_123",
      "fileName": "scanned-policy.pdf",
      "filePath": "scanned-policy.pdf",
      "pageNumber": 1,
      "mimeType": "application/pdf",
      "hitText": "Approval code ALPHA 84A1",
      "locator": {"type": "pdf", "pageNumber": 1},
      "previewUrl": "/api/v1/chat/turns/turn_1/citations/cite_1/preview",
      "downloadUrl": "/api/v1/chat/turns/turn_1/citations/cite_1/download",
      "available": true
    }
  ]
}
```

`knowledgeBaseIds` is authoritative. The singular compatibility field is emitted only for one KB.
Tool evidence is labelled with `[cite_N]`, and the Runtime is instructed to cite those ids.
The stored Turn keeps SHA, LightRAG file/index identities and chunk provenance for integrity and
download resolution, but those internal fields are not returned in `retrievalRefs`, `sources`, or
the citation preview DTO. `filePath` temporarily mirrors the authorized `fileName` for existing
clients; new clients should render `fileName` and append ` · 第 N 页` only when `pageNumber` is not
null. Same-Document/same-page duplicates are collapsed in first-retrieval order and expose all
merged `citationIds`.

Before the SSE response starts, the Backend first reserves a `running` row in `chat_turns`.
A database partial unique index permits only one running Turn per Chat Session, so a concurrent
request returns `409 CHAT_TURN_ALREADY_RUNNING`. After reservation, the Backend validates
attachments, rechecks Expert access for bound sessions, creates or reads the tenant's current
credit period, and checks the positive balance. A rejected pre-flight finalizes the reserved
Turn as failed before returning the original HTTP error. Clean pre-stream errors include:

```text
402 CREDIT_EXHAUSTED
403 EXPERT_NOT_INCLUDED_IN_PLAN
409 CHAT_TURN_ALREADY_RUNNING
```

While streaming, the Backend persists the assembled result (`request_text`, `reasoning_text`,
`response_text`, `status`, `stop_reason`, usage snapshots, ...). Execution belongs to a single Backend worker; browser disconnect only detaches SSE.
Startup marks interrupted Turns failed/interrupted and preserves partial output without resuming ACP. During schema
upgrade, if legacy data already contains duplicate running rows for one Session, the newest is
preserved as running and older duplicates are marked cancelled before the unique index is created.

After the durable Turn terminal state commits, the Backend records one
idempotent credit usage settlement. Credit settlement failure is logged without
changing an otherwise successful Turn or its completion SSE. A Turn already
cancelled is never overwritten by stream completion. New settlements use the
cache-estimating `estimated-cache-v2` calculator documented in
[`credits.md`](credits.md); it is not evidence of a Provider cache hit.

## POST /turns/{turn_id}/cancel

Cancel upstream execution and wait for finalization, preserving partial output.
An already terminal Turn retains its status. Page unmount should only detach SSE.

Response:

```json
{
  "turnId": "turn_1",
  "status": "cancelled"
}
```

## GET /turns/{turn_id}/events

Replay a stored turn's events. Use this to reconnect to a turn created by
`POST /sessions/{session_id}/turns`.

Query parameters:

- `after` (optional, integer >= 0): replay events with a greater SSE id.
- `Last-Event-ID` header: used when `after` is absent. Future cursors return 400.

Response content type:

```text
text/event-stream
```

Events are persisted in order with monotonically increasing ids scoped to the Turn.
Without a cursor, replace local state from `turn_snapshot` and continue after its `eventSeq`.
Apply deltas once per id; terminal `turn_state` replaces the final state, including retrievalRefs.
Reconnect without another POST to avoid executing and charging again. Ownership is rechecked
on every database read. Legacy terminal Turns without events produce a snapshot at zero.

## GET /turns/{turn_id}/citations/{citation_id}/preview

Return the owner-authorized durable hit snapshot. It contains citation/KB/Document display
metadata, nullable one-based `pageNumber`, `hitText`, locator and a text preview. Because the
snapshot is stored on the Turn, it
survives later Document rename or soft delete.

## GET /turns/{turn_id}/citations/{citation_id}/download

Resolve the exact internal `documentId + sourceSha256` provenance, verify it and return a
short-lived download URL for that immutable source. The hash is not returned to the caller. The
source remains available after soft delete
while object GC has not reclaimed the source bytes. Another tenant/user receives `404` through the
normal Turn-ownership boundary.

## POST /permissions/{permission_id}

Resolve a `permission_required` event raised mid-turn (e.g. a tool approval). Proxies to
ACP `POST {prefix}/permission`.

Request (one of `outcome` / `optionId` is required):

```json
{
  "outcome": "approved",
  "optionId": "opt_1"
}
```

`outcome` is one of `approved`, `declined`, `cancelled`.

Public ACP progress contains application-owned status text only. Raw reasoning, tool names, arguments, and execution errors are private. Legacy reasoning is replaced on message, transcript and event replay reads. Runtime contract 10 describes operation failures in business terms without claiming tool success; normal publication installs these instructions.
