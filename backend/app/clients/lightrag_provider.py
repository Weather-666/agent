from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from app.core.config import Settings
from app.core.errors import ApiError


@dataclass(frozen=True)
class ProvisionedLightRag:
    provider: str
    provider_ref: str
    base_url: str
    workspace: str
    status: str


class LightRagProvider(Protocol):
    async def ensure(self, knowledge_base_id: str) -> ProvisionedLightRag: ...

    async def health(self, knowledge_base_id: str) -> ProvisionedLightRag: ...

    async def delete(self, knowledge_base_id: str) -> None: ...

    async def reconcile(self, knowledge_base_ids: list[str]) -> dict[str, Any]: ...


class ControllerLightRagProvider:
    """Narrow Backend client for the independently privileged LightRAG Controller.

    The Controller API exposes only idempotent instance lifecycle operations. The Backend never
    imports a Docker client, receives a socket path, or sends arbitrary container configuration.
    """

    def __init__(
        self,
        base_url: str,
        token: str | None,
        *,
        timeout: float,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout
        self.transport = transport

    def _headers(self) -> dict[str, str]:
        if not self.token:
            return {}
        return {"Authorization": f"Bearer {self.token}"}

    async def ensure(self, knowledge_base_id: str) -> ProvisionedLightRag:
        payload = await self._request(
            "PUT", f"/v1/instances/{knowledge_base_id}", json={}
        )
        return _instance(payload)

    async def health(self, knowledge_base_id: str) -> ProvisionedLightRag:
        payload = await self._request("GET", f"/v1/instances/{knowledge_base_id}")
        return _instance(payload)

    async def delete(self, knowledge_base_id: str) -> None:
        await self._request("DELETE", f"/v1/instances/{knowledge_base_id}")

    async def reconcile(self, knowledge_base_ids: list[str]) -> dict[str, Any]:
        return await self._request(
            "POST", "/v1/instances/reconcile", json={"knowledgeBaseIds": knowledge_base_ids}
        )

    async def _request(
        self, method: str, path: str, *, json: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(
                base_url=self.base_url,
                timeout=self.timeout,
                transport=self.transport,
                trust_env=False,
            ) as client:
                response = await client.request(
                    method, path, json=json, headers=self._headers()
                )
            if response.status_code == 404 and method == "DELETE":
                return {"status": "deleted"}
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                raise ValueError("Controller response is not an object")
            return payload
        except ValueError as exc:
            raise ApiError(
                502,
                "LIGHTRAG_CONTROLLER_INVALID_RESPONSE",
                "LightRAG Controller returned an invalid response",
            ) from exc
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            try:
                detail = exc.response.json().get("detail")
            except ValueError:
                detail = None
            raise ApiError(
                503 if status >= 500 else status,
                "LIGHTRAG_PROVISIONING_FAILED",
                str(detail or "LightRAG Controller rejected the lifecycle request"),
                {"controllerStatus": status},
            ) from exc
        except httpx.HTTPError as exc:
            raise ApiError(
                503,
                "LIGHTRAG_CONTROLLER_UNAVAILABLE",
                "LightRAG Controller is unavailable",
            ) from exc


def create_lightrag_provider(settings: Settings) -> LightRagProvider | None:
    if settings.lightrag_controller_url is None:
        return None
    return ControllerLightRagProvider(
        settings.lightrag_controller_url,
        settings.lightrag_controller_token,
        timeout=settings.lightrag_controller_timeout_seconds,
    )


def _instance(payload: dict[str, Any]) -> ProvisionedLightRag:
    try:
        instance = ProvisionedLightRag(
            provider=str(payload["provider"]),
            provider_ref=str(payload["providerRef"]),
            base_url=str(payload["baseUrl"]).rstrip("/"),
            workspace=str(payload["workspace"]),
            status=str(payload["status"]),
        )
    except (KeyError, TypeError) as exc:
        raise ApiError(
            502,
            "LIGHTRAG_CONTROLLER_INVALID_RESPONSE",
            "LightRAG Controller response is missing instance identity",
        ) from exc
    if instance.status != "ready":
        raise ApiError(
            503,
            "LIGHTRAG_INSTANCE_NOT_READY",
            "LightRAG instance is not ready",
            {"status": instance.status},
        )
    return instance
