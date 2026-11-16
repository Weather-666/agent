import { getServerApiBaseUrl } from "../../../chat/_backend";
import { proxyRoute } from "../../../_proxy";

export const PATCH = proxyRoute({
  method: "PATCH",
  target: (_request, { tenantId }: { tenantId: string }) =>
    `${getServerApiBaseUrl()}/api/v1/tenants/${encodeURIComponent(tenantId)}/status`,
  errorMessage: "更新租户状态失败，请稍后重试",
});
