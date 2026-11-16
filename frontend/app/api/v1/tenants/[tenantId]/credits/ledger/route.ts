import { getServerApiBaseUrl } from "../../../../chat/_backend";
import { proxyRoute } from "../../../../_proxy";

export const GET = proxyRoute({
  method: "GET",
  target: (request, { tenantId }: { tenantId: string }) =>
    `${getServerApiBaseUrl()}/api/v1/tenants/${encodeURIComponent(tenantId)}/credits/ledger${new URL(request.url).search}`,
  errorMessage: "获取租户积分流水失败，请稍后重试",
});
