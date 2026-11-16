from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx

from app.core.config import Settings
from app.core.errors import ApiError


_SANDBOX_MOUNT_TARGETS = (".git", ".agents", ".codex")


class AcpGatewayClient:
    """Client for the agent-gateway ACP data plane.

    The ACP data plane exposes routed endpoints under a configured path prefix:
      - POST {prefix}/turn       -> SSE stream (events: session, delta, permission, done, error)
      - POST {prefix}/permission -> answers one in-flight interactive permission request
      - GET  {prefix}/sessions   -> list materialized ACP sessions (history replay)
      - GET  {prefix}/sessions/{id}/transcript -> coalesced session transcript
    All are route-scoped and authenticated by the route's VirtualKey, so history
    replay no longer needs the gateway admin plane. There is no server-side
    thread/turn lifecycle: `thread_id` is caller-owned and `session_id` is assigned
    by the agent and surfaced via the first `session` event. The local DB stays the
    system of record; this client only drives compute.
    """

    def __init__(self, settings: Settings) -> None:
        self.base_url = settings.acp_gateway_base_url
        self.route_prefix = settings.acp_route_prefix.rstrip("/")
        self.search_route_prefix = (
            settings.acp_search_route_prefix.rstrip("/")
            if settings.acp_search_route_prefix
            else None
        )
        self.auth_token = settings.acp_auth_token
        self.client_id = settings.acp_client_id
        self.default_model = settings.acp_default_model
        self.default_cwd = settings.acp_default_cwd
        self.cwd_base = settings.acp_cwd_base

    def prepare_default_cwd(self) -> str | None:
        """Resolve and create the legacy/unbound ACP working directory."""
        if not self.default_cwd:
            return None
        path = _absolute_path(self.default_cwd)
        _mkdir(path, kind="default")
        return str(path)

    def prepare_tenant_cwd(self, tenant_id: str) -> str:
        """Resolve and create one bound Expert tenant working directory.

        A tenant id is a single path segment. The resolved directory must stay
        under cwd_base and may not itself be a symlink. Backend owns the root
        and tenant child, and Gateway shares the same filesystem.
        """
        if not self.cwd_base:
            raise ApiError(
                503,
                "ACP_TENANT_CWD_UNCONFIGURED",
                "ACP tenant workspace root is not configured",
            )
        _validate_tenant_segment(tenant_id)
        base = _absolute_path(self.cwd_base)
        if base.is_symlink():
            raise ApiError(
                500,
                "ACP_TENANT_CWD_INVALID",
                "ACP tenant workspace root may not be a symbolic link",
            )
        _mkdir(base, kind="tenant_root")
        try:
            resolved_base = base.resolve(strict=True)
            if not resolved_base.is_dir():
                raise NotADirectoryError(str(base))
        except OSError as exc:
            raise _cwd_prepare_error(base, "tenant_root", exc) from exc

        resolved_candidate = _prepare_workspace_child(
            resolved_base,
            tenant_id,
            kind="tenant",
            label="tenant workspace",
            details={"tenantId": tenant_id},
        )
        prepare_sandbox_mount_targets(
            resolved_candidate,
            details={"tenantId": tenant_id},
        )
        return str(resolved_candidate)

    def prepare_user_cwd(self, tenant_id: str, user_id: str) -> str:
        """Resolve one user-isolated workspace below a tenant workspace.

        New Chat Sessions use `<cwd_base>/<tenant_id>/users/<user_id>`. Existing
        Sessions keep their recorded legacy workspace mode and continue resolving
        through `prepare_default_cwd` or `prepare_tenant_cwd`.
        """
        _validate_workspace_segment(user_id, field="userId")
        details = {"tenantId": tenant_id, "userId": user_id}
        tenant = Path(self.prepare_tenant_cwd(tenant_id))
        users_root = _prepare_workspace_child(
            tenant,
            "users",
            kind="user_root",
            label="user workspace root",
            details=details,
        )
        resolved_candidate = _prepare_workspace_child(
            users_root,
            user_id,
            kind="user",
            label="user workspace",
            details=details,
        )
        prepare_sandbox_mount_targets(
            resolved_candidate,
            details={"tenantId": tenant_id, "userId": user_id},
        )
        return str(resolved_candidate)

    def _path(self, suffix: str, route_prefix: str | None = None) -> str:
        prefix = self.route_prefix if route_prefix is None else route_prefix.rstrip("/")
        return f"{prefix}{suffix}"

    def _headers(self, tenant_id: str | None = None) -> dict[str, str]:
        headers = {"X-Client-ID": self.client_id}
        if self.auth_token:
            headers["Authorization"] = f"Bearer {self.auth_token}"
        if tenant_id:
            headers["X-Tenant-Id"] = tenant_id
        return headers

    async def request(
        self, method: str, path: str, *, tenant_id: str | None = None, **kwargs: Any
    ) -> Any:
        if not self.base_url:
            raise ApiError(503, "ACP_UNCONFIGURED", "acp gateway base URL is not configured")
        async with httpx.AsyncClient(base_url=self.base_url, timeout=120) as client:
            response = await client.request(method, path, headers=self._headers(tenant_id), **kwargs)
        if response.status_code >= 400:
            raise _upstream_error(response, stream=False)
        if not response.content:
            return None
        return response.json()

    async def stream(
        self, method: str, path: str, *, tenant_id: str | None = None, **kwargs: Any
    ) -> AsyncIterator[str]:
        if not self.base_url:
            raise ApiError(503, "ACP_UNCONFIGURED", "acp gateway base URL is not configured")
        async with (
            httpx.AsyncClient(base_url=self.base_url, timeout=None) as client,
            client.stream(
                method, path, headers=self._headers(tenant_id), **kwargs
            ) as response,
        ):
            if response.status_code >= 400:
                await response.aread()
                raise _upstream_error(response, stream=True)
            async for line in response.aiter_lines():
                yield line

    # --- ACP data-plane endpoints --------------------------------------------

    def stream_turn(
        self,
        *,
        thread_id: str,
        input: str,
        tenant_id: str | None = None,
        session_id: str | None = None,
        cwd: str | None = None,
        model: str | None = None,
        fresh_session: bool = False,
        config_overrides: dict[str, str] | None = None,
        search_mode: str | None = None,
        route_prefix: str | None = None,
    ) -> AsyncIterator[str]:
        """Drive one turn. Yields raw SSE lines from POST {prefix}/turn.

        Mirrors the deployed Gateway acpruntime.TurnRequest. Search routing is
        selected by the route prefix and never rides in the payload.
        """
        payload: dict[str, Any] = {"thread_id": thread_id, "input": input}
        if session_id:
            payload["session_id"] = session_id
        if cwd:
            payload["cwd"] = cwd
        if model is None and self.default_model:
            payload["model"] = self.default_model
        elif model:
            payload["model"] = model
        if fresh_session:
            payload["fresh_session"] = True
        if config_overrides:
            payload["config_overrides"] = config_overrides
        return self.stream(
            "POST", self._path("/turn", route_prefix), tenant_id=tenant_id, json=payload
        )

    async def resolve_permission(
        self,
        *,
        request_id: str,
        outcome: str,
        option_id: str | None = None,
        tenant_id: str | None = None,
        route_prefix: str | None = None,
    ) -> Any:
        """Answer one pending interactive permission request via POST {prefix}/permission.

        Mirrors acpruntime.PermissionDecision: outcome is the ACP discriminator
        ("selected" with option_id, or "cancelled"). The id travels in the body,
        not the path, and must reach the gateway instance holding the request.
        """
        payload: dict[str, Any] = {"request_id": request_id, "outcome": outcome}
        if option_id:
            payload["option_id"] = option_id
        return await self.request(
            "POST", self._path("/permission", route_prefix), tenant_id=tenant_id, json=payload
        )

    async def list_sessions(
        self,
        *,
        tenant_id: str | None = None,
        cwd: str | None = None,
        cursor: str | None = None,
        route_prefix: str | None = None,
    ) -> Any:
        """List materialized ACP sessions via GET {prefix}/sessions.

        Returns the gateway's ListSessionsResponse: {sessions: [{session_id, cwd,
        title, updated_at}], next_cursor}. The route's VirtualKey is the only auth;
        scope is the route's service, so no service id is passed.
        """
        params: dict[str, str] = {}
        if cwd:
            params["cwd"] = cwd
        if cursor:
            params["cursor"] = cursor
        return await self.request(
            "GET", self._path("/sessions", route_prefix), tenant_id=tenant_id, params=params or None
        )

    async def get_transcript(
        self,
        *,
        session_id: str,
        tenant_id: str | None = None,
        cwd: str | None = None,
        route_prefix: str | None = None,
    ) -> Any:
        """Load a session's coalesced transcript via GET {prefix}/sessions/{id}/transcript.

        Returns the gateway's TranscriptResponse: {session_id, messages: [{role,
        text}]} with role in user/assistant/reasoning.
        """
        params: dict[str, str] = {}
        if cwd:
            params["cwd"] = cwd
        path = self._path(f"/sessions/{quote(session_id, safe='')}/transcript", route_prefix)
        return await self.request("GET", path, tenant_id=tenant_id, params=params or None)


