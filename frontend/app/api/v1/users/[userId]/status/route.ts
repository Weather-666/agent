import { getServerApiBaseUrl } from "../../../chat/_backend";
import { proxyRoute } from "../../../_proxy";

export const PATCH = proxyRoute({
  method: "PATCH",
  target: (_request, { userId }: { userId: string }) =>
    `${getServerApiBaseUrl()}/api/v1/users/${encodeURIComponent(userId)}/status`,
  errorMessage: "更新用户状态失败，请稍后重试",
});
