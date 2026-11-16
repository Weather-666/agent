import request, { getAccessToken, requestData } from "../request";

export type AuditCategory =
  | "auth"
  | "platform_user"
  | "user"
  | "platform_role"
  | "tenant"
  | "tenant_member"
  | "knowledge_base"
  | "document"
  | "skill"
  | "expert_category"
  | "expert"
  | "plan";

export type AuditOperationType =
  | "create"
  | "update"
  | "delete"
  | "login"
  | "grant"
  | "revoke"
  | "upload";

export type AuditActor = {
  userId: string;
  name: string;
  email: string;
  platformRoles: string[];
};

export type AuditTenant = {
  id: string;
  name: string;
};

export type AuditResource = {
  type: string;
  id: string;
  name?: string | null;
};

export type AuditChange = {
  before?: unknown;
  after?: unknown;
};

export type AuditEvent = {
  id: string;
  requestId: string;
  occurredAt: string;
  category: AuditCategory;
  action: string;
  operationType: AuditOperationType;
  actor: AuditActor;
  tenant?: AuditTenant | null;
  resource: AuditResource;
  changes: Record<string, AuditChange>;
  metadata: Record<string, unknown>;
  clientIp: string | null;
};

export type AuditEventsResponse = {
  items: AuditEvent[];
  total: number;
  page: number;
  pageSize: number;
};

export type GetAuditEventsParams = {
  category?: AuditCategory;
  operationType?: AuditOperationType;
  actorId?: string;
  resourceType?: string;
  resourceId?: string;
  search?: string;
  from?: string;
  to?: string;
  page?: number;
  pageSize?: number;
};

function authHeaders() {
  const accessToken = getAccessToken();
  return accessToken ? { Authorization: `Bearer ${accessToken}` } : {};
}

export function getAuditEvents(params: GetAuditEventsParams = {}, _client: typeof request = request) {
  const query: Record<string, string | number> = {};

  if (params.category) query.category = params.category;
  if (params.operationType) query.operationType = params.operationType;
  if (params.actorId) query.actorId = params.actorId;
  if (params.resourceType) query.resourceType = params.resourceType;
  if (params.resourceId) query.resourceId = params.resourceId;
  if (params.search) query.search = params.search;
  if (params.from) query.from = params.from;
  if (params.to) query.to = params.to;
  if (typeof params.page === "number") query.page = params.page;
  if (typeof params.pageSize === "number") query.pageSize = params.pageSize;

  return requestData(
    _client.get<AuditEventsResponse>("/api/v1/audit-events", {
      headers: authHeaders(),
      params: query,
    })
  );
}
