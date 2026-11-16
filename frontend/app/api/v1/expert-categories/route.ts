import { getServerApiBaseUrl } from "../chat/_backend";
import { proxyRoute } from "../_proxy";

export const GET = proxyRoute({
  method: "GET",
  target: (request) =>
    `${getServerApiBaseUrl()}/api/v1/expert-categories${new URL(request.url).search}`,
  errorMessage: "获取专家分类列表失败，请稍后重试",
});

export const POST = proxyRoute({
  method: "POST",
  target: () => `${getServerApiBaseUrl()}/api/v1/expert-categories`,
  errorMessage: "创建专家分类失败，请稍后重试",
});
