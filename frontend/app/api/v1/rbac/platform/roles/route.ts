import { getServerApiBaseUrl } from "../../../chat/_backend";
import { proxyRoute } from "../../../_proxy";

export const GET = proxyRoute({
  method: "GET",
  target: (request) =>
    `${getServerApiBaseUrl()}/api/v1/rbac/platform/roles${new URL(request.url).search}`,
  errorMessage: "获取平台角色列表失败，请稍后重试",
});
