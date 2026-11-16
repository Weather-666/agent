import { getServerApiBaseUrl } from "../../../chat/_backend";
import { proxyRoute } from "../../../_proxy";

export const DELETE = proxyRoute({
  method: "DELETE",
  target: (_request, { id }: { id: string }) =>
    `${getServerApiBaseUrl()}/api/v1/library/files/${encodeURIComponent(id)}`,
  errorMessage: "删除资料库文件失败，请稍后重试",
  forwardTenant: true,
  acceptJson: true,
});
