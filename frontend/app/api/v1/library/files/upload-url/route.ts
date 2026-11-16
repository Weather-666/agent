import { getServerApiBaseUrl } from "../../../chat/_backend";
import { proxyRoute } from "../../../_proxy";

export const POST = proxyRoute({
  method: "POST",
  target: () => `${getServerApiBaseUrl()}/api/v1/library/files/upload-url`,
  errorMessage: "获取资料库文件上传地址失败，请稍后重试",
  forwardTenant: true,
  acceptJson: true,
});
