import { getServerApiBaseUrl } from "../chat/_backend";
import { proxyRoute } from "../_proxy";

export const GET = proxyRoute({
  method: "GET",
  target: (request) =>
    `${getServerApiBaseUrl()}/api/v1/audit-events${new URL(request.url).search}`,
  errorMessage: "获取操作日志失败，请稍后重试",
});
