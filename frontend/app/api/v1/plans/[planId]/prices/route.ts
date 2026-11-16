import { getServerApiBaseUrl } from "../../../chat/_backend";
import { proxyRoute } from "../../../_proxy";

export const PUT = proxyRoute({
  method: "PUT",
  target: (_request, { planId }: { planId: string }) =>
    `${getServerApiBaseUrl()}/api/v1/plans/${encodeURIComponent(planId)}/prices`,
  errorMessage: "更新套餐价格失败，请稍后重试",
});
