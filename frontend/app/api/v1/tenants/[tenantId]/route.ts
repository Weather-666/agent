import { getServerApiBaseUrl } from "../../chat/_backend";
import { proxyRoute } from "../../_proxy";

const target = (_request: Request, { tenantId }: { tenantId: string }) =>
  `${getServerApiBaseUrl()}/api/v1/tenants/${encodeURIComponent(tenantId)}`;

export const GET = proxyRoute({
  method: "GET",
  target,
  errorMessage: "获取租户详情失败，请稍后重试",
});

export const PATCH = proxyRoute({
  method: "PATCH",
  target,
  errorMessage: "更新租户失败，请稍后重试",
});
