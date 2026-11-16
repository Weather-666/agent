import { expertSearchRoute } from "../_search";

export const GET = expertSearchRoute({
  param: "name",
  segment: "name",
  invalidMessage: "name is required",
  errorMessage: "搜索专家名称失败，请稍后重试",
});
