import request, { getAccessToken, requestData } from "../request";

export type ExpertStatus = "published" | "draft" | "unlisted";

export type MarketLabel = "hot";

export type ExpertRuntimeConfig = {
  enabled?: boolean;
  model?: string | null;
  maxInstances?: number | null;
  idleTtlSeconds?: number | null;
  turnTimeoutSeconds?: number | null;
  permissionMode?: "deny" | "auto_approve" | "interactive";
  requireVirtualKey?: boolean;
  environment?: Record<string, { secretRef: string }>;
};

export type SkillRuntimeTarget = {
  skillId: string;
  runtimes: string[];
};

export type LocalizedExpertContent = {
  name?: string | null;
  abilityIntro?: string | null;
  categoryName?: string | null;
  summonButtonText?: string | null;
};

export type Expert = {
  id: string;
  name: string;
  categoryId: string;
  categoryName: string;
  abilityIntro: string;
  localizedContent?: Record<string, LocalizedExpertContent>;
  instructions?: string | null;
  tags: string[];
  status: ExpertStatus;
  skillIds: string[];
  knowledgeBaseIds: string[];
  guideQuestions: string[];
  marketLabels: MarketLabel[];
  summonButtonText?: string | null;
  runtimeConfig?: { codex?: ExpertRuntimeConfig; opencode?: ExpertRuntimeConfig };
  skillRuntimeTargets?: SkillRuntimeTarget[];
  mcpConnectorIds?: string[];
  createdAt?: string;
  updatedAt?: string;
};

export type ExpertsResponse = {
  items: Expert[];
};

export type CreateExpertParams = {
  name: string;
  categoryId: string;
  abilityIntro: string;
  localizedContent?: Record<string, LocalizedExpertContent>;
  instructions?: string | null;
  tags?: string[];
  skillIds?: string[];
  knowledgeBaseIds?: string[];
  guideQuestions?: string[];
  marketLabels?: MarketLabel[];
  summonButtonText?: string | null;
  runtimeConfig?: { codex?: ExpertRuntimeConfig; opencode?: ExpertRuntimeConfig };
  skillRuntimeTargets?: SkillRuntimeTarget[];
  mcpConnectorIds?: string[];
};

export type UpdateExpertParams = Partial<CreateExpertParams>;
export type UpdateExpertStatusParams = { status: "published" | "unlisted" };

function authHeaders() {
  const accessToken = getAccessToken();
  return accessToken ? { Authorization: `Bearer ${accessToken}` } : {};
}

export function getExperts(_client: typeof request = request) {
  return requestData(
    _client.get<ExpertsResponse>("/api/v1/experts", {
      headers: authHeaders(),
    })
  );
}

export function getExpert(expertId: string, _client: typeof request = request) {
  return requestData(
    _client.get<Expert>(`/api/v1/experts/${encodeURIComponent(expertId)}`, {
      headers: authHeaders(),
    })
  );
}

export function searchExpertsByName(name: string, _client: typeof request = request) {
  const query = new URLSearchParams({ name });

  return requestData(
    _client.get<ExpertsResponse>(`/api/v1/experts/search/name?${query}`, {
      headers: authHeaders(),
    })
  );
}

export function searchExpertsByCategory(categoryId: string, _client: typeof request = request) {
  const query = new URLSearchParams({ categoryId });

  return requestData(
    _client.get<ExpertsResponse>(`/api/v1/experts/search/category?${query}`, {
      headers: authHeaders(),
    })
  );
}

export function searchExpertsByStatus(status: ExpertStatus, _client: typeof request = request) {
  const query = new URLSearchParams({ status });

  return requestData(
    _client.get<ExpertsResponse>(`/api/v1/experts/search/status?${query}`, {
      headers: authHeaders(),
    })
  );
}

export function createExpert(data: CreateExpertParams, _client: typeof request = request) {
  return requestData(
    _client.post<Expert>("/api/v1/experts", data, {
      headers: authHeaders(),
    })
  );
}

export function updateExpert(expertId: string, data: UpdateExpertParams, _client: typeof request = request) {
  return requestData(
    _client.patch<Expert>(`/api/v1/experts/${encodeURIComponent(expertId)}`, data, {
      headers: authHeaders(),
    })
  );
}

export function deleteExpert(expertId: string, _client: typeof request = request) {
  return requestData(
    _client.delete<void>(`/api/v1/experts/${encodeURIComponent(expertId)}`, {
      headers: authHeaders(),
    })
  );
}

export function updateExpertStatus(expertId: string, status: "published" | "unlisted", _client: typeof request = request) {
  return requestData(
    _client.patch<Expert>(
      `/api/v1/experts/${encodeURIComponent(expertId)}/status`,
      { status },
      {
        headers: authHeaders(),
        // Publishing may take longer than the default timeout; 0 = no client timeout.
        // Unlisting and other status changes keep the default.
        timeout: status === "published" ? 0 : undefined,
      }
    )
  );
}
