from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest


@pytest.fixture
def sandbox_launcher(tmp_path: Path):
    runtime_root = tmp_path / "experts"
    runtime_home = runtime_root / "expert-codex-1825107e997dfde2"
    workspace_root = tmp_path / "workspaces"
    workspace = workspace_root / "tenant/users/current"
    node_bin = tmp_path / "node-runtime/bin"
    runtime_home.mkdir(parents=True)
    workspace.mkdir(parents=True)
    node_bin.mkdir(parents=True)
    for name in (".git", ".agents", ".codex"):
        (workspace / name).mkdir()
    for name in ("node", "codex-acp"):
        executable = node_bin / name
        executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        executable.chmod(0o755)
    # Observe the launch contract without requiring host mount privileges.
    bwrap = node_bin / "bwrap"
    bwrap.write_text(
        """#!/usr/bin/python3
import json
import os
import sys
args = sys.argv[1:]
environment = dict(os.environ)
for index, value in enumerate(args):
    if value == "--":
        break
    if value == "--clearenv":
        environment.clear()
    elif value == "--setenv":
        environment[args[index + 1]] = args[index + 2]
print(json.dumps({
    "environment": environment,
    "user_namespace": "--unshare-user" in args,
    "capabilities_dropped": any(args[i:i+2] == ["--cap-drop", "ALL"] for i in range(len(args))),
}))
""",
        encoding="utf-8",
    )
    bwrap.chmod(0o755)
    getent = node_bin / "getent"
    getent.write_text("#!/bin/sh\n echo expert-runtime:x:61999:\n", encoding="utf-8")
    getent.chmod(0o755)
    setpriv = node_bin / "setpriv"
    setpriv.write_text("#!/bin/sh\nshift 6\nexec \"$@\"\n", encoding="utf-8")
    setpriv.chmod(0o755)
    for name in ("iptables", "ip6tables"):
        firewall = node_bin / name
        firewall.write_text(
            "#!/bin/sh\n"
            'if [ "${MISSING_MANAGEMENT_FIREWALL:-}" = 1 ]; then exit 1; fi\n'
            'if [ "$3" = "-S" ]; then\n'
            "  echo '-A OUTPUT -p tcp -m owner --gid-owner 61999 "
            "-m multiport --dports 2019,8019 -m addrtype --dst-type LOCAL "
            "-j REJECT --reject-with tcp-reset'\n"
            "fi\n",
            encoding="utf-8",
        )
        firewall.chmod(0o755)
    wrapper = Path(__file__).resolve().parents[1] / "runtime/codex-acp"
    environment = {
        "HOME": str(runtime_home),
        "CODEX_HOME": str(runtime_home),
        "EXPERT_ACP_REAL_ADAPTER_COMMAND": str(node_bin / "codex-acp"),
        "EXPERT_ACP_SANDBOX_RUNTIME_ROOT": str(runtime_root),
        "EXPERT_ACP_SANDBOX_WORKSPACE_ROOT": str(workspace_root),
        "PATH": f"{node_bin}:/usr/bin:/bin",
        "UNRELATED_ADMIN_SECRET": "simulated-admin-secret",
        "OPENAI_API_KEY": "simulated-upstream-master-key",
    }

    def launch(extra: dict[str, str]):
        return subprocess.run(
            ["bash", str(wrapper)],
            cwd=workspace,
            env={**environment, **extra},
            capture_output=True,
            text=True,
            check=False,
        )

    return launch


