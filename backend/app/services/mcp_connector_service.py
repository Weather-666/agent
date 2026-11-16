from app.clients.gateway_admin import GatewayAdminClient
from app.core.errors import ApiError
from app.domain.mcp_connectors import McpConnector, McpConnectorListResponse


class McpConnectorService:
    def __init__(self, gateway: GatewayAdminClient) -> None:
        self.gateway = gateway

    async def list_enabled(self) -> McpConnectorListResponse:
        try:
            services = await self.gateway.list_mcp_services()
        except ApiError:
            raise ApiError(
                503,
                "MCP_CONNECTORS_UNAVAILABLE",
                "MCP Connector directory is unavailable",
            ) from None
        return McpConnectorListResponse(
            items=[
                McpConnector(
                    id=service.id,
                    name=service.name,
                    description=service.description,
                    transport=service.transport,
                )
                for service in sorted(services, key=lambda item: item.id)
                if not service.disabled
            ]
        )
