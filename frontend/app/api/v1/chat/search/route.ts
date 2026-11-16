import { getServerApiBaseUrl } from "../_backend";
import { proxyRoute } from "../../_proxy";

export const GET = proxyRoute({
  method: "GET",
  target: (request) =>
    `${getServerApiBaseUrl()}/api/v1/chat/search${new URL(request.url).search}`,
  errorMessage: "搜索聊天记录失败，请稍后重试",
  forwardTenant: true,
  acceptJson: true,
});
