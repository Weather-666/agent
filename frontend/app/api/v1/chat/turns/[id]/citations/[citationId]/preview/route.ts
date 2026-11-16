import { getServerApiBaseUrl } from "../../../../../_backend";
import { proxyRoute } from "../../../../../../_proxy";

export const GET = proxyRoute({
  method: "GET",
  target: (
    _request,
    { id, citationId }: { id: string; citationId: string },
  ) =>
    `${getServerApiBaseUrl()}/api/v1/chat/turns/${encodeURIComponent(id)}/citations/${encodeURIComponent(citationId)}/preview`,
  errorMessage: "获取引用预览失败，请稍后重试",
  forwardTenant: true,
  acceptJson: true,
});
