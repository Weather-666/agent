// Types re-exported from the API client for use in the admin featured page.
// Mock data has been removed; data is now loaded from the backend API.
export type {
  CategoryTone,
  ExampleStatus,
  ReviewState,
  AdminFeaturedCategory as FeaturedCategory,
  AdminFeaturedExample as FeaturedExample,
  AdminFeaturedCounts as FeaturedCounts,
} from "@/lib/api/admin-client";

export { CATEGORY_TONES } from "./_constants";
