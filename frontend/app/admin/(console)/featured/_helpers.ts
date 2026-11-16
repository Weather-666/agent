import type { CategoryTone, ExampleStatus, AdminFeaturedExample as FeaturedExample, ReviewState } from "@/lib/api/admin-client";

export type { AdminFeaturedCounts as FeaturedCounts } from "@/lib/api/admin-client";

export function filterRows(
  rows: FeaturedExample[],
  statusFilter: ExampleStatus | "all",
  reviewFilter: ReviewState | "all",
  keyword: string,
): FeaturedExample[] {
  const kw = keyword.trim().toLowerCase();
  return rows.filter((item) => {
    const matchesStatus = statusFilter === "all" || item.status === statusFilter;
    const matchesReview = reviewFilter === "all" || item.reviewState === reviewFilter;
    const matchesKeyword = !kw || `${item.question} ${item.id}`.toLowerCase().includes(kw);
    return matchesStatus && matchesReview && matchesKeyword;
  });
}

/** antd Tag color for an example status. */
export const STATUS_TAG_COLOR: Record<ExampleStatus, string> = {
  live: "success",
  pending: "warning",
  rejected: "error",
  reviewing: "warning",
  unlisted: "default",
};

/** Dot color (hex) for a review state. */
export const REVIEW_DOT_COLOR: Record<ReviewState, string> = {
  normal: "#1f9d70",
  expiring: "#f79009",
  expired: "#ef4444",
  none: "#c0c6cf",
};

/** Background/foreground for the small circular category mark. */
export const TONE_STYLE: Record<CategoryTone, { bg: string; color: string }> = {
  blue: { bg: "#eef4ff", color: "#2563eb" },
  green: { bg: "#e8f8ef", color: "#16934f" },
  violet: { bg: "#eeeeff", color: "#5146e5" },
  orange: { bg: "#f2f4f7", color: "#667085" },
};

/** Format a review cycle for display. */
export function reviewCycleLabel(days: number | null): string {
  if (days === null) return "长期有效";
  return `${days} 天`;
}
