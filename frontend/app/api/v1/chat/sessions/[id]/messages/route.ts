import { getServerApiBaseUrl } from "../../../_backend";
import { proxyRoute } from "../../../../_proxy";

export const GET = proxyRoute({
  method: "GET",
  target: (request, { id }: { id: string }) =>
    `${getServerApiBaseUrl()}/api/v1/chat/sessions/${encodeURIComponent(id)}/messages${new URL(request.url).search}`,
  errorMessage: "获取会话消息失败，请稍后重试",
  forwardTenant: true,
  acceptJson: true,
});
