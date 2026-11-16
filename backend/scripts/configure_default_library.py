"""Configure personal Library MCP on existing default Codex services, preserving Skills."""
from __future__ import annotations

import argparse
import asyncio
import copy
import json
import os
from pathlib import Path

from app.clients.gateway_admin import GatewayAdminClient
from app.core.config import Settings
from app.services.library_mcp_service import (
    DEFAULT_LIBRARY_RUNTIME_ID,
    LIBRARY_MCP_AUTHORIZATION_SECRET_REF,
    library_mcp_authorization,
)


def configure_service(service: dict, settings: Settings, model_provider: str) -> dict:
    """Use adapter overrides; never rewrite the shared Codex Home or its Skills."""
    result = copy.deepcopy(service)
    codex = result.get("codex") or {}
    if result.get("agent_type") != "codex" or codex.get("mode", "adapter") != "adapter":
        raise ValueError("Default service must use the Codex ACP adapter")
    if not settings.mcp_model_compat_base_url:
        raise ValueError("EXPERT_MCP_MODEL_COMPAT_BASE_URL is required for namespace tools")
    base = settings.knowledge_mcp_base_url.removesuffix("/knowledge")
    overrides = {
        "mcp_servers.personal_library": (
            '{url = ' + json.dumps(base + "/library/" + DEFAULT_LIBRARY_RUNTIME_ID)
            + ', env_http_headers = {Authorization = "EXPERT_LIBRARY_AUTHORIZATION"}'
            + ', enabled_tools = ["find_personal_file", "read_personal_file"]}'
        ),
        f"model_providers.{model_provider}.base_url": json.dumps(settings.mcp_model_compat_base_url),
    }
    args = list(codex.get("adapter_args") or [])
    kept: list[str] = []
    i = 0
    while i < len(args):
        if args[i] in ("-c", "--config") and i + 1 < len(args):
            key = args[i + 1].split("=", 1)[0].strip()
            if key in overrides:
                i += 2
                continue
        kept.append(args[i])
        i += 1
    for key, value in overrides.items():
        kept.extend(["-c", f"{key}={value}"])
    codex["adapter_args"] = kept
    result["codex"] = codex
    result.setdefault("env", {})[LIBRARY_MCP_AUTHORIZATION_SECRET_REF] = library_mcp_authorization(
        settings, DEFAULT_LIBRARY_RUNTIME_ID
    )
    for field in ("source", "read_only", "created_at", "updated_at"):
        result.pop(field, None)
    return result


async def run(args: argparse.Namespace) -> None:
    settings = Settings()
    gateway = GatewayAdminClient(settings)
    routes = await gateway._request("GET", "/admin/acp/routes")
    prefixes = {settings.acp_route_prefix, settings.acp_search_route_prefix} - {None, ""}
    selected = [r for r in routes.get("items", [])
                if r.get("match_policy", {}).get("path_prefix") in prefixes]
    if {r["match_policy"]["path_prefix"] for r in selected} != prefixes:
        raise ValueError("Every configured default route must exist")
    originals, updates = [], []
    for service_id in sorted({r["service_id"] for r in selected}):
        service = await gateway.get_service(service_id)
        if service is None or service.get("read_only"):
            raise ValueError("Default service must be present and writable")
        originals.append(service)
        updates.append(configure_service(service, settings, args.model_provider))
    print(json.dumps({"mode": "apply" if args.apply else "dry-run",
                      "services": [s["id"] for s in updates],
                      "changes": ["personal_library MCP", "namespace model URL", "service credential"],
                      "preserved": ["HOME", "CODEX_HOME", "Skills", "cwd", "model", "other MCP"]}))
    if not args.apply:
        return
    if not args.backup or not args.backup.is_absolute():
        raise ValueError("--apply requires an absolute --backup path")
    fd = os.open(args.backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as output:
        json.dump(originals, output)
    for update in updates:
        await gateway.upsert_service(update)
        actual = await gateway.get_service(update["id"])
        if actual is None or actual.get("codex") != update["codex"] or actual.get("env") != update["env"]:
            raise RuntimeError("Default service readback mismatch; restore the private backup")
    print("Applied and verified. Existing pooled sessions require a fresh agent process.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-provider", required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--backup", type=Path)
    asyncio.run(run(parser.parse_args()))
