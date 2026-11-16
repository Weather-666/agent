import { getServerApiBaseUrl } from "../../../chat/_backend";
import { proxyRoute } from "../../../_proxy";

export const POST = proxyRoute({
  method: "POST",
  target: (_request, { id }: { id: string }) =>
    `${getServerApiBaseUrl()}/api/v1/knowledge-bases/${encodeURIComponent(id)}/activate`,
  errorMessage: "启用知识库失败，请稍后重试",
});
