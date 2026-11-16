import request, { getAccessToken, requestData } from "../request";
import type { LocalizedExpertContent, MarketLabel } from "./experts";

export type { MarketLabel };

export type ExpertMarketCategory = {
  id: string;
  name: string;
  description?: string | null;
  createdAt?: string;
  updatedAt?: string;
};

export type ExpertMarketExpert = {
  id: string;
  name: string;
  categoryId: string;
  categoryName: string;
  abilityIntro: string;
  localizedContent?: Record<string, LocalizedExpertContent>;
  tags?: string[];
  status?: "published";
  skillIds?: string[];
  knowledgeBaseIds?: string[];
  guideQuestions?: string[];
  marketLabels?: MarketLabel[];
  summonButtonText?: string | null;
  isAccessible: boolean;
  createdAt?: string;
  updatedAt?: string;
};

export type ExpertMarketExpertsResponse = {
  items: ExpertMarketExpert[];
};

export type ExpertMarketCategoriesResponse = {
  items: ExpertMarketCategory[];
};

function authHeaders() {
  const accessToken = getAccessToken();
  return accessToken ? { Authorization: `Bearer ${accessToken}` } : {};
}

export function getExpertMarketExperts() {
  return requestData(
    request.get<ExpertMarketExpertsResponse>("/api/v1/expert-market/experts", {
      headers: authHeaders(),
    })
  );
}

export function getExpertMarketCategories() {
  return requestData(
    request.get<ExpertMarketCategoriesResponse>("/api/v1/expert-market/categories", {
      headers: authHeaders(),
    })
  );
}

export function getExpertMarketExpert(expertId: string) {
  return requestData(
    request.get<ExpertMarketExpert>(
      `/api/v1/expert-market/experts/${encodeURIComponent(expertId)}`,
      {
        headers: authHeaders(),
      }
    )
  );
}
