import { getServerApiBaseUrl } from "../../../../../chat/_backend";
import { proxyRoute } from "../../../../../_proxy";

export const GET = proxyRoute({
  method: "GET",
  target: (
    _request,
    { id, documentId }: { id: string; documentId: string },
  ) =>
    `${getServerApiBaseUrl()}/api/v1/knowledge-bases/${encodeURIComponent(id)}/docs/${encodeURIComponent(documentId)}/download-url`,
  errorMessage: "获取文档下载地址失败，请稍后重试",
});
