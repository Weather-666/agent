import { getServerApiBaseUrl } from "../../chat/_backend";
import { proxyRoute } from "../../_proxy";

const target = (_request: Request, { userId }: { userId: string }) =>
  `${getServerApiBaseUrl()}/api/v1/users/${encodeURIComponent(userId)}`;

export const GET = proxyRoute({
  method: "GET",
  target,
  errorMessage: "获取用户详情失败，请稍后重试",
});

export const PATCH = proxyRoute({
  method: "PATCH",
  target,
  errorMessage: "更新用户信息失败，请稍后重试",
});
