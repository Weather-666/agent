from pydantic import BaseModel


class McpConnector(BaseModel):
    id: str
    name: str
    description: str
    transport: str


class McpConnectorListResponse(BaseModel):
    items: list[McpConnector]