def test_runtime_receives_only_published_environment(sandbox_launcher) -> None:
    result = sandbox_launcher(
        {
            "EXPERT_ACP_RUNTIME_ENV_NAMES": "EXPERT_MCP_AUTHORIZATION SKILL_API_TOKEN",
            "EXPERT_MCP_AUTHORIZATION": "Bearer simulated-restricted-key",
            "SKILL_API_TOKEN": "simulated-bound-skill-key",
        }
    )

    assert result.returncode == 0, result.stderr
    launch = json.loads(result.stdout)
    environment = launch["environment"]
    assert environment["EXPERT_MCP_AUTHORIZATION"] == "Bearer simulated-restricted-key"
    assert environment["SKILL_API_TOKEN"] == "simulated-bound-skill-key"
    assert environment["HOME"] == environment["CODEX_HOME"]
    assert environment["TMPDIR"] == "/tmp"
    assert "UNRELATED_ADMIN_SECRET" not in environment
    assert "OPENAI_API_KEY" not in environment
    assert "EXPERT_ACP_RUNTIME_ENV_NAMES" not in environment
    assert launch["user_namespace"]
    assert launch["capabilities_dropped"]


@pytest.mark.parametrize(
    ("names", "reason"),
    [
        ("MISSING_BOUND_TOKEN", "published Runtime environment variable is missing"),
        ("INVALID=NAME", "Runtime environment contains an invalid variable name"),
    ],
)
def test_runtime_rejects_invalid_published_environment(
    sandbox_launcher,
    names: str,
    reason: str,
) -> None:
    result = sandbox_launcher({"EXPERT_ACP_RUNTIME_ENV_NAMES": names})

    assert result.returncode == 70
    assert reason in result.stderr
    assert not result.stdout


def test_runtime_does_not_inherit_gateway_environment_without_manifest(sandbox_launcher) -> None:
    result = sandbox_launcher({})

    assert result.returncode == 0, result.stderr
    environment = json.loads(result.stdout)["environment"]
    assert "UNRELATED_ADMIN_SECRET" not in environment
    assert "OPENAI_API_KEY" not in environment


def test_runtime_rejects_missing_management_network_boundary(sandbox_launcher) -> None:
    result = sandbox_launcher({"MISSING_MANAGEMENT_FIREWALL": "1"})

    assert result.returncode == 70
    assert "Runtime management-network isolation is not installed" in result.stderr
    assert not result.stdout


@pytest.mark.skipif(os.geteuid() != 0, reason="requires the installed host firewall boundary")
def test_installed_network_guard_with_gateway_path() -> None:
    guard = Path(__file__).resolve().parents[1] / "runtime/sandbox-network"
    installed = subprocess.run(
        ["bash", str(guard), "check"],
        env={"PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"},
        capture_output=True,
        text=True,
        check=False,
    )
    if installed.returncode:
        pytest.skip("the host Runtime firewall boundary is not installed")

    result = subprocess.run(
        ["/bin/bash", str(guard), "check"],
        env={"PATH": "/usr/local/bin:/usr/bin:/bin"},
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


@pytest.mark.skipif(os.geteuid() != 0, reason="requires ownership changes on temporary fixtures")
def test_ownership_repair_stays_in_the_selected_home(tmp_path: Path) -> None:
    root = tmp_path / "runtimes"
    home = root / "expert-codex-1825107e997dfde2"
    home.mkdir(parents=True)
    os.chown(home, 1000, -1)
    state = home / "state.sqlite"
    state.write_bytes(b"simulated-runtime-state")
    state.chmod(0o600)
    outside = tmp_path / "private"
    outside.write_bytes(b"simulated-unrelated-data")
    link = home / "external-link"
    link.symlink_to(outside)
    other = root / "expert-codex-1a97db50554f464e"
    other.mkdir()
    other_state = other / "state.sqlite"
    other_state.write_bytes(b"other-runtime-state")
    repair = Path(__file__).resolve().parents[1] / "runtime/repair-runtime-ownership"

    rejected = subprocess.run(
        [str(repair), str(tmp_path), str(home)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert rejected.returncode != 0
    assert state.stat().st_uid == 0

    result = subprocess.run(
        [str(repair), str(root), str(home)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert state.stat().st_uid == 1000
    assert state.stat().st_mode & 0o777 == 0o600
    assert state.read_bytes() == b"simulated-runtime-state"
    assert link.is_symlink()
    assert outside.stat().st_uid == 0
    assert outside.read_bytes() == b"simulated-unrelated-data"
    assert other_state.stat().st_uid == 0
