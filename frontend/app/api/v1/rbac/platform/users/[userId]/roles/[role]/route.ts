import { getServerApiBaseUrl } from "../../../../../../chat/_backend";
import { proxyRoute } from "../../../../../../_proxy";

export const DELETE = proxyRoute({
  method: "DELETE",
  target: (_request, { userId, role }: { userId: string; role: string }) =>
    `${getServerApiBaseUrl()}/api/v1/rbac/platform/users/${encodeURIComponent(userId)}/roles/${encodeURIComponent(role)}`,
  errorMessage: "撤销平台角色失败，请稍后重试",
});
