import { getServerApiBaseUrl } from "../../../chat/_backend";
import { proxyRoute } from "../../../_proxy";

export const GET = proxyRoute({
  method: "GET",
  target: (request, { id }: { id: string }) =>
    `${getServerApiBaseUrl()}/api/v1/knowledge-bases/${encodeURIComponent(id)}/docs${new URL(request.url).search}`,
  errorMessage: "获取知识库文档列表失败，请稍后重试",
});
