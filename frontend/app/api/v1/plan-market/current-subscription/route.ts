import { getServerApiBaseUrl } from "../../chat/_backend";
import { proxyRoute } from "../../_proxy";

export const GET = proxyRoute({
  method: "GET",
  target: () => `${getServerApiBaseUrl()}/api/v1/plan-market/current-subscription`,
  errorMessage: "获取当前订阅失败，请稍后重试",
  forwardTenant: true,
});

export const PATCH = proxyRoute({
  method: "PATCH",
  target: () => `${getServerApiBaseUrl()}/api/v1/plan-market/current-subscription`,
  errorMessage: "套餐升级失败，请稍后重试",
  forwardTenant: true,
});
