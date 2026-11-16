import { getServerApiBaseUrl } from "../../../chat/_backend";
import { proxyRoute } from "../../../_proxy";

const target = (_request: Request, { tenantId }: { tenantId: string }) =>
  `${getServerApiBaseUrl()}/api/v1/tenants/${encodeURIComponent(tenantId)}/subscription`;

export const PATCH = proxyRoute({
  method: "PATCH",
  target,
  errorMessage: "更新租户订阅失败，请稍后重试",
});
