import { getServerApiBaseUrl } from "../../../chat/_backend";
import { proxyRoute } from "../../../_proxy";

export const POST = proxyRoute({
  method: "POST",
  target: () => `${getServerApiBaseUrl()}/api/v1/library/files/complete-upload`,
  errorMessage: "确认资料库文件上传失败，请稍后重试",
  forwardTenant: true,
  acceptJson: true,
});
