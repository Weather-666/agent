import { getServerApiBaseUrl } from "../../../chat/_backend";
import { proxyRoute } from "../../../_proxy";

export const GET = proxyRoute({
  method: "GET",
  target: (_request, { id }: { id: string }) =>
    `${getServerApiBaseUrl()}/api/v1/knowledge-bases/${encodeURIComponent(id)}/index-review`,
  errorMessage: "获取待构建索引批次失败，请稍后重试",
});
