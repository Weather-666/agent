import { getServerApiBaseUrl } from "../../../../chat/_backend";
import { proxyRoute } from "../../../../_proxy";

export const POST = proxyRoute({
  method: "POST",
  target: (_request, { id }: { id: string }) =>
    `${getServerApiBaseUrl()}/api/v1/knowledge-bases/${encodeURIComponent(id)}/docs/complete-uploads`,
  errorMessage: "确认批量文档上传失败，请稍后重试",
});
