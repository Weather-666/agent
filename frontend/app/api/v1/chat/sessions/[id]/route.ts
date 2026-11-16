import { getServerApiBaseUrl } from "../../_backend";
import { proxyRoute } from "../../../_proxy";

export const GET = proxyRoute({
  method: "GET",
  target: (_request, { id }: { id: string }) =>
    `${getServerApiBaseUrl()}/api/v1/chat/sessions/${encodeURIComponent(id)}`,
  errorMessage: "获取会话信息失败，请稍后重试",
  forwardTenant: true,
  acceptJson: true,
});

export const DELETE = proxyRoute({
  method: "DELETE",
  target: (_request, { id }: { id: string }) =>
    `${getServerApiBaseUrl()}/api/v1/chat/sessions/${encodeURIComponent(id)}`,
  errorMessage: "删除会话失败，请稍后重试",
  forwardTenant: true,
  acceptJson: true,
});
