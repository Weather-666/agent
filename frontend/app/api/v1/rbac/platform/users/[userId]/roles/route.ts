import { getServerApiBaseUrl } from "../../../../../chat/_backend";
import { proxyRoute } from "../../../../../_proxy";

export const POST = proxyRoute({
  method: "POST",
  target: (_request, { userId }: { userId: string }) =>
    `${getServerApiBaseUrl()}/api/v1/rbac/platform/users/${encodeURIComponent(userId)}/roles`,
  errorMessage: "授予平台角色失败，请稍后重试",
});
