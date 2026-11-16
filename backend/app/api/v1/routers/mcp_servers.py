from fastapi import APIRouter, Depends

from app.api.deps import get_mcp_connector_service, require_platform_permission
from app.domain.auth import Principal
from app.domain.mcp_connectors import McpConnectorListResponse
from app.services.mcp_connector_service import McpConnectorService


router = APIRouter()


@router.get("", response_model=McpConnectorListResponse)
async def list_mcp_connectors(
    principal: Principal = Depends(require_platform_permission("expert:read")),
    service: McpConnectorService = Depends(get_mcp_connector_service),
) -> McpConnectorListResponse:
    return await service.list_enabled()
