import request, { getAccessToken, requestData } from "../request";

export type McpConnector = {
  id: string;
  name: string;
  description?: string | null;
  transport?: string | null;
};

export type McpConnectorsResponse = {
  items: McpConnector[];
};

function authHeaders() {
  const accessToken = getAccessToken();
  return accessToken ? { Authorization: `Bearer ${accessToken}` } : {};
}

export function getMcpConnectors(_client: typeof request = request) {
  return requestData(
    _client.get<McpConnectorsResponse>("/api/v1/mcp-connectors", {
      headers: authHeaders(),
    })
  );
}
