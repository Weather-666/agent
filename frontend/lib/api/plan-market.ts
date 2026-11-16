import request, { getAccessToken, getTenantId, requestData } from "../request";
import type { Plan } from "./plans";

export type TenantSubscription = {
  id: string;
  tenantId: string;
  planId: string;
  status: string;
  billingPeriod: string;
  currentPeriodStart: string | null;
  currentPeriodEnd: string | null;
  cancelAtPeriodEnd: boolean;
  createdAt: string;
  updatedAt: string;
};

export type CurrentSubscriptionResponse = {
  subscription: TenantSubscription;
  plan: Plan;
};

export type PlanMarketPlansResponse = {
  items: Plan[];
};

function authHeaders() {
  const accessToken = getAccessToken();
  return accessToken ? { Authorization: `Bearer ${accessToken}` } : {};
}

export function getPlanMarketPlans() {
  return requestData(
    request.get<PlanMarketPlansResponse>("/api/v1/plan-market/plans", {
      headers: authHeaders(),
    })
  );
}

export function getCurrentSubscription() {
  const accessToken = getAccessToken();
  const tenantId = getTenantId();

  return requestData(
    request.get<CurrentSubscriptionResponse>("/api/v1/plan-market/current-subscription", {
      headers: {
        ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
        "X-Tenant-ID": tenantId,
      },
    })
  );
}

export function upgradeSubscription(planId: string) {
  const accessToken = getAccessToken();
  const tenantId = getTenantId();

  return requestData(
    request.patch<CurrentSubscriptionResponse>("/api/v1/plan-market/current-subscription", { planId }, {
      headers: {
        ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
        "X-Tenant-ID": tenantId,
      },
    })
  );
}
