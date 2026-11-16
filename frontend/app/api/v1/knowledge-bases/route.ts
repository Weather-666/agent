import { getServerApiBaseUrl } from "../chat/_backend";
import { proxyRoute } from "../_proxy";

export const GET = proxyRoute({
  method: "GET",
  target: (request) =>
    `${getServerApiBaseUrl()}/api/v1/knowledge-bases${new URL(request.url).search}`,
  errorMessage: "获取知识库列表失败，请稍后重试",
});

export const POST = proxyRoute({
  method: "POST",
  target: () => `${getServerApiBaseUrl()}/api/v1/knowledge-bases`,
  errorMessage: "创建知识库失败，请稍后重试",
});
