import request, { getAccessToken, requestData } from "../request";

export type ExpertCategory = {
  id: string;
  name: string;
  description?: string | null;
  createdAt?: string;
  updatedAt?: string;
};

export type ExpertCategoriesResponse = {
  items: ExpertCategory[];
};

export type CreateExpertCategoryParams = {
  name: string;
  description?: string | null;
};

export type UpdateExpertCategoryParams = Partial<CreateExpertCategoryParams>;

function authHeaders() {
  const accessToken = getAccessToken();
  return accessToken ? { Authorization: `Bearer ${accessToken}` } : {};
}

export function getExpertCategories(_client: typeof request = request) {
  return requestData(
    _client.get<ExpertCategoriesResponse>("/api/v1/expert-categories", {
      headers: authHeaders(),
    })
  );
}

export function createExpertCategory(data: CreateExpertCategoryParams, _client: typeof request = request) {
  return requestData(
    _client.post<ExpertCategory>("/api/v1/expert-categories", data, {
      headers: authHeaders(),
    })
  );
}

export function updateExpertCategory(categoryId: string, data: UpdateExpertCategoryParams, _client: typeof request = request) {
  return requestData(
    _client.patch<ExpertCategory>(
      `/api/v1/expert-categories/${encodeURIComponent(categoryId)}`,
      data,
      { headers: authHeaders() }
    )
  );
}

export function deleteExpertCategory(categoryId: string, _client: typeof request = request) {
  return requestData(
    _client.delete<void>(
      `/api/v1/expert-categories/${encodeURIComponent(categoryId)}`,
      { headers: authHeaders() }
    )
  );
}
