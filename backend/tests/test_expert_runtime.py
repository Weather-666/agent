from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import stat
import subprocess
from pathlib import Path
from typing import Any

import pytest
from pydantic import SecretStr, ValidationError

from app.clients.acp_gateway import AcpGatewayClient
from app.clients.builder_process import BuilderProcess
from app.clients.gateway_admin import (
    GatewayAdminClient,
    GatewayMcpRoute,
    GatewayMcpRouteUpsert,
    GatewayMcpService,
    GatewayMcpTool,
    GatewayVirtualKey,
    GatewayVirtualKeyUpsert,
)
from app.clients.mcp_gateway import McpInitializeResult, McpTool, McpToolCallResult
from app.core.config import Settings
from app.core.errors import ApiError
from app.db import migrate_database, open_database_connection
from app.domain.auth import PlatformRole, Principal
from app.domain.chat import ChatTurnRequest, CreateSessionRequest
from app.domain.expert_runtime import expert_runtime_name
from app.domain.experts import CreateExpertRequest, UpdateExpertRequest
from app.services.library_mcp_service import library_mcp_authorization
from app.services.chat_service import ChatService
from app.services.expert_publication_service import ExpertPublicationService
from app.services.expert_repository import ExpertRepository
from app.services.expert_runtime_reconciliation import reconcile_published_experts
from app.services.expert_service import ExpertService


class FakeSkillStorage:
    def get_file(self, slug: str, path: str) -> bytes:
        raise AssertionError(f"Unexpected Skill read: {slug}/{path}")


class FakeObjectStore:
    def __init__(self, objects: dict[str, bytes] | None = None) -> None:
        self.objects = objects or {}

    def read(self, storage_key: str) -> bytes:
        if storage_key not in self.objects:
            raise AssertionError(f"Unexpected object read: {storage_key}")
        return self.objects[storage_key]


class FakeBuilder:
    def __init__(self) -> None:
        self.inputs: list[dict[str, Any]] = []
        self.status_reader = None
        self.observed_statuses: list[str] = []

    async def build(
        self,
        *,
        input_path: Path,
        assets_dir: Path,
        output_dir: Path,
        expert_id: str,
        runtime_type: str,
    ) -> dict[str, Any]:
        assert assets_dir.is_dir()
        if self.status_reader is not None:
            self.observed_statuses.append(self.status_reader())
        source = json.loads(input_path.read_text(encoding="utf-8"))
        self.inputs.append(source)
        if runtime_type == "codex":
            (output_dir / ".agents/skills").mkdir(parents=True)
            (output_dir / "knowledge").mkdir()
            (output_dir / "AGENTS.md").write_text(source["instructions"], encoding="utf-8")
            (output_dir / "config.toml").write_text(
                """model_provider = "agent-gateway"
approval_policy = "never"
project_doc_max_bytes = 0
developer_instructions = "Expert instructions\\n"
default_permissions = "expert-runtime"

[permissions.expert-runtime.filesystem]
":minimal" = "read"
":tmpdir" = "write"
":slash_tmp" = "write"
"~/.agents/skills" = "read"

[permissions.expert-runtime.filesystem.":workspace_roots"]
"." = "write"
".git" = "deny"
".agents" = "deny"
".codex" = "deny"

[permissions.expert-runtime.network]
enabled = true
""".replace('developer_instructions = "Expert instructions\\n"',
            "developer_instructions = " + json.dumps(source["instructions"])),
                encoding="utf-8",
            )
        else:
            (output_dir / ".config/opencode").mkdir(parents=True)
            (output_dir / ".agents/skills").mkdir(parents=True)
            (output_dir / "knowledge").mkdir()
            (output_dir / ".config/opencode/AGENTS.md").write_text(
                "Expert instructions\n", encoding="utf-8"
            )
            (output_dir / ".config/opencode/opencode.json").write_text("{}\n", encoding="utf-8")
        for knowledge in source.get("knowledge", []):
            for document in knowledge.get("documents", []):
                source_path = assets_dir / document["assetPath"]
                target_path = output_dir / "knowledge" / knowledge["id"] / document["path"]
                target_path.parent.mkdir(parents=True, exist_ok=True)
                target_path.write_bytes(source_path.read_bytes())
        return {
            "status": "passed",
            "expertId": expert_id,
            "runtimeType": runtime_type,
            "output": str(output_dir.resolve()),
        }

    async def validate(self, output_dir: Path, *, runtime_type: str) -> dict[str, Any]:
        return {
            "status": "passed",
            "runtimeType": runtime_type,
            "output": str(output_dir.resolve()),
        }


