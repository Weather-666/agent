import { getServerApiBaseUrl } from "../../chat/_backend";
import { proxyRoute } from "../../_proxy";

const target = (_request: Request, { planId }: { planId: string }) =>
  `${getServerApiBaseUrl()}/api/v1/plans/${encodeURIComponent(planId)}`;

export const GET = proxyRoute({
  method: "GET",
  target,
  errorMessage: "获取套餐详情失败，请稍后重试",
});

export const PATCH = proxyRoute({
  method: "PATCH",
  target,
  errorMessage: "更新套餐失败，请稍后重试",
});

export const DELETE = proxyRoute({
  method: "DELETE",
  target,
  errorMessage: "删除套餐失败，请稍后重试",
});
