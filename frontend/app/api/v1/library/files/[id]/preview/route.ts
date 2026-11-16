import { getServerApiBaseUrl } from "../../../../chat/_backend";
import { proxyRoute } from "../../../../_proxy";

export const GET = proxyRoute({
  method: "GET",
  target: (_request, { id }: { id: string }) =>
    `${getServerApiBaseUrl()}/api/v1/library/files/${encodeURIComponent(id)}/preview`,
  errorMessage: "获取文件预览失败，请稍后重试",
  forwardTenant: true,
  acceptJson: true,
});
