import { getServerApiBaseUrl } from "../../chat/_backend";
import { proxyRoute } from "../../_proxy";

const target = () => `${getServerApiBaseUrl()}/api/v1/auth/me`;

export const GET = proxyRoute({
  method: "GET",
  target,
  errorMessage: "获取管理员信息失败，请稍后重试",
  forwardTenant: true,
});

export const PATCH = proxyRoute({
  method: "PATCH",
  target,
  errorMessage: "更新个人资料失败，请稍后重试",
  forwardTenant: true,
});
