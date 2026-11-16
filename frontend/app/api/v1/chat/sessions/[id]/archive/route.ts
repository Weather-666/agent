import { getServerApiBaseUrl } from "../../../_backend";
import { proxyRoute } from "../../../../_proxy";

export const PATCH = proxyRoute({
  method: "PATCH",
  target: (_request, { id }: { id: string }) =>
    `${getServerApiBaseUrl()}/api/v1/chat/sessions/${encodeURIComponent(id)}/archive`,
  errorMessage: "更新会话归档状态失败，请稍后重试",
  forwardTenant: true,
  acceptJson: true,
});
