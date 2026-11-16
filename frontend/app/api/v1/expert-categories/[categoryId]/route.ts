import { getServerApiBaseUrl } from "../../chat/_backend";
import { proxyRoute } from "../../_proxy";

const target = (_request: Request, { categoryId }: { categoryId: string }) =>
  `${getServerApiBaseUrl()}/api/v1/expert-categories/${encodeURIComponent(categoryId)}`;

export const GET = proxyRoute({
  method: "GET",
  target,
  errorMessage: "获取专家分类详情失败，请稍后重试",
});

export const PATCH = proxyRoute({
  method: "PATCH",
  target,
  errorMessage: "更新专家分类失败，请稍后重试",
});

export const DELETE = proxyRoute({
  method: "DELETE",
  target,
  errorMessage: "删除专家分类失败，请稍后重试",
});
