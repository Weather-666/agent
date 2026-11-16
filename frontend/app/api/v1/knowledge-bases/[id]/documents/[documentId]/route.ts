import { getServerApiBaseUrl } from "../../../../chat/_backend";
import { proxyRoute } from "../../../../_proxy";

const target = (
  _request: Request,
  { id, documentId }: { id: string; documentId: string },
) =>
  `${getServerApiBaseUrl()}/api/v1/knowledge-bases/${encodeURIComponent(id)}/docs/${encodeURIComponent(documentId)}`;

export const GET = proxyRoute({
  method: "GET",
  target,
  errorMessage: "获取文档详情失败，请稍后重试",
});

export const PATCH = proxyRoute({
  method: "PATCH",
  target,
  errorMessage: "更新文档失败，请稍后重试",
});

export const DELETE = proxyRoute({
  method: "DELETE",
  target,
  errorMessage: "删除文档失败，请稍后重试",
});
