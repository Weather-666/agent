import { getServerApiBaseUrl } from "../../_backend";
import { proxyRoute } from "../../../_proxy";

export const POST = proxyRoute({
  method: "POST",
  target: (_request, { id }: { id: string }) =>
    `${getServerApiBaseUrl()}/api/v1/chat/permissions/${encodeURIComponent(id)}`,
  errorMessage: "提交权限确认失败，请稍后重试",
  forwardTenant: true,
});
