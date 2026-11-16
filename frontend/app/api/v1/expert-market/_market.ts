import {
  passThroughJsonResponse,
  readCookie,
  getServerApiBaseUrl,
  SERVER_TENANT_ID,
} from "../chat/_backend";

export { passThroughJsonResponse, getServerApiBaseUrl };

export function optionalMarketHeaders(request: Request) {
  const authorization = request.headers.get("authorization");
  const headerToken = request.headers.get("x-access-token");
  const accessToken = readCookie(request, "access_token");
  const tenantId =
    request.headers.get("x-tenant-id") ||
    request.headers.get("x-tenant") ||
    readCookie(request, "tenant_id") ||
    SERVER_TENANT_ID;
  const authHeader =
    authorization ||
    (headerToken ? `Bearer ${headerToken}` : "") ||
    (accessToken ? `Bearer ${accessToken}` : "");

  return {
    ...(authHeader ? { Authorization: authHeader } : {}),
    "X-Tenant-ID": tenantId,
  };
}
