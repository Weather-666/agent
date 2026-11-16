import request, { getAccessToken, requestData } from "../request";

export type TenantType = "personal" | "team" | string;
export type TenantStatus = "active" | "disabled" | string;
export type SubscriptionStatus = "active" | "expiring_soon" | "expired" | "trialing" | "past_due" | "cancelled" | string;
export type BillingPeriod = "free" | "monthly" | "yearly" | "sales" | string;

export type TenantSubscription = {
  subscriptionId?: string | null;
  planId?: string | null;
  planCode?: string | null;
  planName?: string | null;
  billingPeriod?: BillingPeriod | null;
  status?: SubscriptionStatus | null;
  rawStatus?: string | null;
  currentPeriodStart?: string | null;
  currentPeriodEnd?: string | null;
  daysUntilExpiry?: number | null;
  cancelAtPeriodEnd?: boolean | null;
  autoRenew?: boolean | null;
  priceLabel?: string | null;
};

export type TenantPlan = {
  id?: string | null;
  code?: string | null;
  name?: string | null;
  typeLabel?: string | null;
  billingPeriod?: BillingPeriod | null;
  priceLabel?: string | null;
  priceSnapshot?: unknown;
  entitlementsSnapshot?: unknown;
};

export type TenantMonthlyCredits = {
  monthlyCreditLimit: number;
  estimatedUsedCredits: number;
  deductedCredits: number;
  remainingCredits: number;
  enforcementEnabled: boolean;
};

export type TenantCreditSummary = TenantMonthlyCredits & {
  ledgerBalance?: number | null;
  overdrawnCredits?: number | null;
};

export type TenantCreditLedgerEntry = {
  id: string;
  periodId: string;
  tenantId: string;
  beneficiaryUserId?: string | null;
  entryType: "monthly_grant" | "upgrade_grant" | "turn_charge" | "manual_adjustment";
  amount: number;
  referenceId?: string | null;
  idempotencyKey?: string | null;
  actorUserId?: string | null;
  reason?: string | null;
  createdAt: string;
};

export type TenantCreditLedgerResponse = {
  items: TenantCreditLedgerEntry[];
  total: number;
  page: number;
  pageSize: number;
};

export type TenantOrderSummary = {
  totalAmountCents: number;
  orderCount: number;
  recentOrders: Array<{
    orderNo?: string | null;
    planName?: string | null;
    billingPeriod?: BillingPeriod | null;
    amountCents?: number | null;
    paidAt?: string | null;
    status?: string | null;
  }>;
};

export type TenantMember = {
  userId: string;
  email: string;
  name?: string | null;
  status: "pending_activation" | "active" | "disabled" | string;
  role: "owner" | "admin" | "member" | string;
  joinedAt: string;
};

export type Tenant = {
  id: string;
  type: TenantType;
  name: string;
  slug: string;
  ownerUserId?: string | null;
  ownerUserName?: string | null;
  ownerUserEmail?: string | null;
  status: TenantStatus;
  memberCount: number;
  currentSubscription?: TenantSubscription | null;
  currentPlan?: TenantPlan | null;
  monthlyCredits?: TenantMonthlyCredits | null;
  orderSummary?: TenantOrderSummary | null;
  members?: TenantMember[];
  createdAt: string;
  updatedAt: string;
};

export type GetTenantsParams = {
  search?: string;
  type?: "personal" | "team";
  subscriptionType?: string;
  subscriptionStatus?: string;
  sort?: string;
  page?: number;
  pageSize?: number;
};

export type TenantsResponse = {
  items: Tenant[];
  total: number;
  page: number;
  pageSize: number;
};

export type TenantMembersResponse = { items: TenantMember[] };

export type CreateTenantParams = {
  name: string;
  slug?: string;
  ownerUserId: string;
};

export type UpdateTenantParams = Partial<CreateTenantParams>;
export type UpdateTenantStatusParams = { status: "active" | "disabled" };
export type UpdateTenantSubscriptionParams = {
  planId: string;
  billingPeriod: "free" | "monthly" | "yearly" | "sales";
  status: "active" | "trialing" | "past_due" | "cancelled" | "expired";
  currentPeriodStart?: string;
  currentPeriodEnd?: string;
  cancelAtPeriodEnd?: boolean;
};
export type AddTenantMemberParams = { userId: string; role?: "admin" | "member" };
export type UpdateTenantMemberParams = { role: "admin" | "member" };

