import { expertSearchRoute } from "../_search";

export const GET = expertSearchRoute({
  param: "categoryId",
  segment: "category",
  invalidMessage: "categoryId is required",
  errorMessage: "按分类搜索专家失败，请稍后重试",
});
