import { getServerApiBaseUrl } from "../../../../chat/_backend";
import { proxyRoute } from "../../../../_proxy";

export const POST = proxyRoute({
  method: "POST",
  target: (_request, { id }: { id: string }) =>
    `${getServerApiBaseUrl()}/api/v1/library/files/${encodeURIComponent(id)}/promote`,
  errorMessage: "转为永久文件失败，请稍后重试",
  forwardTenant: true,
  acceptJson: true,
});
