import { getServerApiBaseUrl } from "../../../chat/_backend";
import { proxyRoute } from "../../../_proxy";

export const GET = proxyRoute({
  method: "GET",
  target: (request, { tenantId }: { tenantId: string }) =>
    `${getServerApiBaseUrl()}/api/v1/tenants/${encodeURIComponent(tenantId)}/members${new URL(request.url).search}`,
  errorMessage: "获取租户成员失败，请稍后重试",
});

export const POST = proxyRoute({
  method: "POST",
  target: (_request, { tenantId }: { tenantId: string }) =>
    `${getServerApiBaseUrl()}/api/v1/tenants/${encodeURIComponent(tenantId)}/members`,
  errorMessage: "添加租户成员失败，请稍后重试",
});
