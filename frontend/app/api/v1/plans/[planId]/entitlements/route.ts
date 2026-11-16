import { getServerApiBaseUrl } from "../../../chat/_backend";
import { proxyRoute } from "../../../_proxy";

export const PUT = proxyRoute({
  method: "PUT",
  target: (_request, { planId }: { planId: string }) =>
    `${getServerApiBaseUrl()}/api/v1/plans/${encodeURIComponent(planId)}/entitlements`,
  errorMessage: "更新套餐权益失败，请稍后重试",
});
