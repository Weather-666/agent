import request, { getAccessToken, requestData } from "../request";

export type Skill = {
  id: string;
  slug: string;
  name: string;
  description: string;
  version?: string | null;
  allowedTools?: string[];
  filePaths?: string[];
  tags?: string[];
  storageUri?: string;
  createdAt?: string;
  updatedAt?: string;
};

export type SkillsResponse = {
  items: Skill[];
  total: number;
  limit: number;
  offset: number;
  hasMore: boolean;
};

export type GetSkillsParams = {
  search?: string;
  tags?: string[];
  limit?: number;
  offset?: number;
};

export type UpdateSkillParams = Partial<{
  name: string;
  description: string;
  version: string;
  allowedTools: string[];
  tags: string[];
}>;

function authHeaders() {
  const accessToken = getAccessToken();
  return accessToken ? { Authorization: `Bearer ${accessToken}` } : {};
}

export function getSkills(params: GetSkillsParams = {}, _client: typeof request = request) {
  const searchParams = new URLSearchParams();

  if (params.search) searchParams.set("search", params.search);
  if (params.tags?.length) searchParams.set("tags", params.tags.join(","));
  if (typeof params.limit === "number") searchParams.set("limit", String(params.limit));
  if (typeof params.offset === "number") searchParams.set("offset", String(params.offset));

  const query = searchParams.toString();
  const url = `/api/v1/skills${query ? `?${query}` : ""}`;

  return requestData(
    _client.get<SkillsResponse>(url, {
      headers: authHeaders(),
    })
  );
}

export function uploadSkill(file: File, slug?: string, _client: typeof request = request) {
  const formData = new FormData();
  formData.append("file", file);

  if (slug?.trim()) {
    formData.append("slug", slug.trim());
  }

  return requestData(
    _client.post<Skill>("/api/v1/skills", formData, {
      headers: authHeaders(),
    })
  );
}

export function getSkill(slug: string, _client: typeof request = request) {
  return requestData(
    _client.get<Skill>(`/api/v1/skills/${encodeURIComponent(slug)}`, {
      headers: authHeaders(),
    })
  );
}

export function updateSkill(slug: string, data: UpdateSkillParams, _client: typeof request = request) {
  return requestData(
    _client.put<Skill>(`/api/v1/skills/${encodeURIComponent(slug)}`, data, {
      headers: authHeaders(),
    })
  );
}

export function deleteSkill(slug: string, deleteFiles = false, _client: typeof request = request) {
  const query = new URLSearchParams({ delete_files: String(deleteFiles) });

  return requestData(
    _client.delete<void>(`/api/v1/skills/${encodeURIComponent(slug)}?${query}`, {
      headers: authHeaders(),
    })
  );
}

export async function getSkillFileText(slug: string, path = "SKILL.md", _client: typeof request = request) {
  const query = new URLSearchParams({ path });
  const response = await _client.get<string>(
    `/api/v1/skills/${encodeURIComponent(slug)}/file?${query}`,
    {
      headers: authHeaders(),
      responseType: "text",
      transformResponse: [(data) => data],
    }
  );

  return response.data;
}
