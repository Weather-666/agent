import { getServerApiBaseUrl } from "../../chat/_backend";
import { proxyRoute } from "../../_proxy";

export const GET = proxyRoute({
  method: "GET",
  target: () => `${getServerApiBaseUrl()}/api/v1/library/spaces`,
  errorMessage: "获取存储空间信息失败，请稍后重试",
  forwardTenant: true,
  acceptJson: true,
});
