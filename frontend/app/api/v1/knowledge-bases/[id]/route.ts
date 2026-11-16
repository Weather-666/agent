import { getServerApiBaseUrl } from "../../chat/_backend";
import { proxyRoute } from "../../_proxy";

const target = (_request: Request, { id }: { id: string }) =>
  `${getServerApiBaseUrl()}/api/v1/knowledge-bases/${encodeURIComponent(id)}`;

export const GET = proxyRoute({
  method: "GET",
  target,
  errorMessage: "获取知识库详情失败，请稍后重试",
});

export const PATCH = proxyRoute({
  method: "PATCH",
  target,
  errorMessage: "更新知识库失败，请稍后重试",
});

export const DELETE = proxyRoute({
  method: "DELETE",
  target,
  errorMessage: "删除知识库失败，请稍后重试",
});
