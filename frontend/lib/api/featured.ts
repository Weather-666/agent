import request, { getAccessToken, requestData } from "../request";

export type CategoryTone = "blue" | "green" | "violet" | "orange";
export type ExampleStatus = "pending" | "live" | "rejected" | "reviewing" | "unlisted";
export type ReviewState = "normal" | "expiring" | "expired" | "none";

// ---- User-facing types ----

export type FeaturedMarketItem = {
  id: string;
  question: string;
  categoryId: string;
  categoryName: string;
  categoryTone: CategoryTone;
  sortOrder: number;
  clickCount: number;
};

export type FeaturedMarketListResponse = { items: FeaturedMarketItem[] };

export type FeaturedMarketUseResponse = {
  id: string;
  question: string;
  clickCount: number;
};

// ---- Admin types ----

export type AdminFeaturedCategory = {
  id: string;
  name: string;
  short: string;
  tone: CategoryTone;
  sortOrder: number;
  createdAt: string;
  updatedAt: string;
};

export type AdminFeaturedCounts = {
  total: number;
  live: number;
  pending: number;
  reviewing: number;
  rejected: number;
  unlisted: number;
  expiring: number;
  expired: number;
};

export type AdminFeaturedExample = {
  id: string;
  categoryId: string;
  question: string;
  sortOrder: number;
  status: ExampleStatus;
  reviewCycleDays: number | null;
  reviewedAt: string | null;
  expiresAt: string | null;
  reviewState: ReviewState;
  rejectReason: string | null;
  clickCount: number;
  createdBy: string | null;
  authorName: string | null;
  updatedBy: string | null;
  reviewedBy: string | null;
  createdAt: string;
  updatedAt: string;
};

export type AdminFeaturedExamplesResponse = {
  items: AdminFeaturedExample[];
  counts: AdminFeaturedCounts;
};

export type AdminFeaturedCategoriesResponse = { items: AdminFeaturedCategory[] };

// ---- Helpers ----

function authHeaders() {
  const accessToken = getAccessToken();
  return accessToken ? { Authorization: `Bearer ${accessToken}` } : {};
}

// ---- User-facing API ----

export function getFeaturedMarketExamples(categoryId?: string, _client: typeof request = request) {
  const params = categoryId ? `?categoryId=${encodeURIComponent(categoryId)}` : "";
  return requestData(
    _client.get<FeaturedMarketListResponse>(`/api/v1/featured-market/examples${params}`, {
      headers: authHeaders(),
    })
  );
}

export function useFeaturedMarketExample(id: string, _client: typeof request = request) {
  return requestData(
    _client.post<FeaturedMarketUseResponse>(
      `/api/v1/featured-market/examples/${encodeURIComponent(id)}/use`,
      {},
      { headers: authHeaders() }
    )
  );
}

// ---- Admin categories API ----

export function adminGetFeaturedCategories(_client: typeof request = request) {
  return requestData(
    _client.get<AdminFeaturedCategoriesResponse>("/api/v1/featured-categories", {
      headers: authHeaders(),
    })
  );
}

export function adminCreateFeaturedCategory(data: { name: string; tone: CategoryTone }, _client: typeof request = request) {
  return requestData(
    _client.post<AdminFeaturedCategory>("/api/v1/featured-categories", data, {
      headers: authHeaders(),
    })
  );
}

export function adminUpdateFeaturedCategory(id: string, data: { name?: string; tone?: CategoryTone }, _client: typeof request = request) {
  return requestData(
    _client.patch<AdminFeaturedCategory>(
      `/api/v1/featured-categories/${encodeURIComponent(id)}`,
      data,
      { headers: authHeaders() }
    )
  );
}

export function adminDeleteFeaturedCategory(id: string, _client: typeof request = request) {
  return _client.delete(`/api/v1/featured-categories/${encodeURIComponent(id)}`, {
    headers: authHeaders(),
  });
}

export function adminReorderFeaturedCategories(ids: string[], _client: typeof request = request) {
  return requestData(
    _client.put<AdminFeaturedCategoriesResponse>("/api/v1/featured-categories/order", { ids }, {
      headers: authHeaders(),
    })
  );
}

// ---- Admin examples API ----

export type AdminExamplesParams = {
  categoryId?: string;
  status?: ExampleStatus | "all";
  reviewState?: ReviewState | "all";
  keyword?: string;
};

export function adminGetFeaturedExamples(params?: AdminExamplesParams, _client: typeof request = request) {
  const qs = new URLSearchParams();
  if (params?.categoryId) qs.set("categoryId", params.categoryId);
  if (params?.status && params.status !== "all") qs.set("status", params.status);
  if (params?.reviewState && params.reviewState !== "all") qs.set("reviewState", params.reviewState);
  if (params?.keyword) qs.set("keyword", params.keyword);
  const search = qs.toString() ? `?${qs.toString()}` : "";
  return requestData(
    _client.get<AdminFeaturedExamplesResponse>(`/api/v1/featured-examples${search}`, {
      headers: authHeaders(),
    })
  );
}

export function adminCreateFeaturedExample(data: {
  categoryId: string;
  question: string;
  reviewCycleDays: number | null;
}, _client: typeof request = request) {
  return requestData(
    _client.post<AdminFeaturedExample>("/api/v1/featured-examples", data, {
      headers: authHeaders(),
    })
  );
}

export function adminGetFeaturedExample(id: string, _client: typeof request = request) {
  return requestData(
    _client.get<AdminFeaturedExample>(`/api/v1/featured-examples/${encodeURIComponent(id)}`, {
      headers: authHeaders(),
    })
  );
}

export function adminUpdateFeaturedExample(
  id: string,
  data: { categoryId?: string; question?: string; reviewCycleDays?: number | null },
  _client: typeof request = request
) {
  return requestData(
    _client.patch<AdminFeaturedExample>(
      `/api/v1/featured-examples/${encodeURIComponent(id)}`,
      data,
      { headers: authHeaders() }
    )
  );
}

export function adminDeleteFeaturedExample(id: string, _client: typeof request = request) {
  return _client.delete(`/api/v1/featured-examples/${encodeURIComponent(id)}`, {
    headers: authHeaders(),
  });
}

export function adminReorderCategoryExamples(categoryId: string, ids: string[], _client: typeof request = request) {
  return requestData(
    _client.put<AdminFeaturedExamplesResponse>(
      `/api/v1/featured-categories/${encodeURIComponent(categoryId)}/examples/order`,
      { ids },
      { headers: authHeaders() }
    )
  );
}

export function adminReviewFeaturedExample(
  id: string,
  data: { decision: "approve" | "reject"; expectedUpdatedAt: string; reason?: string },
  _client: typeof request = request
) {
  return requestData(
    _client.post<AdminFeaturedExample>(
      `/api/v1/featured-examples/${encodeURIComponent(id)}/review`,
      data,
      { headers: authHeaders() }
    )
  );
}

export function adminUnlistFeaturedExample(id: string, _client: typeof request = request) {
  return requestData(
    _client.post<AdminFeaturedExample>(
      `/api/v1/featured-examples/${encodeURIComponent(id)}/unlist`,
      {},
      { headers: authHeaders() }
    )
  );
}
