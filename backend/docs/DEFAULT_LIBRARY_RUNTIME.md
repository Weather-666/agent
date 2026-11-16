# Personal Library on the default Codex route

Unbound ACP sessions retain their default route, Codex Home, Skills and workspace.
They receive a current-Turn capability just like bound Expert sessions. The internal
MCP endpoint `/internal/mcp/library/default` uses a distinct service credential and
accepts only running Turns whose session and Turn both have no Expert identity.
Owner, tenant membership, file lifecycle and deletion checks remain unchanged.
All public chat transcripts use the Backend's owner-scoped records, excluding
internal authorization prompts from agent transcripts.

## Configure an existing default service

Run from the Backend repository with its deployment environment. First check the
default Codex configuration's active model provider name (for example `agw`).
`EXPERT_MCP_MODEL_COMPAT_BASE_URL` must point to the reachable namespace adapter;
the internal MCP origin comes from `EXPERT_KNOWLEDGE_MCP_BASE_URL`.

```bash
.venv/bin/python -m scripts.configure_default_library --model-provider agw
.venv/bin/python -m scripts.configure_default_library --model-provider agw \
  --apply --backup /absolute/private/default-services-before-library.json
```

The first command is a dry run. Apply backs up the original services to an exclusive
mode-0600 file, then updates and reads back only services behind the configured
default/search routes. It preserves the existing model, HOME, CODEX_HOME, Skills,
working directory, unrelated adapter arguments and other MCP servers. It adds
Codex adapter `-c` overrides for personal Library and the active provider's namespace
adapter URL, plus the service authentication environment value. Do not print or
commit the backup. Do not hand-edit generated Expert Homes.

Deploy Backend source before enabling the MCP service. Existing pooled processes
may need to be closed through Gateway's service/thread lifecycle before they see
new adapter arguments; do not restart unrelated services. Preserve saved chat
history and Skill files. Rollback restores the backed-up service configuration
through Gateway Admin and the previous Backend commit.

## Acceptance

Use an authenticated default session, no `expertId` and no `attachmentFileIds`.
Ask for an owned permanent personal file by exact name. Require real file content,
completed Turn status and `attachments.source=personal_library_tool`. Check a
follow-up in an existing session, unchanged Skill use, and another user's denial
for the same file ID. Public history must contain no `lturn_` capability. Delete
only test sessions/files and revoke test login refresh tokens afterward.