class FakeGateway:
    def __init__(self) -> None:
        self.services: dict[str, dict[str, Any]] = {}
        self.routes: dict[str, dict[str, Any]] = {}
        self.allowed_routes: set[str] = set()
        self.closed_threads: list[tuple[str, str]] = []
        self.mcp_services: dict[str, GatewayMcpService] = {
            "local_test": GatewayMcpService(
                id="local_test",
                name="Local MCP test",
                description="System acceptance Connector",
                transport="streamable_http",
            )
        }
        self.mcp_tools: dict[str, list[GatewayMcpTool]] = {
            "local_test": [
                GatewayMcpTool(name="check_product_mcp"),
                GatewayMcpTool(name="check_policy_mcp"),
            ]
        }
        self.mcp_routes: dict[str, GatewayMcpRoute] = {}
        self.virtual_keys: dict[str, GatewayVirtualKey] = {}
        self.mcp_initializations: list[str] = []
        self.disable_attempts: list[tuple[str, str]] = []
        self.disable_route_errors: set[str] = set()
        self.disable_service_errors: set[str] = set()

    async def upsert_service(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.services[str(payload["id"])] = dict(payload)
        return payload

    async def upsert_route(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.routes[str(payload["id"])] = dict(payload)
        return payload

    async def assert_service(self, expected: dict[str, Any]) -> None:
        assert self.services[expected["id"]] == expected

    async def assert_route(self, expected: dict[str, Any]) -> None:
        assert self.routes[expected["id"]] == expected

    async def add_virtual_key_route(self, virtual_key_id: str, route_id: str) -> dict[str, Any]:
        assert virtual_key_id == "backend-acp"
        self.allowed_routes.add(route_id)
        return {"id": virtual_key_id, "key": "route-access-key"}

    async def get_service(self, service_id: str) -> dict[str, Any] | None:
        return self.services.get(service_id)

    async def get_route(self, route_id: str) -> dict[str, Any] | None:
        return self.routes.get(route_id)

    async def disable_service(self, service_id: str) -> None:
        self.disable_attempts.append(("service", service_id))
        if service_id in self.disable_service_errors:
            raise RuntimeError("service disable failed")
        if service_id in self.services:
            self.services[service_id]["disabled"] = True

    async def disable_route(self, route_id: str) -> None:
        self.disable_attempts.append(("route", route_id))
        if route_id in self.disable_route_errors:
            raise RuntimeError("route disable failed")
        if route_id in self.routes:
            self.routes[route_id]["disabled"] = True

    async def close_acp_thread(self, service_id: str, thread_id: str) -> int:
        self.closed_threads.append((service_id, thread_id))
        return 1

    async def get_mcp_service(self, service_id: str) -> GatewayMcpService | None:
        return self.mcp_services.get(service_id)

    async def initialize_mcp_service(self, service_id: str) -> dict[str, Any]:
        self.mcp_initializations.append(service_id)
        return {"tools": {}}

    async def list_mcp_service_tools(self, service_id: str) -> list[GatewayMcpTool]:
        return self.mcp_tools.get(service_id, [])

    async def upsert_mcp_route(self, route: GatewayMcpRouteUpsert) -> GatewayMcpRoute:
        actual = GatewayMcpRoute.model_validate(route.model_dump())
        self.mcp_routes[route.id] = actual
        return actual

    async def upsert_virtual_key(
        self,
        key: GatewayVirtualKeyUpsert,
    ) -> GatewayVirtualKey:
        current = self.virtual_keys.get(key.id)
        secret = current.key if current and current.key else SecretStr("mcp-route-access-key")
        actual = GatewayVirtualKey(
            **key.model_dump(exclude={"disabled"}),
            key=secret,
            disabled=False,
        )
        self.virtual_keys[key.id] = actual
        return actual

    async def disable_virtual_key(self, key_id: str) -> None:
        if key_id in self.virtual_keys:
            self.virtual_keys[key_id].disabled = True


class FakeMcpGateway:
    def __init__(self, gateway: FakeGateway) -> None:
        self.gateway = gateway
        self.initialized_paths: list[str] = []
        self.listed_paths: list[str] = []
        self.called_tools: list[tuple[str, str]] = []

    async def initialize(self, route_path: str, key: SecretStr) -> McpInitializeResult:
        assert key.get_secret_value() == "mcp-route-access-key"
        self.initialized_paths.append(route_path)
        return McpInitializeResult(protocolVersion="2025-06-18")

    async def list_tools(self, route_path: str, key: SecretStr) -> list[McpTool]:
        assert key.get_secret_value() == "mcp-route-access-key"
        self.listed_paths.append(route_path)
        route = next(
            item for item in self.gateway.mcp_routes.values()
            if item.match_policy.path_prefix == route_path
        )
        return [
            McpTool.model_validate(tool.model_dump())
            for tool in self.gateway.mcp_tools[route.service_id]
        ]

    async def call_tool(
        self,
        route_path: str,
        key: SecretStr,
        name: str,
        arguments: dict[str, Any] | None = None,
    ) -> McpToolCallResult:
        self.called_tools.append((route_path, name))
        return McpToolCallResult(isError=False)


class FakeAcp:
    def __init__(self, *, pass_smoke: bool = True, marker_only_in_transcript: bool = False) -> None:
        self.auth_token: str | None = None
        self.pass_smoke = pass_smoke
        self.fail_smokes = 0
        self.marker_only_in_transcript = marker_only_in_transcript
        self.default_model: str | None = None
        self.route_prefix = "/acp/default"
        self.search_route_prefix: str | None = None
        self.calls: list[dict[str, Any]] = []

    def prepare_tenant_cwd(self, tenant_id: str) -> str:
        return f"/tmp/expert-runtime-tests/{tenant_id}"

    def prepare_user_cwd(self, tenant_id: str, user_id: str) -> str:
        return f"/tmp/expert-runtime-tests/{tenant_id}/users/{user_id}"

    async def list_sessions(self, **kwargs: Any) -> dict[str, Any]:
        return {"sessions": [], "next_cursor": ""}

    async def get_transcript(self, **kwargs: Any) -> dict[str, Any]:
        marker = str(self.calls[-1]["input"]).rsplit(" ", 1)[-1]
        return {"messages": [{"role": "assistant", "text": marker}]}

    def stream_turn(self, **kwargs: Any):
        self.calls.append(kwargs)
        input_text = str(kwargs["input"])
        is_publication_smoke = str(kwargs["thread_id"]).startswith("publication-")
        marker = input_text.rsplit(" ", 1)[-1] if is_publication_smoke else input_text

        async def events():
            fail_smoke = is_publication_smoke and self.fail_smokes > 0
            if fail_smoke:
                self.fail_smokes -= 1
            if self.pass_smoke and not fail_smoke:
                if not is_publication_smoke or self.marker_only_in_transcript:
                    session_id = str(kwargs.get("session_id") or "acp_session_preserved")
                    yield "event: session"
                    yield f'data: {{"session_id": "{session_id}"}}'
                    yield ""
                if not self.marker_only_in_transcript:
                    yield "event: delta"
                    yield "data: " + json.dumps({"text": marker})
                    yield ""
                yield "event: done"
                yield 'data: {"stop_reason": "end_turn"}'
                yield ""
            else:
                yield "event: done"
                yield 'data: {"stop_reason": "end_turn"}'
                yield ""

        return events()


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        database_url=f"sqlite:///{tmp_path / 'backend.sqlite3'}",
        acp_gateway_base_url="http://127.0.0.1:8080",
        acp_config_base=str(tmp_path / "experts"),
        acp_cwd_base=str(tmp_path / "tenant-workspaces"),
        acp_virtual_key_id="backend-acp",
        acp_codex_adapter_command="/opt/expert-runtime/codex-acp",
        acp_codex_real_adapter_command="/usr/local/bin/codex-acp",
        agent_gateway_model_base_url="http://127.0.0.1:8080/v1",
        agent_gateway_model_api_key="model-route-key",
    )


def _principal() -> Principal:
    return Principal(
        user_id="platform_admin",
        email="admin@example.com",
        platform_roles=[PlatformRole.ADMIN],
        platform_permissions=["expert:read", "expert:write"],
        active_tenant_id="tenant_default",
        tenant_permissions=["chat:ask"],
    )


def _prepare_database(settings: Settings) -> None:
    migrate_database(settings)
    with open_database_connection(settings) as connection:
        connection.execute(
            """
            insert into users (id, email, password_hash, name, status)
            values ('platform_admin', 'admin@example.com', 'hash', 'Admin', 'active')
            """
        )
        connection.execute(
            """
            insert into tenants (id, name, slug, status)
            values ('tenant_default', 'Default tenant', 'default-tenant', 'active')
            on conflict (id) do nothing
            """
        )
        connection.execute(
            """
            insert into tenant_members (id, tenant_id, user_id, role)
            values ('member_runtime_admin', 'tenant_default', 'platform_admin', 'member')
            on conflict (tenant_id, user_id) do nothing
            """
        )
        connection.execute(
            """
            insert into subscriptions (
              id, tenant_id, plan_id, status, billing_period, current_period_start
            ) values (
              'subscription_runtime_tests', 'tenant_default', 'plan_max',
              'active', 'monthly', CURRENT_TIMESTAMP
            )
            on conflict (id) do nothing
            """
        )
        connection.commit()


def _create_expert(
    connection,
    *,
    name: str = "Runtime Expert",
    knowledge_base_ids: list[str] | None = None,
    mcp_connector_ids: list[str] | None = None,
):
    return ExpertService(connection).create(
        _principal(),
        CreateExpertRequest.model_validate(
            {
                "name": name,
                "categoryId": "expert_category_default",
                "abilityIntro": "Runtime orchestration expert.",
                "runtimeConfig": {
                    "codex": {
                        "enabled": True,
                        "model": "gpt-5.5",
                        "permissionMode": "auto_approve",
                    },
                    "opencode": {"enabled": False},
                },
                "knowledgeBaseIds": knowledge_base_ids or [],
                "mcpConnectorIds": mcp_connector_ids or [],
            }
        ),
        request_id="request-create",
    )


def _publication_service(
    connection,
    settings: Settings,
    *,
    acp: FakeAcp | None = None,
    object_store: FakeObjectStore | None = None,
):
    builder = FakeBuilder()
    gateway = FakeGateway()
    mcp_gateway = FakeMcpGateway(gateway)
    service = ExpertPublicationService(
        connection,
        settings,
        skill_storage=FakeSkillStorage(),
        object_store=object_store or FakeObjectStore(),
        builder=builder,
        gateway=gateway,
        mcp_gateway=mcp_gateway,
        acp=acp or FakeAcp(),
    )
    return service, builder, gateway


def test_max_instances_defaults_to_50_and_preserves_explicit_values(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    _prepare_database(settings)
    with open_database_connection(settings) as connection:
        row = connection.execute(
            "select runtime_config from experts where id = '1825107e997dfde2'"
        ).fetchone()
        runtime_config = json.loads(row["runtime_config"])
        runtime_config["codex"]["maxInstances"] = 7
        connection.execute(
            "update experts set runtime_config = ? where id = '1825107e997dfde2'",
            (json.dumps(runtime_config),),
        )

        defaulted = _create_expert(connection, name="Default Capacity")
        assert defaulted.runtimeConfig["codex"].maxInstances == 50
        assert defaulted.runtimeConfig["opencode"].maxInstances == 50

        connection.execute("delete from experts where id = '1825107e997dfde2'")
        fallback = _create_expert(connection, name="Fallback Capacity")
        assert fallback.runtimeConfig["codex"].maxInstances == 50

        service = ExpertService(connection)
        explicit = service.create(
            _principal(),
            CreateExpertRequest.model_validate(
                {
                    "name": "Explicit Capacity",
                    "categoryId": "expert_category_default",
                    "abilityIntro": "Preserves configured capacity.",
                    "runtimeConfig": {"codex": {"enabled": True, "maxInstances": 7}},
                }
            ),
            request_id="request-explicit-capacity",
        )
        assert explicit.runtimeConfig["codex"].maxInstances == 7

        unchanged = service.update(
            _principal(),
            explicit.id,
            UpdateExpertRequest(name="Renamed Capacity"),
            request_id="request-rename-capacity",
        )
        assert unchanged.runtimeConfig["codex"].maxInstances == 7

        defaulted_update = service.update(
            _principal(),
            explicit.id,
            UpdateExpertRequest.model_validate({"runtimeConfig": {"codex": {"enabled": True}}}),
            request_id="request-reset-capacity",
        )
        assert defaulted_update.runtimeConfig["codex"].maxInstances == 50


@pytest.mark.asyncio
async def test_publication_keeps_public_knowledge_out_of_runtime(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    _prepare_database(settings)
    with open_database_connection(settings) as connection:
        connection.execute(
            """
            insert into knowledge_bases (id, owner_user_id, name, status)
            values ('kb_runtime', 'platform_admin', 'Runtime knowledge', 'active')
            """
        )
        connection.commit()
        expert = _create_expert(connection, knowledge_base_ids=["kb_runtime"])
        service, builder, gateway = _publication_service(
            connection,
            settings,
            object_store=FakeObjectStore(),
        )

        await service.change_status(
            _principal(), expert.id, "published", request_id="request-publish"
        )

        assert builder.inputs[0]["knowledge"] == []
        assert builder.inputs[0]["mcpServers"][1:] == [
            {
                "name": "expert_knowledge",
                "enabled": True,
                "transport": "http",
                "url": (
                    "http://127.0.0.1:15000/internal/mcp/knowledge/"
                    f"{expert.id}"
                ),
                "timeoutSeconds": 60,
                "headers": {
                    "Authorization": {
                        "secretRef": "EXPERT_KNOWLEDGE_AUTHORIZATION"
                    }
                },
                "toolAllow": ["search_expert_knowledge"],
                "toolDeny": [],
            }
        ]
        assert "mcp__expert_knowledge__search_expert_knowledge" in builder.inputs[0][
            "instructions"
        ]
        runtime_name = expert_runtime_name("codex", expert.id)
        knowledge_authorization = gateway.services[runtime_name]["env"][
            "EXPERT_KNOWLEDGE_AUTHORIZATION"
        ]
        assert knowledge_authorization.startswith("Bearer kmcp_")
        assert knowledge_authorization not in json.dumps(builder.inputs[0])
        assert service._runtime_knowledge_current(expert, runtime_name)


def test_expert_runtime_name_is_the_only_gateway_identity() -> None:
    expert_id = "1825107e997dfde2"
    assert expert_runtime_name("codex", expert_id) == "expert-codex-1825107e997dfde2"
    assert expert_runtime_name("opencode", expert_id) == "expert-opencode-1825107e997dfde2"
    with pytest.raises(ValueError):
        expert_runtime_name("codex", "expert_legacy")


@pytest.mark.asyncio
async def test_publish_orchestrates_builder_gateway_and_real_turn_before_status(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    _prepare_database(settings)
    with open_database_connection(settings) as connection:
        expert = _create_expert(connection)
        assert re.fullmatch(r"[0-9a-f]{16}", expert.id)
        assert expert.status == "draft"
        assert "expertKey" not in expert.model_dump()
        with pytest.raises(ValidationError):
            CreateExpertRequest.model_validate(
                {
                    "name": "Caller-selected identity",
                    "categoryId": "expert_category_default",
                    "abilityIntro": "Invalid request.",
                    "expertId": "f" * 16,
                    "status": "published",
                }
            )

        service, builder, gateway = _publication_service(connection, settings)
        published = await service.change_status(
            _principal(), expert.id, "published", request_id="request-publish"
        )

        runtime_name = expert_runtime_name("codex", expert.id)
        assert published.status == "published"
        assert builder.inputs[0]["schemaVersion"] == 2
        assert builder.inputs[0]["expertId"] == expert.id
        assert builder.inputs[0]["runtimeType"] == "codex"
        assert "expertKey" not in json.dumps(builder.inputs[0])
        assert "model-route-key" not in json.dumps(builder.inputs[0])
        assert gateway.services[runtime_name]["id"] == runtime_name
        assert gateway.services[runtime_name]["codex"] == {
            "mode": "adapter",
            "adapter_command": "/opt/expert-runtime/codex-acp",
        }
        assert gateway.services[runtime_name]["cwd"] == str(
            Path(settings.acp_cwd_base or "") / ".publication" / runtime_name
        )
        publication_cwd = Path(gateway.services[runtime_name]["cwd"])
        for name in (".git", ".agents", ".codex"):
            mount_target = publication_cwd / name
            assert mount_target.is_dir()
            assert list(mount_target.iterdir()) == []
        assert gateway.services[runtime_name]["allowed_roots"] == [
            str(Path(settings.acp_cwd_base or ""))
        ]
        assert gateway.services[runtime_name]["env"] == {
            "HOME": str(Path(settings.acp_config_base or "") / runtime_name),
            "EXPERT_RUNTIME_CONTRACT_VERSION": "10",
            "EXPERT_LIBRARY_AUTHORIZATION": library_mcp_authorization(settings, expert.id),
            "CODEX_HOME": str(Path(settings.acp_config_base or "") / runtime_name),
            "EXPERT_ACP_SANDBOX_RUNTIME_ROOT": str(Path(settings.acp_config_base or "")),
            "EXPERT_ACP_SANDBOX_WORKSPACE_ROOT": str(Path(settings.acp_cwd_base or "")),
            "EXPERT_ACP_REAL_ADAPTER_COMMAND": "/usr/local/bin/codex-acp",
            "EXPERT_ACP_RUNTIME_ENV_NAMES": (
                "CODEX_HOME EXPERT_ACP_REAL_ADAPTER_COMMAND EXPERT_ACP_SANDBOX_RUNTIME_ROOT "
                "EXPERT_ACP_SANDBOX_WORKSPACE_ROOT EXPERT_LIBRARY_AUTHORIZATION "
                "EXPERT_RUNTIME_CONTRACT_VERSION HOME"
            ),
        }
        assert gateway.services[runtime_name]["permission_mode"] == "auto_approve"
        assert "WinWise platform rules" in builder.inputs[0]["instructions"]
        assert builder.inputs[0]["instructions"].endswith(expert.abilityIntro)
        assert gateway.routes[runtime_name]["id"] == runtime_name
        assert gateway.routes[runtime_name]["service_id"] == runtime_name
        assert gateway.routes[runtime_name]["match_policy"]["path_prefix"] == (
            f"/acp/{runtime_name}"
        )
        assert runtime_name in gateway.allowed_routes
        assert len(gateway.closed_threads) == 1
        closed_service_id, closed_thread_id = gateway.closed_threads[0]
        assert closed_service_id == runtime_name
        assert closed_thread_id.startswith(f"publication-{expert.id}-codex-")
        runtime_home = Path(settings.acp_config_base or "") / runtime_name
        assert (runtime_home / "AGENTS.md").is_file()
        assert (runtime_home / "auth.json").stat().st_mode & 0o777 == 0o600
        assert "OPENAI_API_KEY" not in gateway.services[runtime_name]["env"]

        with pytest.raises(ApiError) as exc_info:
            ExpertService(connection).update(
                _principal(),
                expert.id,
                UpdateExpertRequest(name="Blocked"),
                request_id="request-update",
            )
        assert exc_info.value.code == "EXPERT_PUBLISHED_READ_ONLY"


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid_target", ["symlink", "nonempty"])
async def test_publish_rejects_invalid_publication_sandbox_mount_target(
    tmp_path: Path,
    invalid_target: str,
) -> None:
    settings = _settings(tmp_path)
    _prepare_database(settings)
    with open_database_connection(settings) as connection:
        expert = _create_expert(connection)
        runtime_name = expert_runtime_name("codex", expert.id)
        publication_cwd = (
            Path(settings.acp_cwd_base or "") / ".publication" / runtime_name
        )
        publication_cwd.mkdir(parents=True)
        if invalid_target == "symlink":
            outside = tmp_path / "outside"
            outside.mkdir()
            (publication_cwd / ".git").symlink_to(outside, target_is_directory=True)
        else:
            (publication_cwd / ".git").mkdir()
            (publication_cwd / ".git" / "unexpected").write_text(
                "must not be hidden by the sandbox\n",
                encoding="utf-8",
            )

        service, _, gateway = _publication_service(connection, settings)
        with pytest.raises(ApiError) as exc_info:
            await service.change_status(
                _principal(), expert.id, "published", request_id="request-invalid-cwd"
            )

        assert exc_info.value.code == "ACP_TENANT_CWD_INVALID"
        assert ExpertService(connection).get(expert.id).status == "draft"
        assert runtime_name not in gateway.services
        assert runtime_name not in gateway.routes


@pytest.mark.parametrize(
    ("invalid_target", "expected_error"),
    [
        ("missing", "workspace sandbox mount target is missing: .git"),
        ("symlink", "workspace sandbox mount target is a symbolic link: .git"),
        ("nonempty", "workspace sandbox mount target is not empty: .git"),
    ],
)
def test_codex_adapter_preflight_rejects_invalid_inner_sandbox_mount_target(
    tmp_path: Path,
    invalid_target: str,
    expected_error: str,
) -> None:
    runtime_root = tmp_path / "experts"
    runtime_home = runtime_root / "expert-codex-1825107e997dfde2"
    workspace_root = tmp_path / "tenant-workspaces"
    workspace = workspace_root / "tenant_default"
    node_bin = tmp_path / "node-runtime" / "bin"
    runtime_home.mkdir(parents=True)
    workspace.mkdir(parents=True)
    node_bin.mkdir(parents=True)
    called = tmp_path / "bwrap-called"
    for executable in ("node", "codex-acp"):
        path = node_bin / executable
        path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        path.chmod(0o755)
    fake_bwrap = node_bin / "bwrap"
    fake_bwrap.write_text('#!/bin/sh\n: > "$BWRAP_CALLED"\n', encoding="utf-8")
    fake_bwrap.chmod(0o755)

    if invalid_target == "symlink":
        outside = tmp_path / "outside"
        outside.mkdir()
        (workspace / ".git").symlink_to(outside, target_is_directory=True)
    elif invalid_target == "nonempty":
        (workspace / ".git").mkdir()
        (workspace / ".git" / "unexpected").write_text("data\n", encoding="utf-8")
    for name in (".agents", ".codex"):
        (workspace / name).mkdir()

    wrapper = Path(__file__).resolve().parents[1] / "runtime" / "codex-acp"
    result = subprocess.run(
        ["bash", str(wrapper)],
        cwd=workspace,
        env={
            "BWRAP_CALLED": str(called),
            "CODEX_HOME": str(runtime_home),
            "EXPERT_ACP_REAL_ADAPTER_COMMAND": str(node_bin / "codex-acp"),
            "EXPERT_ACP_SANDBOX_RUNTIME_ROOT": str(runtime_root),
            "EXPERT_ACP_SANDBOX_WORKSPACE_ROOT": str(workspace_root),
            "HOME": str(runtime_home),
            "PATH": f"{node_bin}:/usr/bin:/bin",
        },
        capture_output=True,
        check=False,
        text=True,
    )

    assert result.returncode == 70
    assert expected_error in result.stderr
    assert not called.exists()


def test_codex_adapter_does_not_rebind_system_usr_over_sandbox_tree() -> None:
    wrapper = (
        Path(__file__).resolve().parents[1] / "runtime" / "codex-acp"
    ).read_text(encoding="utf-8")

    assert 'node_runtime_bind=()' in wrapper
    assert 'if [[ "$node_root" != /usr ]]; then' in wrapper
    assert 'node_runtime_bind=(--ro-bind "$node_root" "$node_root")' in wrapper
    assert '  "${node_runtime_bind[@]}"' in wrapper
    assert '\n  --ro-bind "$node_root" "$node_root"\n' not in wrapper


def test_bundled_codex_adapter_is_executable() -> None:
    wrapper = Path(__file__).resolve().parents[1] / "runtime" / "codex-acp"

    assert wrapper.is_file()
    assert os.access(wrapper, os.X_OK)


@pytest.mark.asyncio
async def test_published_runtime_reconcile_repairs_after_failed_smoke(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    _prepare_database(settings)
    with open_database_connection(settings) as connection:
        expert = _create_expert(connection)
        acp = FakeAcp()
        service, builder, _ = _publication_service(connection, settings, acp=acp)
        await service.change_status(
            _principal(), expert.id, "published", request_id="request-publish"
        )

        repaired = await service.reconcile_published(
            expert.id,
            principal=_principal(),
            request_id="request-reconcile-check",
        )
        assert repaired is False
        assert len(acp.calls) == 2
        assert len(builder.inputs) == 1

        acp.fail_smokes = 1
        builder.status_reader = lambda: ExpertService(connection).get(expert.id).status
        repaired = await service.reconcile_published(
            expert.id,
            principal=_principal(),
            request_id="request-startup-reconcile",
        )

        assert repaired is True
        assert ExpertService(connection).get(expert.id).status == "published"
        assert len(builder.inputs) == 2
        assert builder.observed_statuses == ["unlisted"]


@pytest.mark.asyncio
async def test_startup_reconcile_recreates_missing_publication_sandbox_mount_target(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    _prepare_database(settings)
    with open_database_connection(settings) as connection:
        expert = _create_expert(connection)
        service, builder, _ = _publication_service(connection, settings)
        await service.change_status(
            _principal(), expert.id, "published", request_id="request-publish"
        )
        runtime_name = expert_runtime_name("codex", expert.id)
        missing_target = (
            Path(settings.acp_cwd_base or "")
            / ".publication"
            / runtime_name
            / ".git"
        )
        missing_target.rmdir()

        repaired = await service.reconcile_published(
            expert.id,
            principal=_principal(),
            request_id="request-startup-reconcile-mount-target",
        )

        assert repaired is False
        assert missing_target.is_dir()
        assert list(missing_target.iterdir()) == []
        assert len(builder.inputs) == 1


@pytest.mark.asyncio
async def test_published_runtime_reconcile_accepts_normalized_empty_config_overrides(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    _prepare_database(settings)
    with open_database_connection(settings) as connection:
        expert = _create_expert(connection)
        service, builder, gateway = _publication_service(connection, settings)
        await service.change_status(
            _principal(), expert.id, "published", request_id="request-publish"
        )
        runtime_name = expert_runtime_name("codex", expert.id)
        gateway.services[runtime_name]["config_overrides"] = None

        repaired = await service.reconcile_published(
            expert.id,
            principal=_principal(),
            request_id="request-reconcile-normalized-empty-overrides",
        )

        assert repaired is False
        assert ExpertService(connection).get(expert.id).status == "published"
        assert len(builder.inputs) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "drift",
    [
        "adapter",
        "sandbox_env",
        "service_config",
        "config_overrides",
        "contract_version",
        "missing_route",
        "missing_layout",
        "invalid_layout_type",
        "legacy_codex_config",
        "approval_policy",
        "project_docs",
        "platform_instructions",
    ],
)
async def test_published_runtime_reconcile_repairs_service_configuration_drift(
    tmp_path: Path,
    drift: str,
) -> None:
    settings = _settings(tmp_path)
    _prepare_database(settings)
    with open_database_connection(settings) as connection:
        expert = _create_expert(connection)
        service, builder, gateway = _publication_service(connection, settings)
        await service.change_status(
            _principal(), expert.id, "published", request_id="request-publish"
        )
        runtime_name = expert_runtime_name("codex", expert.id)
        if drift == "adapter":
            gateway.services[runtime_name]["codex"]["adapter_command"] = "codex-acp"
        elif drift == "sandbox_env":
            gateway.services[runtime_name]["env"][
                "EXPERT_ACP_SANDBOX_WORKSPACE_ROOT"
            ] = "/wrong/workspace"
        elif drift == "service_config":
            gateway.services[runtime_name]["max_instances"] += 1
        elif drift == "config_overrides":
            gateway.services[runtime_name]["config_overrides"] = {
                "thought_level": "high"
            }
        elif drift == "contract_version":
            gateway.services[runtime_name]["env"]["EXPERT_RUNTIME_CONTRACT_VERSION"] = "1"
        elif drift == "missing_route":
            gateway.routes.pop(runtime_name)
        elif drift == "missing_layout":
            (Path(settings.acp_config_base or "") / runtime_name / "config.toml").unlink()
        elif drift == "invalid_layout_type":
            config_path = Path(settings.acp_config_base or "") / runtime_name / "config.toml"
            config_path.unlink()
            config_path.mkdir()
        elif drift in {"project_docs", "platform_instructions"}:
            config_path = Path(settings.acp_config_base or "") / runtime_name / "config.toml"
            config_path.write_text(
                config_path.read_text().replace(
                    'project_doc_max_bytes = 0' if drift == "project_docs" else 'developer_instructions',
                    'project_doc_max_bytes = 32768' if drift == "project_docs" else 'removed_instructions',
                ),
                encoding="utf-8",
            )
        elif drift == "approval_policy":
            config_path = Path(settings.acp_config_base or "") / runtime_name / "config.toml"
            config_path.write_text(
                config_path.read_text().replace('approval_policy = "never"',
                                                'approval_policy = "on-request"'),
                encoding="utf-8",
            )
        else:
            (Path(settings.acp_config_base or "") / runtime_name / "config.toml").write_text(
                'sandbox_mode = "workspace-write"\n',
                encoding="utf-8",
            )

        repaired = await service.reconcile_published(
            expert.id,
            principal=_principal(),
            request_id="request-reconcile-drift",
        )

        assert repaired is True
        assert ExpertService(connection).get(expert.id).status == "published"
        assert len(builder.inputs) == 2
        assert gateway.services[runtime_name]["codex"]["adapter_command"] == (
            "/opt/expert-runtime/codex-acp"
        )
        assert gateway.services[runtime_name]["env"][
            "EXPERT_ACP_SANDBOX_WORKSPACE_ROOT"
        ] == str(Path(settings.acp_cwd_base or ""))
        assert gateway.services[runtime_name]["env"]["EXPERT_RUNTIME_CONTRACT_VERSION"] == "10"
        assert gateway.routes[runtime_name]["disabled"] is False
        assert (Path(settings.acp_config_base or "") / runtime_name / "config.toml").is_file()


@pytest.mark.asyncio
async def test_runtime_smoke_timeout_fails_closed_and_disables_resources(tmp_path: Path) -> None:
    class HangingAcp(FakeAcp):
        def stream_turn(self, **kwargs: Any):
            async def events():
                await asyncio.Event().wait()
                yield ""  # pragma: no cover - makes this an async generator

            return events()

    settings = _settings(tmp_path)
    settings.runtime_operation_timeout_seconds = 0.01
    _prepare_database(settings)
    with open_database_connection(settings) as connection:
        expert = _create_expert(connection)
        service, _, gateway = _publication_service(connection, settings)
        await service.change_status(
            _principal(), expert.id, "published", request_id="request-publish"
        )
        service.acp = HangingAcp()

        with pytest.raises(ApiError) as exc_info:
            await service.reconcile_published(
                expert.id,
                principal=_principal(),
                request_id="request-timeout-reconcile",
            )

        assert exc_info.value.code == "EXPERT_RUNTIME_SMOKE_TIMEOUT"
        assert ExpertService(connection).get(expert.id).status == "unlisted"
        runtime_name = expert_runtime_name("codex", expert.id)
        assert gateway.services[runtime_name]["disabled"] is True
        assert gateway.routes[runtime_name]["disabled"] is True


@pytest.mark.asyncio
async def test_failed_runtime_repair_leaves_expert_unlisted(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    _prepare_database(settings)
    with open_database_connection(settings) as connection:
        expert = _create_expert(connection)
        acp = FakeAcp()
        service, _, gateway = _publication_service(connection, settings, acp=acp)
        await service.change_status(
            _principal(), expert.id, "published", request_id="request-publish"
        )
        acp.pass_smoke = False

        with pytest.raises(ApiError) as exc_info:
            await service.reconcile_published(
                expert.id,
                principal=_principal(),
                request_id="request-startup-reconcile",
            )

        assert exc_info.value.code == "EXPERT_RUNTIME_SMOKE_FAILED"
        assert ExpertService(connection).get(expert.id).status == "unlisted"
        runtime_name = expert_runtime_name("codex", expert.id)
        assert gateway.services[runtime_name]["disabled"] is True
        assert gateway.routes[runtime_name]["disabled"] is True


@pytest.mark.asyncio
async def test_fail_closed_attempts_service_when_route_disable_fails(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    _prepare_database(settings)
    with open_database_connection(settings) as connection:
        expert = _create_expert(connection)
        service, _, gateway = _publication_service(connection, settings)
        await service.change_status(
            _principal(), expert.id, "published", request_id="request-publish"
        )
        runtime_name = expert_runtime_name("codex", expert.id)
        gateway.disable_route_errors.add(runtime_name)

        with pytest.raises(ApiError) as exc_info:
            await service.fail_closed_runtime(expert.id)

        assert exc_info.value.code == "EXPERT_RUNTIME_FAIL_CLOSED_FAILED"
        assert gateway.services[runtime_name]["disabled"] is True
        assert gateway.routes[runtime_name]["disabled"] is False
        assert ("route", runtime_name) in gateway.disable_attempts
        assert ("service", runtime_name) in gateway.disable_attempts


@pytest.mark.asyncio
async def test_startup_reconcile_rolls_back_failure_fails_closed_and_continues(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings(tmp_path)
    _prepare_database(settings)
    with open_database_connection(settings) as connection:
        failed = _create_expert(connection, name="Failed startup Expert")
        healthy = _create_expert(connection, name="Healthy startup Expert")
        connection.execute(
            """
            insert into platform_user_roles (id, user_id, role)
            values ('role_runtime_admin', 'platform_admin', 'admin')
            """
        )
        repository = ExpertRepository(connection)
        repository.update_status(failed.id, "published")
        repository.update_status(healthy.id, "published")
        connection.commit()

    calls: list[str] = []

    async def reconcile(
        service: ExpertPublicationService,
        expert_id: str,
        **_: Any,
    ) -> bool:
        calls.append(expert_id)
        if expert_id == failed.id:
            service.connection.execute(
                "update experts set name = 'uncommitted' where id = ?",
                (expert_id,),
            )
            raise RuntimeError("unexpected per-Expert failure")
        return False

    monkeypatch.setattr(ExpertPublicationService, "reconcile_published", reconcile)

    fail_closed_calls: list[str] = []

    async def fail_closed_runtime(
        _: ExpertPublicationService,
        expert_id: str,
    ) -> None:
        fail_closed_calls.append(expert_id)

    monkeypatch.setattr(
        ExpertPublicationService,
        "fail_closed_runtime",
        fail_closed_runtime,
    )

    summary = await reconcile_published_experts(settings)

    items = {item.expert_id: item for item in summary.items}
    assert set(calls) == {failed.id, healthy.id}
    assert fail_closed_calls == [failed.id]
    assert items[failed.id].outcome == "failed"
    assert items[failed.id].expert_status == "unlisted"
    assert items[healthy.id].outcome == "healthy"
    with open_database_connection(settings) as connection:
        failed_after = ExpertService(connection).get(failed.id)
        assert failed_after.status == "unlisted"
        assert failed_after.name == "Failed startup Expert"
        assert ExpertService(connection).get(healthy.id).status == "published"


@pytest.mark.asyncio
async def test_mcp_connector_is_shared_by_all_runtimes_and_not_rechecked_before_chat(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    _prepare_database(settings)
    with open_database_connection(settings) as connection:
        expert = _create_expert(
            connection,
            mcp_connector_ids=["local_test"],
        )
        expert = ExpertService(connection).update(
            _principal(),
            expert.id,
            UpdateExpertRequest(
                runtimeConfig={
                    "codex": {
                        "enabled": True,
                        "model": "gpt-5.5",
                        "permissionMode": "auto_approve",
                    },
                    "opencode": {
                        "enabled": True,
                        "model": "gpt-5.5",
                        "permissionMode": "auto_approve",
                    },
                }
            ),
            request_id="request-enable-two-runtimes",
        )
        builder = FakeBuilder()
        gateway = FakeGateway()
        mcp_gateway = FakeMcpGateway(gateway)
        publication = ExpertPublicationService(
            connection,
            settings,
            skill_storage=FakeSkillStorage(),
            object_store=FakeObjectStore(),
            builder=builder,
            gateway=gateway,
            mcp_gateway=mcp_gateway,
            acp=FakeAcp(),
        )

        published = await publication.change_status(
            _principal(), expert.id, "published", request_id="request-publish-mcp"
        )

        assert published.status == "published"
        connector_hash = hashlib.sha256(b"local_test").hexdigest()[:16]
        route_id = f"mcp-connector-{connector_hash}"
        route_path = f"/mcp/connectors/{connector_hash}"
        expected_server = {
            "name": f"connector_{connector_hash}",
            "enabled": True,
            "transport": "http",
            "url": f"http://127.0.0.1:8080{route_path}",
            "timeoutSeconds": 60,
            "headers": {
                "Authorization": {"secretRef": "EXPERT_MCP_AUTHORIZATION"}
            },
            "toolAllow": ["check_product_mcp", "check_policy_mcp"],
            "toolDeny": [],
        }
        assert builder.inputs[0]["mcpServers"][1:] == [expected_server]
        assert builder.inputs[1]["mcpServers"][1:] == [expected_server]
        expected_inventory = (
            "## Managed MCP capability inventory\n\n"
            "MCP connectors expose callable tools. These are separate from MCP resources and "
            "resource templates, so an empty resources/templates listing does not mean the "
            "tools below are unavailable.\n"
            "When asked which MCP services or tools are available, report this managed "
            "inventory. Use the matching fully qualified namespaced MCP function for requests "
            "that need it; never emit the bare tool name as an unnamespaced function call, and "
            "do not use resource listing as a substitute for this inventory.\n\n"
            '- Service "Local MCP test" (id "local_test"): tools '
            '"check_product_mcp" (call as '
            f'"mcp__connector_{connector_hash}__check_product_mcp"), '
            '"check_policy_mcp" (call as '
            f'"mcp__connector_{connector_hash}__check_policy_mcp")'
        )
        assert builder.inputs[0]["instructions"].endswith(expected_inventory)
        assert builder.inputs[1]["instructions"].endswith(expected_inventory)
        assert "mcp-route-access-key" not in json.dumps(builder.inputs)
        assert gateway.mcp_initializations == ["local_test"]
        assert gateway.mcp_routes[route_id].service_id == "local_test"
        assert gateway.mcp_routes[route_id].auth_policy.require_virtual_key is True
        mcp_key = gateway.virtual_keys[f"mcp-key-{expert.id}"]
        assert mcp_key.allowed_route_ids == [route_id]
        assert mcp_gateway.initialized_paths == [route_path]
        assert mcp_gateway.listed_paths == [route_path]
        assert [item["runtimeType"] for item in builder.inputs] == ["codex", "opencode"]
        for runtime_type in ("codex", "opencode"):
            runtime_name = expert_runtime_name(runtime_type, expert.id)
            assert gateway.services[runtime_name]["env"]["EXPERT_MCP_AUTHORIZATION"] == (
                "Bearer mcp-route-access-key"
            )
        chat = ChatService(connection, acp=FakeAcp())
        session = await chat.create_session(
            _principal(),
            CreateSessionRequest(expertId=expert.id, runtimeType="codex"),
        )
        chat.validate_turn_preconditions(_principal(), session.id, ChatTurnRequest(question="test"))
        assert gateway.mcp_initializations == ["local_test"]


@pytest.mark.asyncio
async def test_publication_smoke_accepts_persisted_transcript_after_tool_turn(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    _prepare_database(settings)
    with open_database_connection(settings) as connection:
        expert = _create_expert(connection)
        service, _, gateway = _publication_service(
            connection,
            settings,
            acp=FakeAcp(marker_only_in_transcript=True),
        )

        published = await service.change_status(
            _principal(), expert.id, "published", request_id="request-publish-transcript"
        )

        assert published.status == "published"
        assert len(gateway.closed_threads) == 1


@pytest.mark.asyncio
async def test_failed_real_turn_keeps_status_and_disables_created_gateway_resources(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    _prepare_database(settings)
    with open_database_connection(settings) as connection:
        expert = _create_expert(connection, mcp_connector_ids=["local_test"])
        service, _, gateway = _publication_service(
            connection, settings, acp=FakeAcp(pass_smoke=False)
        )

        with pytest.raises(ApiError) as exc_info:
            await service.change_status(
                _principal(), expert.id, "published", request_id="request-publish"
            )
        assert exc_info.value.code == "EXPERT_RUNTIME_SMOKE_FAILED"
        assert ExpertService(connection).get(expert.id).status == "draft"
        runtime_name = expert_runtime_name("codex", expert.id)
        assert gateway.services[runtime_name]["disabled"] is True
        assert gateway.routes[runtime_name]["disabled"] is True
        assert gateway.virtual_keys[f"mcp-key-{expert.id}"].disabled is True
        assert len(gateway.closed_threads) == 1
        assert gateway.closed_threads[0][0] == runtime_name


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("failure", "expected_code"),
    [
        ("missing", "EXPERT_MCP_CONNECTOR_NOT_FOUND"),
        ("disabled", "EXPERT_MCP_CONNECTOR_DISABLED"),
        ("no_tools", "EXPERT_MCP_CONNECTOR_NO_TOOLS"),
    ],
)
async def test_invalid_mcp_connector_blocks_publication_before_builder(
    tmp_path: Path,
    failure: str,
    expected_code: str,
) -> None:
    settings = _settings(tmp_path)
    _prepare_database(settings)
    with open_database_connection(settings) as connection:
        expert = _create_expert(connection, mcp_connector_ids=["local_test"])
        service, builder, gateway = _publication_service(connection, settings)
        if failure == "missing":
            gateway.mcp_services.clear()
        elif failure == "disabled":
            gateway.mcp_services["local_test"].disabled = True
        else:
            gateway.mcp_tools["local_test"] = []

        with pytest.raises(ApiError) as exc_info:
            await service.change_status(
                _principal(),
                expert.id,
                "published",
                request_id="request-invalid-connector",
            )

        assert exc_info.value.code == expected_code
        assert builder.inputs == []
        assert ExpertService(connection).get(expert.id).status == "draft"


@pytest.mark.asyncio
async def test_opencode_uses_the_local_gateway_key_environment_contract(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    _prepare_database(settings)
    with open_database_connection(settings) as connection:
        expert = _create_expert(connection, mcp_connector_ids=["local_test"])
        expert = ExpertService(connection).update(
            _principal(),
            expert.id,
            UpdateExpertRequest(
                runtimeConfig={
                    "codex": {"enabled": False},
                    "opencode": {
                        "enabled": True,
                        "model": "gpt-5.5",
                        "permissionMode": "auto_approve",
                    },
                }
            ),
            request_id="request-enable-opencode",
        )
        service, builder, gateway = _publication_service(connection, settings)

        await service.change_status(
            _principal(), expert.id, "published", request_id="request-publish"
        )

        runtime_name = expert_runtime_name("opencode", expert.id)
        assert builder.inputs[0]["runtimeType"] == "opencode"
        assert builder.inputs[0]["modelGateway"]["requiresAuth"] is True
        assert "model-route-key" not in json.dumps(builder.inputs[0])
        assert gateway.services[runtime_name]["env"]["AGENT_GATEWAY_API_KEY"] == ("model-route-key")
        assert "OPENAI_API_KEY" not in gateway.services[runtime_name]["env"]


@pytest.mark.asyncio
async def test_unlist_edit_republish_preserves_runtime_home_and_chat_route(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    _prepare_database(settings)
    principal = _principal()
    with open_database_connection(settings) as connection:
        expert = _create_expert(connection, mcp_connector_ids=["local_test"])
        acp = FakeAcp()
        service, _, gateway = _publication_service(connection, settings, acp=acp)
        await service.change_status(principal, expert.id, "published", request_id="request-publish")
        chat = ChatService(connection, acp=acp)  # type: ignore[arg-type]
        session = await chat.create_session(
            principal,
            CreateSessionRequest(
                title="Preserved runtime session",
                expertId=expert.id,
                runtimeType="codex",
            ),
        )
        runtime_name = expert_runtime_name("codex", expert.id)
        runtime_home = Path(settings.acp_config_base or "") / runtime_name
        (runtime_home / "sessions").mkdir()
        (runtime_home / "sessions/keep.txt").write_text("state", encoding="utf-8")

        first_marker = "ORIGINAL_SESSION_BEFORE_UNLIST"
        first_request = ChatTurnRequest(question=first_marker)
        first_turn_id = chat.reserve_turn(principal, session.id, first_request)
        first_events = "".join(
            [
                event
                async for event in chat.stream_turn(
                    principal,
                    session.id,
                    first_request,
                    turn_id=first_turn_id,
                )
            ]
        )
        assert first_marker in first_events
        assert "event: turn_completed" in first_events
        first_row = chat.repo.get_session_row("tenant_default", "platform_admin", session.id)
        assert first_row is not None
        original_acp_session_id = first_row["acp_session_id"]
        assert original_acp_session_id == "acp_session_preserved"

        await service.change_status(principal, expert.id, "unlisted", request_id="request-unlist")
        assert gateway.services[runtime_name]["disabled"] is True
        assert gateway.routes[runtime_name]["disabled"] is True
        assert gateway.virtual_keys[f"mcp-key-{expert.id}"].disabled is True
        ExpertService(connection).update(
            principal,
            expert.id,
            UpdateExpertRequest(name="Updated Runtime Expert"),
            request_id="request-update",
        )
        await service.change_status(
            principal, expert.id, "published", request_id="request-republish"
        )

        second_marker = "ORIGINAL_SESSION_AFTER_REPUBLISH"
        second_request = ChatTurnRequest(question=second_marker)
        second_turn_id = chat.reserve_turn(principal, session.id, second_request)
        second_events = "".join(
            [
                event
                async for event in chat.stream_turn(
                    principal,
                    session.id,
                    second_request,
                    turn_id=second_turn_id,
                )
            ]
        )
        assert second_marker in second_events
        assert "event: turn_completed" in second_events

        row = chat.repo.get_session_row("tenant_default", "platform_admin", session.id)
        assert row is not None
        assert row["acp_session_id"] == original_acp_session_id
        assert chat._acp_route(row, False).route_prefix == f"/acp/{runtime_name}"
        assert (runtime_home / "sessions/keep.txt").read_text(encoding="utf-8") == "state"
        chat_calls = [call for call in acp.calls if call["input"].split("\n\n", 1)[0] in {first_marker, second_marker}]
        assert [call["input"].split("\n\n", 1)[0] for call in chat_calls] == [first_marker, second_marker]
        assert {call["thread_id"] for call in chat_calls} == {f"{session.id}:no_search"}
        assert chat_calls[0]["session_id"] is None
        assert chat_calls[1]["session_id"] == original_acp_session_id
        assert {call["route_prefix"] for call in chat_calls} == {f"/acp/{runtime_name}"}


@pytest.mark.asyncio
async def test_empty_default_cwd_is_omitted_from_acp_turn(tmp_path: Path) -> None:
    settings = Settings(
        acp_gateway_base_url="http://127.0.0.1:8080",
        acp_default_cwd="",
    )
    acp = AcpGatewayClient(settings)
    captured: dict[str, Any] = {}

    async def fake_stream(method: str, path: str, **kwargs: Any):
        captured.update(kwargs["json"])
        yield ""

    acp.stream = fake_stream  # type: ignore[method-assign]
    assert acp.prepare_default_cwd() is None
    async for _ in acp.stream_turn(thread_id="thread", input="hello", cwd=None):
        pass
    assert "cwd" not in captured
    assert str(Path.cwd()) not in captured.values()


@pytest.mark.asyncio
async def test_builder_process_uses_the_v2_argument_contract(tmp_path: Path) -> None:
    executable = tmp_path / "experts-builder"
    executable.write_text(
        """#!/usr/bin/env python3
import json
import pathlib
import sys

args = sys.argv[1:]
assert args[0] == "build"
values = {args[index]: args[index + 1] for index in range(1, len(args), 2)}
source = json.loads(pathlib.Path(values["--input"]).read_text(encoding="utf-8"))
output = pathlib.Path(values["--output"])
print(json.dumps({
    "status": "passed",
    "expertId": source["expertId"],
    "runtimeType": source["runtimeType"],
    "output": str(output.resolve()),
}))
""",
        encoding="utf-8",
    )
    executable.chmod(executable.stat().st_mode | stat.S_IXUSR)
    input_path = tmp_path / "build-input.json"
    input_path.write_text(
        json.dumps({"expertId": "1825107e997dfde2", "runtimeType": "codex"}),
        encoding="utf-8",
    )
    assets = tmp_path / "assets"
    output = tmp_path / "generated"
    assets.mkdir()
    output.mkdir()
    process = BuilderProcess(Settings(builder_executable=str(executable)))

    result = await process.build(
        input_path=input_path,
        assets_dir=assets,
        output_dir=output,
        expert_id="1825107e997dfde2",
        runtime_type="codex",
    )

    assert result["status"] == "passed"


@pytest.mark.asyncio
async def test_builder_process_does_not_expose_stderr(tmp_path: Path) -> None:
    executable = tmp_path / "experts-builder"
    executable.write_text(
        "#!/bin/sh\nprintf 'credential=must-not-leak\\n' >&2\nexit 17\n",
        encoding="utf-8",
    )
    executable.chmod(executable.stat().st_mode | stat.S_IXUSR)
    input_path = tmp_path / "build-input.json"
    input_path.write_text("{}\n", encoding="utf-8")
    assets = tmp_path / "assets"
    output = tmp_path / "generated"
    assets.mkdir()
    output.mkdir()
    process = BuilderProcess(Settings(builder_executable=str(executable)))

    with pytest.raises(ApiError) as exc_info:
        await process.build(
            input_path=input_path,
            assets_dir=assets,
            output_dir=output,
            expert_id="1825107e997dfde2",
            runtime_type="codex",
        )

    assert exc_info.value.code == "EXPERT_BUILDER_FAILED"
    assert exc_info.value.details == {"runtimeType": "codex", "exitCode": 17}
    assert "must-not-leak" not in str(exc_info.value)


@pytest.mark.asyncio
async def test_builder_process_timeout_terminates_the_child(tmp_path: Path) -> None:
    executable = tmp_path / "experts-builder"
    executable.write_text("#!/bin/sh\nsleep 5\n", encoding="utf-8")
    executable.chmod(executable.stat().st_mode | stat.S_IXUSR)
    input_path = tmp_path / "build-input.json"
    input_path.write_text("{}\n", encoding="utf-8")
    assets = tmp_path / "assets"
    output = tmp_path / "generated"
    assets.mkdir()
    output.mkdir()
    process = BuilderProcess(
        Settings(
            builder_executable=str(executable),
            runtime_operation_timeout_seconds=0.01,
        )
    )

    with pytest.raises(ApiError) as exc_info:
        await process.build(
            input_path=input_path,
            assets_dir=assets,
            output_dir=output,
            expert_id="1825107e997dfde2",
            runtime_type="codex",
        )

    assert exc_info.value.code == "EXPERT_BUILDER_TIMEOUT"


@pytest.mark.parametrize("field", ["acp_config_base", "acp_cwd_base"])
def test_runtime_roots_reject_the_filesystem_root(field: str) -> None:
    with pytest.raises(ValidationError, match="absolute non-root paths"):
        Settings(**{field: "/"})


def test_tenant_workspace_rejects_reserved_publication_segment(tmp_path: Path) -> None:
    client = AcpGatewayClient(Settings(acp_cwd_base=str(tmp_path / "workspaces")))

    with pytest.raises(ApiError) as exc_info:
        client.prepare_tenant_cwd(".publication")

    assert exc_info.value.code == "ACP_TENANT_CWD_INVALID"


@pytest.mark.asyncio
async def test_gateway_service_readback_accepts_normalized_empty_config_overrides() -> None:
    client = GatewayAdminClient(Settings(acp_gateway_admin_url="http://127.0.0.1:8019"))

    async def get_service(_: str) -> dict[str, Any]:
        return {
            "id": "expert-codex-1825107e997dfde2",
            "config_overrides": None,
        }

    client.get_service = get_service  # type: ignore[method-assign]
    await client.assert_service(
        {
            "id": "expert-codex-1825107e997dfde2",
            "config_overrides": {},
        }
    )


@pytest.mark.asyncio
async def test_gateway_virtual_key_must_match_the_persistent_backend_token() -> None:
    client = GatewayAdminClient(
        Settings(
            acp_gateway_admin_url="http://127.0.0.1:8019",
            acp_auth_token="persistent-token",
        )
    )
    current = {
        "id": "backend-acp-local",
        "tag": "local-backend",
        "key": "persistent-token",
        "allowed_route_ids": ["existing-route"],
    }

    async def request(method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        if method == "PUT":
            current["allowed_route_ids"] = list(kwargs["json"]["allowed_route_ids"])
        return dict(current)

    client._request = request  # type: ignore[method-assign]
    await client.add_virtual_key_route("backend-acp-local", "expert-codex-1825107e997dfde2")
    assert current["allowed_route_ids"] == [
        "existing-route",
        "expert-codex-1825107e997dfde2",
    ]

    current["key"] = "different-token"
    with pytest.raises(ApiError) as exc_info:
        await client.add_virtual_key_route("backend-acp-local", "expert-codex-1825107e997dfde2")
    assert exc_info.value.code == "EXPERT_ACP_VIRTUAL_KEY_MISMATCH"


@pytest.mark.asyncio
async def test_gateway_admin_closes_the_publication_thread() -> None:
    client = GatewayAdminClient(Settings(acp_gateway_admin_url="http://127.0.0.1:8019"))
    calls: list[tuple[str, str]] = []

    async def request(method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        calls.append((method, path))
        return {"closed": 1}

    client._request = request  # type: ignore[method-assign]
    closed = await client.close_acp_thread(
        "expert-codex-1825107e997dfde2",
        "publication/with spaces",
    )

    assert closed == 1
    assert calls == [
        (
            "DELETE",
            "/admin/acp/runtime/threads/expert-codex-1825107e997dfde2/"
            "publication%2Fwith%20spaces",
        )
    ]


@pytest.mark.asyncio
async def test_gateway_acp_upsert_uses_collection_when_legacy_item_read_is_missing() -> None:
    client = GatewayAdminClient(Settings(acp_gateway_admin_url="http://127.0.0.1:8019"))
    route = {
        "id": "expert-codex-1825107e997dfde2",
        "kind": "acp",
        "protocol": "acp",
        "service_id": "expert-codex-1825107e997dfde2",
    }
    calls: list[tuple[str, str]] = []

    async def request(
        method: str,
        path: str,
        *,
        allow_not_found: bool = False,
        **kwargs: Any,
    ) -> dict[str, Any] | None:
        calls.append((method, path))
        if method == "GET" and path.endswith(route["id"]):
            assert allow_not_found is True
            return None
        if method == "GET" and path == "/admin/acp/routes":
            return {"items": [route]}
        if method == "PUT" and path.endswith(route["id"]):
            return dict(kwargs["json"])
        if method == "POST":
            raise AssertionError("Existing legacy route must not be inserted again")
        raise AssertionError((method, path))

    client._request = request  # type: ignore[method-assign]
    actual = await client.upsert_route(route)

    assert actual == route
    assert calls == [
        ("GET", "/admin/acp/routes/expert-codex-1825107e997dfde2"),
        ("GET", "/admin/acp/routes"),
        ("PUT", "/admin/acp/routes/expert-codex-1825107e997dfde2"),
    ]
