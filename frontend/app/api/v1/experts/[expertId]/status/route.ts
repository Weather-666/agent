import { getServerApiBaseUrl } from "../../../chat/_backend";
import { proxyRoute } from "../../../_proxy";

export const PATCH = proxyRoute({
  method: "PATCH",
  target: (_request, { expertId }: { expertId: string }) =>
    `${getServerApiBaseUrl()}/api/v1/experts/${encodeURIComponent(expertId)}/status`,
  errorMessage: "更新专家状态失败，请稍后重试",
});
