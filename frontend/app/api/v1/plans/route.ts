import { getServerApiBaseUrl } from "../chat/_backend";
import { proxyRoute } from "../_proxy";

export const GET = proxyRoute({
  method: "GET",
  target: (request) =>
    `${getServerApiBaseUrl()}/api/v1/plans${new URL(request.url).search}`,
  errorMessage: "获取套餐列表失败，请稍后重试",
});

export const POST = proxyRoute({
  method: "POST",
  target: () => `${getServerApiBaseUrl()}/api/v1/plans`,
  errorMessage: "创建套餐失败，请稍后重试",
});