def _upstream_error(response: httpx.Response, *, stream: bool) -> ApiError:
    upstream_code: str | None = None
    try:
        body = response.json()
    except ValueError:
        body = None
    if isinstance(body, dict):
        candidate = body.get("code")
        if candidate is None and isinstance(body.get("error"), dict):
            candidate = body["error"].get("code")
        if candidate is not None:
            upstream_code = str(candidate)[:120]
    details: dict[str, Any] = {
        "statusCode": response.status_code,
        "retryable": response.status_code in {429, 502, 503, 504},
    }
    if upstream_code:
        details["upstreamCode"] = upstream_code
    if response.status_code == 429:
        details["queueSupported"] = False
        return ApiError(
            429,
            "ACP_CAPACITY_EXHAUSTED",
            "Expert Runtime capacity is temporarily exhausted",
            details,
        )
    return ApiError(
        response.status_code,
        "ACP_UPSTREAM_ERROR",
        "acp gateway stream failed" if stream else "acp gateway request failed",
        details,
    )


def _absolute_path(value: str) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else path.resolve()


def _validate_tenant_segment(tenant_id: str) -> None:
    _validate_workspace_segment(tenant_id, field="tenantId")
    if tenant_id == ".publication":
        raise ApiError(
            500,
            "ACP_TENANT_CWD_INVALID",
            "tenantId conflicts with the reserved publication workspace",
            {"tenantId": tenant_id},
        )


