import request, { getAccessToken, requestData } from "../request";

export type PlatformUser = {
  id: string;
  email: string;
  name?: string | null;
  status?: string;
  activeTenantId?: string | null;
  tenantRoles?: string[];
  tenantPermissions?: string[];
  platformRoles?: string[];
  platformPermissions?: string[];
  createdAt?: string;
  updatedAt?: string;
};

export type PlatformUsersResponse = {
  items: PlatformUser[];
};

export type PlatformRole = {
  role: string;
  name: string;
  permissions: string[];
};

export type PlatformRolesResponse = {
  items: PlatformRole[];
};

export type UserStatus = "pending_activation" | "active" | "disabled" | string;

export type UserTenant = {
  id: string;
  name: string;
  type: "personal" | "team" | string;
  slug: string;
  status: "active" | "disabled" | string;
  role: "admin" | "member" | string;
  joinedAt: string;
};

export type UserSubscriptionSummary = {
  subscriptionId: string;
  planId: string;
  planCode: string;
  planName: string;
  billingPeriod: "free" | "monthly" | "yearly" | string;
  status: "active" | "expiring_soon" | "expired" | string;
  statusLabel: string;
  currentPeriodStart?: string | null;
  currentPeriodEnd?: string | null;
  daysUntilExpiry?: number | null;
  cancelAtPeriodEnd: boolean;
  autoRenew: boolean;
  priceLabel?: string | null;
  currentOrderNo?: string | null;
  paymentMethod?: string | null;
  tenantId?: string | null;
  tenantName?: string | null;
};

export type UserMonthlyUsage = {
  questionUsed: number;
  questionLimit: number;
  tokenUsed: number;
  tokenLimit: number;
  questionUsagePercent: number;
  tokenUsagePercent: number;
  status: "active" | "expiring_soon" | "expired" | string;
  isServicePaused: boolean;
};

export type UserOrderSummary = {
  totalAmountCents: number;
  orderCount: number;
  recentOrders: Array<{
    orderNo?: string | null;
    planName?: string | null;
    billingPeriod?: string | null;
    amountCents?: number | null;
    paidAt?: string | null;
    status?: string | null;
  }>;
};

export type UserUsageLifetime = {
  startDate?: string | null;
  usageDays: number;
  stopped: boolean;
};

export type NormalUser = {
  id: string;
  email: string;
  name?: string | null;
  status: UserStatus;
  platformRoles: string[];
  tenantCount: number;
  currentSubscription?: UserSubscriptionSummary | null;
  monthlyUsage?: UserMonthlyUsage | null;
  orderSummary?: UserOrderSummary | null;
  usageLifetime?: UserUsageLifetime | null;
  createdAt: string;
  updatedAt: string;
};

export type NormalUserDetail = Omit<NormalUser, "tenantCount"> & {
  platformPermissions: string[];
  tenants: UserTenant[];
};

export type NormalUsersResponse = {
  total: number;
  page: number;
  pageSize: number;
  items: NormalUser[];
};

export type GetUsersParams = {
  search?: string;
  subscriptionStatus?: string;
  subscriptionType?: string;
  sort?: "expiresAt" | "monthlyUsage" | "subscriptionStart";
  page?: number;
  pageSize?: number;
};

export type UserTenantsResponse = {
  items: UserTenant[];
};

export type UpdateUserParams = {
  name?: string;
};

export type UpdateUserStatusParams = {
  status: "active" | "disabled";
};

export type CreatePlatformUserParams = {
  email: string;
  name: string;
  roles: string[];
};

export type CreatePlatformUserResponse = Pick<
  PlatformUser,
  "id" | "email" | "name" | "status" | "platformRoles"
> & {
  activationToken: string;
  activationExpiresAt: string;
};

export type ActivatePlatformUserParams = {
  token: string;
  newPassword: string;
  name?: string;
};

export type ActivatePlatformUserResponse = {
  message: string;
  userId: string;
  email: string;
};

function authHeaders() {
  const accessToken = getAccessToken();
  return accessToken ? { Authorization: `Bearer ${accessToken}` } : {};
}

export function getPlatformUsers(_client: typeof request = request) {
  return requestData(
    _client.get<PlatformUsersResponse>("/api/v1/users/platform", {
      headers: authHeaders(),
    })
  );
}

export function getPlatformRoles(_client: typeof request = request) {
  return requestData(
    _client.get<PlatformRolesResponse>("/api/v1/rbac/platform/roles", {
      headers: authHeaders(),
    })
  );
}

export function getUsers(params?: GetUsersParams, _client: typeof request = request) {
  return requestData(
    _client.get<NormalUsersResponse>("/api/v1/users", {
      headers: authHeaders(),
      params,
    })
  );
}

export function getUser(userId: string, _client: typeof request = request) {
  return requestData(
    _client.get<NormalUserDetail>(`/api/v1/users/${encodeURIComponent(userId)}`, {
      headers: authHeaders(),
    })
  );
}

export function updateUser(userId: string, data: UpdateUserParams, _client: typeof request = request) {
  return requestData(
    _client.patch<NormalUserDetail>(`/api/v1/users/${encodeURIComponent(userId)}`, data, {
      headers: authHeaders(),
    })
  );
}

export function updateUserStatus(userId: string, data: UpdateUserStatusParams, _client: typeof request = request) {
  return requestData(
    _client.patch<NormalUserDetail>(`/api/v1/users/${encodeURIComponent(userId)}/status`, data, {
      headers: authHeaders(),
    })
  );
}

export function getUserTenants(userId: string, _client: typeof request = request) {
  return requestData(
    _client.get<UserTenantsResponse>(`/api/v1/users/${encodeURIComponent(userId)}/tenants`, {
      headers: authHeaders(),
    })
  );
}

export function createPlatformUser(data: CreatePlatformUserParams, _client: typeof request = request) {
  return requestData(
    _client.post<CreatePlatformUserResponse>("/api/v1/users/platform", data, {
      headers: authHeaders(),
    })
  );
}

export function activatePlatformUser(data: ActivatePlatformUserParams) {
  return requestData(
    request.post<ActivatePlatformUserResponse>("/api/v1/users/platform/activate", data)
  );
}

export function grantPlatformRole(userId: string, role: string, _client: typeof request = request) {
  return requestData(
    _client.post<void>(
      `/api/v1/rbac/platform/users/${encodeURIComponent(userId)}/roles`,
      { role },
      {
        headers: authHeaders(),
      }
    )
  );
}

export function revokePlatformRole(userId: string, role: string, _client: typeof request = request) {
  return requestData(
    _client.delete<void>(
      `/api/v1/rbac/platform/users/${encodeURIComponent(userId)}/roles/${encodeURIComponent(role)}`,
      {
        headers: authHeaders(),
      }
    )
  );
}
