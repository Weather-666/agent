import { getServerApiBaseUrl } from "../../../../chat/_backend";
import { proxyRoute } from "../../../../_proxy";

const target = (
  _request: Request,
  { tenantId, userId }: { tenantId: string; userId: string },
) =>
  `${getServerApiBaseUrl()}/api/v1/tenants/${encodeURIComponent(tenantId)}/members/${encodeURIComponent(userId)}`;

export const PATCH = proxyRoute({
  method: "PATCH",
  target,
  errorMessage: "更新租户成员失败，请稍后重试",
});

export const DELETE = proxyRoute({
  method: "DELETE",
  target,
  errorMessage: "移除租户成员失败，请稍后重试",
});