def _validate_workspace_segment(value: str, *, field: str) -> None:
    if (
        not value
        or value in {".", ".."}
        or "/" in value
        or "\\" in value
        or "\x00" in value
        or Path(value).is_absolute()
    ):
        raise ApiError(
            500,
            "ACP_TENANT_CWD_INVALID",
            f"{field} is not a safe ACP workspace path segment",
            {field: value},
        )


def _mkdir(path: Path, *, kind: str, parents: bool = True) -> None:
    try:
        path.mkdir(parents=parents, exist_ok=True)
        if not path.is_dir():
            raise NotADirectoryError(str(path))
    except OSError as exc:
        raise _cwd_prepare_error(path, kind, exc) from exc


def _prepare_workspace_child(
    parent: Path,
    name: str,
    *,
    kind: str,
    label: str,
    details: dict[str, str],
) -> Path:
    candidate = parent / name
    error_details = {**details, "path": str(candidate)}
    if candidate.is_symlink():
        raise ApiError(
            500,
            "ACP_TENANT_CWD_INVALID",
            f"ACP {label} may not be a symbolic link",
            error_details,
        )
    _mkdir(candidate, kind=kind, parents=False)
    if candidate.is_symlink():
        raise ApiError(
            500,
            "ACP_TENANT_CWD_INVALID",
            f"ACP {label} may not be a symbolic link",
            error_details,
        )
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(parent)
        return resolved
    except ValueError as exc:
        raise ApiError(
            500,
            "ACP_TENANT_CWD_INVALID",
            f"ACP {label} resolves outside its configured root",
            error_details,
        ) from exc
    except OSError as exc:
        raise _cwd_prepare_error(candidate, kind, exc) from exc


def prepare_sandbox_mount_targets(
    workspace: Path,
    *,
    details: dict[str, str],
) -> None:
    """Create the empty paths Bubblewrap binds over before an Expert tool starts."""
    for name in _SANDBOX_MOUNT_TARGETS:
        target = _prepare_workspace_child(
            workspace,
            name,
            kind="sandbox_mount",
            label="sandbox mount target",
            details=details,
        )
        try:
            next(target.iterdir())
        except StopIteration:
            continue
        except OSError as exc:
            raise _cwd_prepare_error(target, "sandbox_mount", exc) from exc
        raise ApiError(
            500,
            "ACP_TENANT_CWD_INVALID",
            "ACP sandbox mount target must be empty",
            {**details, "path": str(target)},
        )


def _cwd_prepare_error(path: Path, kind: str, exc: OSError) -> ApiError:
    return ApiError(
        500,
        "ACP_CWD_PREPARE_FAILED",
        "Failed to prepare ACP working directory",
        {"kind": kind, "path": str(path), "reason": str(exc)},
    )
