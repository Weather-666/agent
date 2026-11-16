import { getServerApiBaseUrl } from "../../../chat/_backend";
import { proxyRoute } from "../../../_proxy";

export const GET = proxyRoute({
  method: "GET",
  target: (request, { userId }: { userId: string }) =>
    `${getServerApiBaseUrl()}/api/v1/users/${encodeURIComponent(userId)}/tenants${new URL(request.url).search}`,
  errorMessage: "获取用户租户列表失败，请稍后重试",
});
