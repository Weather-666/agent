import { getServerApiBaseUrl } from "../../chat/_backend";
import { proxyRoute } from "../../_proxy";

export const GET = proxyRoute({
  method: "GET",
  target: () => `${getServerApiBaseUrl()}/api/v1/credits/current`,
  errorMessage: "获取积分信息失败，请稍后重试",
  forwardTenant: true,
});
