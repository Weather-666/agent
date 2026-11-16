import { getServerApiBaseUrl } from "../../chat/_backend";
import { proxyRoute } from "../../_proxy";

export const GET = proxyRoute({
  method: "GET",
  target: (request) =>
    `${getServerApiBaseUrl()}/api/v1/users/platform${new URL(request.url).search}`,
  errorMessage: "获取平台用户列表失败，请稍后重试",
});

export const POST = proxyRoute({
  method: "POST",
  target: () => `${getServerApiBaseUrl()}/api/v1/users/platform`,
  errorMessage: "创建平台用户失败，请稍后重试",
});