function authHeaders() {
  const accessToken = getAccessToken();
  return accessToken ? { Authorization: `Bearer ${accessToken}` } : {};
}

export function getTenants(params?: GetTenantsParams, _client: typeof request = request) {
  return requestData(
    _client.get<TenantsResponse>("/api/v1/tenants", {
      headers: authHeaders(),
      params,
    })
  );
}

export function getTenant(tenantId: string, _client: typeof request = request) {
  return requestData(
    _client.get<Tenant>(`/api/v1/tenants/${encodeURIComponent(tenantId)}`, {
      headers: authHeaders(),
    })
  );
}

export function createTenant(data: CreateTenantParams, _client: typeof request = request) {
  return requestData(
    _client.post<Tenant>("/api/v1/tenants", data, {
      headers: authHeaders(),
    })
  );
}

export function updateTenant(tenantId: string, data: UpdateTenantParams, _client: typeof request = request) {
  return requestData(
    _client.patch<Tenant>(`/api/v1/tenants/${encodeURIComponent(tenantId)}`, data, {
      headers: authHeaders(),
    })
  );
}

export function updateTenantStatus(tenantId: string, data: UpdateTenantStatusParams, _client: typeof request = request) {
  return requestData(
    _client.patch<Tenant>(`/api/v1/tenants/${encodeURIComponent(tenantId)}/status`, data, {
      headers: authHeaders(),
    })
  );
}

export function updateTenantSubscription(tenantId: string, data: UpdateTenantSubscriptionParams, _client: typeof request = request) {
  return requestData(
    _client.patch<Tenant>(`/api/v1/tenants/${encodeURIComponent(tenantId)}/subscription`, data, {
      headers: authHeaders(),
    })
  );
}

export function getTenantMembers(tenantId: string, _client: typeof request = request) {
  return requestData(
    _client.get<TenantMembersResponse>(`/api/v1/tenants/${encodeURIComponent(tenantId)}/members`, {
      headers: authHeaders(),
    })
  );
}

export function addTenantMember(tenantId: string, data: AddTenantMemberParams, _client: typeof request = request) {
  return requestData(
    _client.post<TenantMember>(`/api/v1/tenants/${encodeURIComponent(tenantId)}/members`, data, {
      headers: authHeaders(),
    })
  );
}

export function updateTenantMember(tenantId: string, userId: string, data: UpdateTenantMemberParams, _client: typeof request = request) {
  return requestData(
    _client.patch<TenantMember>(
      `/api/v1/tenants/${encodeURIComponent(tenantId)}/members/${encodeURIComponent(userId)}`,
      data,
      {
        headers: authHeaders(),
      }
    )
  );
}

export function removeTenantMember(tenantId: string, userId: string, _client: typeof request = request) {
  return requestData(
    _client.delete<void>(
      `/api/v1/tenants/${encodeURIComponent(tenantId)}/members/${encodeURIComponent(userId)}`,
      {
        headers: authHeaders(),
      }
    )
  );
}

export type GetTenantCreditsParams = { userId?: string };
export type GetTenantCreditLedgerParams = { page?: number; pageSize?: number; userId?: string };
export type CreateCreditAdjustmentParams = { amount: number; reason: string; userId?: string };

export function getTenantCredits(tenantId: string, params?: GetTenantCreditsParams, _client: typeof request = request) {
  return requestData(
    _client.get<TenantCreditSummary>(`/api/v1/tenants/${encodeURIComponent(tenantId)}/credits/current`, {
      headers: authHeaders(),
      params,
    })
  );
}

export function getTenantCreditLedger(tenantId: string, params?: GetTenantCreditLedgerParams, _client: typeof request = request) {
  return requestData(
    _client.get<TenantCreditLedgerResponse>(`/api/v1/tenants/${encodeURIComponent(tenantId)}/credits/ledger`, {
      headers: authHeaders(),
      params,
    })
  );
}

export function createCreditAdjustment(tenantId: string, data: CreateCreditAdjustmentParams, idempotencyKey: string, _client: typeof request = request) {
  return requestData(
    _client.post<TenantCreditLedgerEntry>(
      `/api/v1/tenants/${encodeURIComponent(tenantId)}/credits/adjustments`,
      data,
      {
        headers: {
          ...authHeaders(),
          "Idempotency-Key": idempotencyKey,
        },
      }
    )
  );
}
