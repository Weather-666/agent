import { getServerApiBaseUrl } from "../../../../chat/_backend";
import { proxyRoute } from "../../../../_proxy";

export const POST = proxyRoute({
  method: "POST",
  target: (_request, { id }: { id: string }) =>
    `${getServerApiBaseUrl()}/api/v1/knowledge-bases/${encodeURIComponent(id)}/index-review/approve`,
  errorMessage: "批准知识库索引构建失败，请稍后重试",
});
