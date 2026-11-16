# Codex Runtime boundary

Backend publication selects the Runtime Home, workspace and explicit Service environment.
The bundled `runtime/codex-acp` launcher applies the boundary before starting ACP:

- Only the current Runtime Home, current tenant/user workspace, and required system
  dependencies enter the filesystem view. Bound Skills and platform configuration are
  read-only; generated files belong in the current workspace.
- `EXPERT_ACP_RUNTIME_ENV_NAMES` is a space-separated list of published environment
  variable names. Bubblewrap clears inherited Gateway variables and passes only this
  list plus fixed runtime paths and locale. Backend includes bound SecretRef values and
  restricted model/MCP tokens. An unrelated Gateway environment credential is not inherited.
- A user namespace maps the host owner to namespace UID 65534. The adapter has no
  effective or bounding capabilities, no supplementary groups, and cannot acquire new
  privileges. Using a nonzero namespace UID also permits Codex's nested Bubblewrap
  sandbox after capabilities are dropped; existing host file ownership is preserved.
- Sockets retain the dedicated host `expert-runtime` group. IPv4/IPv6 OUTPUT rules reject
  only this group's TCP connections to local management ports 2019 and 8019. Other users,
  the Gateway data plane, bound MCP, ordinary networking and authorized file transfer
  remain available. This does not authorize data transfer requested by external content.

The Gateway starts the launcher as root. `setpriv` switches to the Runtime Home owner's
host UID and the dedicated group before Bubblewrap drops privileges. Backend-created
Runtime Homes and user workspaces therefore remain writable by their actual owner;
no host DAC capability is retained. The launcher checks both firewall rules before
starting ACP and fails closed if the deployment boundary is missing or an earlier
OUTPUT rule could bypass it. The namespace has no authority to change the host firewall or
the host socket group.

## Install on the local Linux host

Requirements: Bubblewrap, util-linux (`setpriv`), iptables/ip6tables, and systemd.
The supplied unit uses the standard `/usr/local/amazon` repository layout.

```bash
cd /usr/local/amazon/amazon-experts-backend-dev
sudo install -m 0644 runtime/expert-runtime-network.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now expert-runtime-network.service
sudo runtime/sandbox-network check
```

The idempotent helper creates the dedicated system group and installs the two narrow
rules first in OUTPUT. It changes no Gateway source/configuration and no data volume.
Keep this unit enabled before publishing Experts or starting their runtime. If another
host firewall manager replaces OUTPUT rules, apply this boundary afterward and run
`check`; newly launched adapters refuse to proceed without it.

To remove the deployment, stop Expert runtime consumers first, then disable and stop
`expert-runtime-network.service`. Its stop action removes only its own rules. The system
group is retained to avoid recycling the GID while a process might still use it.

On Ubuntu hosts with `kernel.apparmor_restrict_unprivileged_userns=1`, install
the launcher-specific AppArmor profile before starting Expert runtimes:

```bash
sudo install -m 0644 runtime/expert-runtime.apparmor /etc/apparmor.d/expert-runtime
sudo apparmor_parser -r /etc/apparmor.d/expert-runtime
```

This permits user namespace creation for the fixed managed launcher and its children.
It preserves the global userns restriction and the launcher's Bubblewrap filesystem,
capability and network boundaries. Without it, nested Bubblewrap can fail with
`setting up uid map: Permission denied`; kernel audit logs identify
`profile="unprivileged_userns"` and a disconnected `proc/<pid>/uid_map` denial.
Existing adapter processes must be closed and recreated to acquire the profile.
Use normal unlist/republish for affected Experts; never edit generated Runtime Homes.
Hosts without this AppArmor restriction do not need the profile.

## Existing root-owned runtime state

Earlier launchers ran the adapter as host root. A Home owned by the Backend service user
may still contain root-owned Codex state or managed files. Before switching such a Home
to owner-UID execution, unlist that Expert through the normal Backend API and stop its
active turns. Then run the narrowly scoped ownership repair once:

```bash
sudo runtime/repair-runtime-ownership \
  /usr/local/amazon/output/experts \
  /usr/local/amazon/output/experts/expert-codex-<16-hex-id>
```

The helper requires a real direct child of the supplied Runtime root whose owner is
already the Backend service user. It changes only root-owned entries to that owner's UID,
does not follow symbolic links, and preserves content, structure, groups and file modes.
Republish through the Backend API afterward. Never run publication as root to work
around a permissions failure, because that creates ownership different from the service.

Local migration of the original published Expert changed 132 owner metadata entries;
path names, groups, modes and file hashes were unchanged. Both the original Expert and
a newly created Expert then published successfully through the actual Backend API.
The original Expert also completed a fresh ordinary-user chat that generated and read
a report in its real user workspace with host UID 1000. Its test file and session were
removed.

## Verification and logs

Focused tests in `tests/test_codex_runtime_sandbox.py` exercise the wrapper's environment
and launch preconditions without requiring privileged host mutations. For real boundary
acceptance, use a temporary Runtime Home/workspace and simulated private data, then run
the actual wrapper. Verify Skill reads, workspace writes and a nested Bubblewrap command
alongside denied Skill/config writes, unrelated file reads, group changes and management
connections. Also verify a real published Expert/ACP Skill or MCP turn; a wrapper probe
alone does not establish model-path compatibility.

Local acceptance on 2026-09-08 verified the actual wrapper: bound Skill read and workspace
file generation succeeded; Skill/config writes failed without changing either source;
another test user's file was absent; an unrelated simulated host secret was omitted
while a published restricted token remained; effective and bounding capabilities were
zero; changing the socket group failed; both local management ports refused connections;
Gateway 8080 and an authorized temporary HTTP file endpoint returned 200; the nested
Bubblewrap command generated its output successfully. Temporary probe resources were
removed. The original published Expert was then republished through the normal Backend
service with generated restricted permissions and `never` command approval; its real ACP
marker turn completed and the publication thread was closed. This caught and fixed a Gateway
PATH difference: administrative binaries are searched in standard sbin directories.
Shared-server deployment was not performed.

Wrapper preflight failures are concise stderr events captured by the existing Gateway
process logs. Codex may reject a permission escalation before emitting any ACP tool-call
event; those denials remain in existing adapter/Gateway logs. Backend's existing turn
logs can record ACP tool failures when such events are emitted. Do not interpret normal
model refusals or questions about model names as security incidents, and never add
tokens, raw file content or credential-bearing URLs to diagnostics.
