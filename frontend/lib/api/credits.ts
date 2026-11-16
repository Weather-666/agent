import request, { getAccessToken, getTenantId, requestData } from "../request";

export type UserCredits = {
  tenantId: string;
  planId: string;
  planCode: string;
  planName: string;
  periodStart: string;
  periodEnd: string;
  monthlyCreditLimit: number;
  grantedCredits: number;
  adjustmentCredits: number;
  estimatedUsedCredits: number;
  deductedCredits: number;
  remainingCredits: number;
  enforcementEnabled: boolean;
};

export function getCurrentCredits() {
  const accessToken = getAccessToken();
  const tenantId = getTenantId();

  return requestData(
    request.get<UserCredits>("/api/v1/credits/current", {
      headers: {
        ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
        "X-Tenant-ID": tenantId,
      },
    })
  );
}
