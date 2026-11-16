import { getServerApiBaseUrl } from "../../../../../_backend";
import { proxyRoute } from "../../../../../../_proxy";

export const GET = proxyRoute({
  method: "GET",
  target: (
    _request,
    { id, citationId }: { id: string; citationId: string },
  ) =>
    `${getServerApiBaseUrl()}/api/v1/chat/turns/${encodeURIComponent(id)}/citations/${encodeURIComponent(citationId)}/download`,
  errorMessage: "获取引用下载地址失败，请稍后重试",
  forwardTenant: true,
  acceptJson: true,
});
