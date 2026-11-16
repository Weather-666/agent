import request, { getAccessToken, requestData } from "../request";

export type PlanStatus = "active" | "disabled";
export type BillingPeriod = "free" | "monthly" | "yearly" | "sales";

export type PlanPrice = {
  id: string;
  planId: string;
  billingPeriod: BillingPeriod;
  currency: string;
  amountCents: number;
  discountLabel?: string | null;
  isEnabled: boolean;
  createdAt?: string;
  updatedAt?: string;
};

export type LocalizedPlanContent = {
  subtitle?: string | null;
  description?: string | null;
  badgeLabel?: string | null;
  highlightItems: string[];
};

export type PlanEntitlements = {
  id: string;
  planId: string;
  monthlyCreditLimit: number;
  allExperts: boolean;
  seatLimit: number;
  singleTurnTokenLimit?: number | null;
  modelTiers: string[];
  features: Record<string, unknown>;
  createdAt?: string;
  updatedAt?: string;
};

export type Plan = {
  id: string;
  code: string;
  name: string;
  level: number;
  description: string;
  typeLabel?: string | null;
  subtitle?: string | null;
  badgeLabel?: string | null;
  highlightItems?: string[];
  localizedContent?: Partial<Record<"zh" | "en", LocalizedPlanContent>>;
  upgradeRules?: string[];
  status: PlanStatus;
  isRecommended: boolean;
  sortOrder: number;
  prices: PlanPrice[];
  entitlements: PlanEntitlements | null;
  expertIds: string[];
  subscriberCount?: number | null;
  subscriptionCount?: number | null;
  subscribedUserCount?: number | null;
  subscribedTenantCount?: number | null;
  subscriberTenantCount?: number | null;
  activeSubscriptionCount?: number | null;
  tenantCount?: number | null;
  createdAt?: string;
  updatedAt?: string;
};

export type PlansResponse = {
  items: Plan[];
};

export type CreatePlanParams = {
  code?: string;
  name: string;
  level: number;
  description: string;
  typeLabel?: string | null;
  subtitle?: string | null;
  badgeLabel?: string | null;
  highlightItems?: string[];
  localizedContent?: Partial<Record<"zh" | "en", LocalizedPlanContent>>;
  upgradeRules?: string[];
  status?: PlanStatus;
  isRecommended?: boolean;
  sortOrder?: number;
};

export type UpdatePlanParams = Partial<CreatePlanParams>;

export type ReplacePlanPricesParams = {
  items: Array<{
    billingPeriod: BillingPeriod;
    currency: string;
    amountCents: number;
    discountLabel?: string | null;
    isEnabled?: boolean;
  }>;
};

export type ReplacePlanEntitlementsParams = {
  monthlyCreditLimit: number;
  allExperts: boolean;
  seatLimit: number;
  singleTurnTokenLimit?: number | null;
  modelTiers?: string[];
  features?: Record<string, unknown>;
};

export type ReplacePlanExpertsParams = {
  expertIds: string[];
};

function authHeaders() {
  const accessToken = getAccessToken();
  return accessToken ? { Authorization: `Bearer ${accessToken}` } : {};
}

export function getPlans(_client: typeof request = request) {
  return requestData(
    _client.get<PlansResponse>("/api/v1/plans", {
      headers: authHeaders(),
    })
  );
}

export function createPlan(data: CreatePlanParams, _client: typeof request = request) {
  return requestData(
    _client.post<Plan>("/api/v1/plans", data, {
      headers: authHeaders(),
    })
  );
}

export function updatePlan(planId: string, data: UpdatePlanParams, _client: typeof request = request) {
  return requestData(
    _client.patch<Plan>(`/api/v1/plans/${encodeURIComponent(planId)}`, data, {
      headers: authHeaders(),
    })
  );
}

export function deletePlan(planId: string, _client: typeof request = request) {
  return requestData(
    _client.delete<void>(`/api/v1/plans/${encodeURIComponent(planId)}`, {
      headers: authHeaders(),
    })
  );
}

export function replacePlanPrices(planId: string, data: ReplacePlanPricesParams, _client: typeof request = request) {
  return requestData(
    _client.put<Plan>(`/api/v1/plans/${encodeURIComponent(planId)}/prices`, data, {
      headers: authHeaders(),
    })
  );
}

export function replacePlanEntitlements(planId: string, data: ReplacePlanEntitlementsParams, _client: typeof request = request) {
  return requestData(
    _client.put<Plan>(`/api/v1/plans/${encodeURIComponent(planId)}/entitlements`, data, {
      headers: authHeaders(),
    })
  );
}

export function replacePlanExperts(planId: string, data: ReplacePlanExpertsParams, _client: typeof request = request) {
  return requestData(
    _client.put<Plan>(`/api/v1/plans/${encodeURIComponent(planId)}/experts`, data, {
      headers: authHeaders(),
    })
  );
}
