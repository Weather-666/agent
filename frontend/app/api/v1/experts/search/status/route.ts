import { expertSearchRoute } from "../_search";

export const GET = expertSearchRoute({
  param: "status",
  segment: "status",
  allowed: new Set(["published", "draft", "unlisted"]),
  invalidMessage: "status must be published, draft, or unlisted",
  errorMessage: "按状态搜索专家失败，请稍后重试",
});
