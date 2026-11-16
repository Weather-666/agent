import { getServerApiBaseUrl } from "../../../_backend";
import { proxyRoute } from "../../../../_proxy";

export const PATCH = proxyRoute({
  method: "PATCH",
  target: (_request, { id }: { id: string }) =>
    `${getServerApiBaseUrl()}/api/v1/chat/sessions/${encodeURIComponent(id)}/pin`,
  errorMessage: "更新会话置顶状态失败，请稍后重试",
  forwardTenant: true,
  acceptJson: true,
});
