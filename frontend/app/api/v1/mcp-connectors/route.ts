import { getServerApiBaseUrl } from "../chat/_backend";
import { proxyRoute } from "../_proxy";

export const GET = proxyRoute({
  method: "GET",
  target: () => `${getServerApiBaseUrl()}/api/v1/mcp-connectors`,
  errorMessage: "获取 MCP Connector 列表失败，请稍后重试",
});
