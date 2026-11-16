import { getServerApiBaseUrl } from "../../chat/_backend";
import { proxyRoute } from "../../_proxy";

// File uploads use the presigned URL flow:
// POST /api/v1/library/files/upload-url -> PUT to storage -> POST /api/v1/library/files/complete-upload
export const GET = proxyRoute({
  method: "GET",
  target: (request) =>
    `${getServerApiBaseUrl()}/api/v1/library/files${new URL(request.url).search}`,
  errorMessage: "获取资料库文件列表失败，请稍后重试",
  forwardTenant: true,
  acceptJson: true,
});
