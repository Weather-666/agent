from __future__ import annotations

import hmac
from typing import Any
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, RootModel, SecretStr, ValidationError

from app.core.config import Settings
from app.core.errors import ApiError


class GatewayMcpService(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    name: str
    description: str = ""
    transport: str
    disabled: bool = False


class GatewayMcpCapabilities(RootModel[dict[str, Any]]):
    pass


class GatewayMcpTool(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str
    description: str = ""
    inputSchema: dict[str, Any] = Field(default_factory=dict)


class GatewayRouteMatch(BaseModel):
    host: str = ""
    path_prefix: str
    methods: list[str] = Field(default_factory=list)


class GatewayRouteAuth(BaseModel):
    require_virtual_key: bool = False


class GatewayMcpRoute(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    kind: str = "mcp"
    protocol: str = "mcp"
    description: str = ""
    disabled: bool = False
    match_policy: GatewayRouteMatch
    auth_policy: GatewayRouteAuth
    service_id: str


class GatewayMcpRouteUpsert(BaseModel):
    id: str
    kind: str = "mcp"
    protocol: str = "mcp"
    description: str = ""
    disabled: bool = False
    match_policy: GatewayRouteMatch
    auth_policy: GatewayRouteAuth = Field(
        default_factory=lambda: GatewayRouteAuth(require_virtual_key=True)
    )
    service_id: str


class GatewayVirtualKey(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    key: SecretStr | None = None
    tag: str = ""
    description: str = ""
    disabled: bool = False
    allowed_route_ids: list[str] = Field(default_factory=list)


class GatewayVirtualKeyUpsert(BaseModel):
    id: str
    tag: str = ""
    description: str = ""
    disabled: bool = False
    allowed_route_ids: list[str] = Field(default_factory=list)


class GatewayAdminClient:
    def __init__(self, settings: Settings) -> None:
        self.base_url = settings.acp_gateway_admin_url
        self.bearer_token = settings.acp_gateway_admin_token
        self.data_plane_token = settings.acp_auth_token

    async def list_mcp_services(self) -> list[GatewayMcpService]:
        payload = await self._request("GET", "/admin/mcp/services") or {}
        items = payload.get("items")
        if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
            raise _gateway_error("Gateway MCP Service list readback is invalid")
        try:
            return [GatewayMcpService.model_validate(item) for item in items]
        except ValidationError:
            raise _gateway_error("Gateway MCP Service list readback is invalid") from None

    async def get_mcp_service(self, service_id: str) -> GatewayMcpService | None:
        payload = await self._request(
            "GET",
            f"/admin/mcp/services/{quote(service_id, safe='')}",
            allow_not_found=True,
        )
        if payload is None:
            return None
        return _validate_model(
            GatewayMcpService,
            payload,
            "Gateway MCP Service readback is invalid",
        )

    async def initialize_mcp_service(self, service_id: str) -> GatewayMcpCapabilities:
        payload = await self._request(
            "GET",
            f"/admin/mcp/services/{quote(service_id, safe='')}/capabilities",
        )
        return _validate_model(
            GatewayMcpCapabilities,
            payload or {},
            "Gateway MCP capabilities readback is invalid",
        )

    async def list_mcp_service_tools(self, service_id: str) -> list[GatewayMcpTool]:
        payload = (
            await self._request(
                "GET",
                f"/admin/mcp/services/{quote(service_id, safe='')}/tools",
            )
            or {}
        )
        items = payload.get("items")
        if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
            raise _gateway_error("Gateway MCP tool list readback is invalid")
        try:
            return [GatewayMcpTool.model_validate(item) for item in items]
        except ValidationError:
            raise _gateway_error("Gateway MCP tool list readback is invalid") from None

    async def get_mcp_route(self, route_id: str) -> GatewayMcpRoute | None:
        payload = await self._request(
            "GET",
            f"/admin/mcp/routes/{quote(route_id, safe='')}",
            allow_not_found=True,
        )
        if payload is None:
            return None
        return _validate_model(
            GatewayMcpRoute,
            payload,
            "Gateway MCP Route readback is invalid",
        )

    async def create_mcp_route(self, route: GatewayMcpRouteUpsert) -> GatewayMcpRoute:
        payload = await self._request(
            "POST",
            "/admin/mcp/routes",
            json=route.model_dump(),
        )
        return _validate_model(
            GatewayMcpRoute,
            payload or {},
            "Gateway MCP Route create readback is invalid",
        )

    async def update_mcp_route(self, route: GatewayMcpRouteUpsert) -> GatewayMcpRoute:
        payload = await self._request(
            "PUT",
            f"/admin/mcp/routes/{quote(route.id, safe='')}",
            json=route.model_dump(),
        )
        return _validate_model(
            GatewayMcpRoute,
            payload or {},
            "Gateway MCP Route update readback is invalid",
        )

    async def upsert_mcp_route(self, route: GatewayMcpRouteUpsert) -> GatewayMcpRoute:
        current = await self.get_mcp_route(route.id)
        if current is None:
            await self.create_mcp_route(route)
        elif not _mcp_route_matches(current, route):
            await self.update_mcp_route(route)
        actual = await self.get_mcp_route(route.id)
        if actual is None or not _mcp_route_matches(actual, route):
            raise _gateway_error("Gateway MCP Route readback mismatch")
        return actual

    async def get_virtual_key(self, key_id: str) -> GatewayVirtualKey | None:
        payload = await self._request(
            "GET",
            f"/admin/virtual_keys/{quote(key_id, safe='')}",
            allow_not_found=True,
        )
        if payload is None:
            return None
        return _validate_model(
            GatewayVirtualKey,
            payload,
            "Gateway VirtualKey readback is invalid",
        )

    async def create_virtual_key(self, key: GatewayVirtualKeyUpsert) -> GatewayVirtualKey:
        _require_nonempty_route_allowlist(key.allowed_route_ids)
        payload = await self._request(
            "POST",
            "/admin/virtual_keys",
            json=key.model_dump(),
        )
        return _validate_model(
            GatewayVirtualKey,
            payload or {},
            "Gateway VirtualKey create readback is invalid",
        )

    async def update_virtual_key(self, key: GatewayVirtualKeyUpsert) -> GatewayVirtualKey:
        _require_nonempty_route_allowlist(key.allowed_route_ids)
        payload = await self._request(
            "PUT",
            f"/admin/virtual_keys/{quote(key.id, safe='')}",
            json=key.model_dump(),
        )
        return _validate_model(
            GatewayVirtualKey,
            payload or {},
            "Gateway VirtualKey update readback is invalid",
        )

    async def enable_virtual_key(self, key_id: str) -> GatewayVirtualKey:
        payload = await self._request(
            "POST",
            f"/admin/virtual_keys/{quote(key_id, safe='')}/enable",
        )
        return _validate_model(
            GatewayVirtualKey,
            payload or {},
            "Gateway VirtualKey enable readback is invalid",
        )

    async def disable_virtual_key(self, key_id: str) -> None:
        current = await self.get_virtual_key(key_id)
        if current is None:
            return
        await self._request(
            "POST",
            f"/admin/virtual_keys/{quote(key_id, safe='')}/disable",
        )
        actual = await self.get_virtual_key(key_id)
        if actual is None or actual.disabled is not True:
            raise _gateway_error("Gateway VirtualKey disable readback failed")

    async def upsert_virtual_key(self, key: GatewayVirtualKeyUpsert) -> GatewayVirtualKey:
        _require_nonempty_route_allowlist(key.allowed_route_ids)
        current = await self.get_virtual_key(key.id)
        if current is None:
            await self.create_virtual_key(key)
        elif not _virtual_key_matches(current, key):
            await self.update_virtual_key(key)
        current = await self.get_virtual_key(key.id)
        if current is None:
            raise _gateway_error("Gateway VirtualKey readback is missing")
        if current.disabled:
            await self.enable_virtual_key(key.id)
        actual = await self.get_virtual_key(key.id)
        if actual is None or not _virtual_key_matches(actual, key) or actual.disabled:
            raise _gateway_error("Gateway VirtualKey readback mismatch")
        if actual.key is None or not actual.key.get_secret_value():
            raise _gateway_error("Gateway VirtualKey readback has no key")
        return actual

    async def get_service(self, service_id: str) -> dict[str, Any] | None:
        return await self._get_resource("acp/services", "Service", service_id)

    async def upsert_service(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._upsert_resource("acp/services", payload)

    async def get_route(self, route_id: str) -> dict[str, Any] | None:
        return await self._get_resource("acp/routes", "Route", route_id)

    async def upsert_route(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._upsert_resource("acp/routes", payload)

    async def disable_service(self, service_id: str) -> None:
        current = await self.get_service(service_id)
        if current is None:
            return
        payload = _writable_resource(current)
        payload["disabled"] = True
        await self.upsert_service(payload)
        actual = await self.get_service(service_id)
        if actual is None or actual.get("id") != service_id or actual.get("disabled") is not True:
            raise _gateway_error("Gateway Service disable readback failed")

    async def disable_route(self, route_id: str) -> None:
        current = await self.get_route(route_id)
        if current is None:
            return
        payload = _writable_resource(current)
        payload["disabled"] = True
        await self.upsert_route(payload)
        actual = await self.get_route(route_id)
        if actual is None or actual.get("id") != route_id or actual.get("disabled") is not True:
            raise _gateway_error("Gateway Route disable readback failed")

    async def add_virtual_key_route(
        self,
        virtual_key_id: str,
        route_id: str,
    ) -> None:
        current = await self._request(
            "GET",
            f"/admin/virtual_keys/{quote(virtual_key_id, safe='')}",
            allow_not_found=True,
        )
        if current is None:
            raise ApiError(
                503,
                "EXPERT_ACP_VIRTUAL_KEY_NOT_FOUND",
                "Configured Backend ACP VirtualKey does not exist",
            )
        _assert_virtual_key(current, virtual_key_id, self.data_plane_token)
        raw_allowed = current.get("allowed_route_ids") or []
        if not isinstance(raw_allowed, list):
            raise _gateway_error("Gateway VirtualKey readback is invalid")
        allowed = [str(item) for item in raw_allowed]
        if route_id not in allowed:
            allowed.append(route_id)
        payload = {
            "id": virtual_key_id,
            "tag": str((current or {}).get("tag") or "experts-backend"),
            "allowed_route_ids": sorted(set(allowed)),
        }
        if route_id not in {str(item) for item in raw_allowed}:
            await self._request(
                "PUT",
                f"/admin/virtual_keys/{quote(virtual_key_id, safe='')}",
                json=payload,
            )
        actual = (
            await self._request(
                "GET",
                f"/admin/virtual_keys/{quote(virtual_key_id, safe='')}",
            )
            or {}
        )
        _assert_virtual_key(actual, virtual_key_id, self.data_plane_token)
        actual_allowed = actual.get("allowed_route_ids") or []
        if route_id not in {str(item) for item in actual_allowed}:
            raise _gateway_error("Gateway VirtualKey readback is missing the Expert Route")

    async def close_acp_thread(self, service_id: str, thread_id: str) -> int:
        result = (
            await self._request(
                "DELETE",
                "/admin/acp/runtime/threads/"
                f"{quote(service_id, safe='')}/{quote(thread_id, safe='')}",
            )
            or {}
        )
        closed = result.get("closed")
        if isinstance(closed, bool) or not isinstance(closed, int) or closed < 0:
            raise _gateway_error("Gateway ACP thread close readback is invalid")
        return closed

    async def assert_service(self, expected: dict[str, Any]) -> None:
        actual = await self.get_service(str(expected["id"]))
        _assert_readback("Service", actual, expected)

    async def assert_route(self, expected: dict[str, Any]) -> None:
        actual = await self.get_route(str(expected["id"]))
        _assert_readback("Route", actual, expected)

    async def _upsert_resource(
        self,
        collection: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        resource_id = str(payload["id"])
        current = await self._get_resource(collection, "resource", resource_id)
        if current is None:
            return await self._request("POST", f"/admin/{collection}", json=payload) or {}
        return (
            await self._request(
                "PUT",
                f"/admin/{collection}/{quote(resource_id, safe='')}",
                json=payload,
            )
            or {}
        )

    async def _get_resource(
        self,
        collection: str,
        resource_name: str,
        resource_id: str,
    ) -> dict[str, Any] | None:
        item = await self._request(
            "GET",
            f"/admin/{collection}/{quote(resource_id, safe='')}",
            allow_not_found=True,
        )
        if item is not None:
            if item.get("id") == resource_id:
                return item
            if item.get("id") is not None:
                raise _gateway_error(f"Gateway {resource_name} readback returned a mismatched id")

        # Older Gateway builds can list ACP resources but return 404 from the
        # item endpoint. Fall back to the collection before deciding to POST;
        # otherwise a repeated publish collides with the existing routes.id.
        payload = await self._request("GET", f"/admin/{collection}") or {}
        items = payload.get("items")
        if not isinstance(items, list):
            raise _gateway_error(f"Gateway {resource_name} list readback is invalid")
        if any(not isinstance(candidate, dict) for candidate in items):
            raise _gateway_error(f"Gateway {resource_name} list readback is invalid")
        matches = [candidate for candidate in items if candidate.get("id") == resource_id]
        if len(matches) > 1:
            raise _gateway_error(f"Gateway {resource_name} list contains duplicate ids")
        return matches[0] if matches else None

    async def _request(
        self,
        method: str,
        path: str,
        *,
        allow_not_found: bool = False,
        **kwargs: Any,
    ) -> dict[str, Any] | None:
        if not self.base_url:
            raise ApiError(
                503,
                "EXPERT_GATEWAY_ADMIN_UNCONFIGURED",
                "Gateway Admin URL is not configured",
            )
        headers = {"Accept": "application/json"}
        if self.bearer_token:
            headers["Authorization"] = f"Bearer {self.bearer_token}"
        try:
            async with httpx.AsyncClient(
                base_url=self.base_url,
                timeout=30,
                trust_env=False,
            ) as client:
                response = await client.request(method, path, headers=headers, **kwargs)
        except httpx.HTTPError as exc:
            raise _gateway_error("Gateway Admin request failed") from exc
        if allow_not_found and response.status_code == 404:
            return None
        if response.status_code >= 400:
            raise ApiError(
                502,
                "EXPERT_GATEWAY_ADMIN_ERROR",
                "Gateway Admin request failed",
                {"statusCode": response.status_code},
            )
        if not response.content:
            return {}
        try:
            value = response.json()
        except ValueError as exc:
            raise _gateway_error("Gateway Admin returned invalid JSON") from exc
        if not isinstance(value, dict):
            raise _gateway_error("Gateway Admin returned non-object JSON")
        return value


def _writable_resource(value: dict[str, Any]) -> dict[str, Any]:
    return {
        key: item
        for key, item in value.items()
        if key
        not in {
            "created_at",
            "updated_at",
            "source",
            "read_only",
            # AgentView fields that must not round-trip into a create/update body.
            "runtime_status",
            "capabilities",
        }
    }


def _validate_model(
    model: type[BaseModel],
    value: object,
    message: str,
) -> Any:
    try:
        return model.model_validate(value)
    except ValidationError:
        raise _gateway_error(message) from None


def _mcp_route_matches(
    actual: GatewayMcpRoute,
    expected: GatewayMcpRouteUpsert,
) -> bool:
    return (
        actual.id == expected.id
        and actual.kind == "mcp"
        and actual.protocol == "mcp"
        and actual.description == expected.description
        and actual.disabled == expected.disabled
        and actual.match_policy == expected.match_policy
        and actual.auth_policy == expected.auth_policy
        and actual.service_id == expected.service_id
    )


def _virtual_key_matches(
    actual: GatewayVirtualKey,
    expected: GatewayVirtualKeyUpsert,
) -> bool:
    return (
        actual.id == expected.id
        and actual.tag == expected.tag
        and actual.description == expected.description
        and set(actual.allowed_route_ids) == set(expected.allowed_route_ids)
    )


def _require_nonempty_route_allowlist(route_ids: list[str]) -> None:
    if not route_ids:
        raise ApiError(
            409,
            "EXPERT_MCP_ROUTE_ALLOWLIST_EMPTY",
            "An Expert MCP VirtualKey requires at least one Route",
        )
    if any(not route_id.strip() for route_id in route_ids) or len(set(route_ids)) != len(route_ids):
        raise ApiError(
            409,
            "EXPERT_MCP_ROUTE_ALLOWLIST_INVALID",
            "An Expert MCP VirtualKey Route allowlist is invalid",
        )


def _assert_readback(
    resource_name: str,
    actual: dict[str, Any] | None,
    expected: dict[str, Any],
) -> None:
    if actual is None:
        raise _gateway_error(f"Gateway {resource_name} readback is missing")
    defaults: dict[str, Any] = {
        "allowed_roots": [],
        "default_model": "",
        "env": {},
        "config_overrides": {},
        "disabled": False,
        "description": "",
        "codex": None,
        "match_policy": {},
        "auth_policy": {"require_virtual_key": False},
    }
    for key, expected_value in expected.items():
        actual_value = actual.get(key, defaults.get(key))
        if key == "config_overrides" and actual_value is None:
            actual_value = {}
        if actual_value != expected_value:
            raise _gateway_error(f"Gateway {resource_name} readback mismatch: {key}")


def _assert_virtual_key(
    actual: dict[str, Any],
    virtual_key_id: str,
    configured_token: str | None,
) -> None:
    if actual.get("id") != virtual_key_id:
        raise _gateway_error("Gateway VirtualKey readback returned a mismatched id")
    # The gateway omits allowed_route_ids (omitempty) when the allowlist is empty;
    # a missing field is the same as an empty list, not an invalid readback.
    if not isinstance(actual.get("allowed_route_ids") or [], list):
        raise _gateway_error("Gateway VirtualKey readback is invalid")
    if not configured_token:
        raise ApiError(
            503,
            "EXPERT_ACP_AUTH_UNCONFIGURED",
            "Backend ACP authentication token is not configured",
        )
    key = actual.get("key")
    if not isinstance(key, str) or not hmac.compare_digest(key, configured_token):
        raise ApiError(
            503,
            "EXPERT_ACP_VIRTUAL_KEY_MISMATCH",
            "Backend ACP token does not match the configured VirtualKey",
        )


def _gateway_error(message: str) -> ApiError:
    return ApiError(502, "EXPERT_GATEWAY_ADMIN_ERROR", message)
