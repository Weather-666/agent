import { proxyAuthRequest } from "../../_auth-proxy";

export async function POST(request: Request) {
  return proxyAuthRequest(request, "/api/v1/auth/refresh");
}
