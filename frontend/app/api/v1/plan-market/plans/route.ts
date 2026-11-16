import { getServerApiBaseUrl } from "../../chat/_backend";
import { proxyRoute } from "../../_proxy";

export const GET = proxyRoute({
  method: "GET",
  target: () => `${getServerApiBaseUrl()}/api/v1/plan-market/plans`,
  errorMessage: "获取套餐列表失败，请稍后重试",
});
