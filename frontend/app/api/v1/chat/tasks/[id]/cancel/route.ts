import { getServerApiBaseUrl } from "../../../_backend";
import { proxyRoute } from "../../../../_proxy";

export const POST = proxyRoute({
  method: "POST",
  target: (_request, { id }: { id: string }) =>
    `${getServerApiBaseUrl()}/api/v1/chat/tasks/${encodeURIComponent(id)}/cancel`,
  errorMessage: "取消问答任务失败，请稍后重试",
  forwardTenant: true,
  acceptJson: true,
});
