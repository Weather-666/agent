import { NextResponse } from "next/server";

let cachedServerApiBaseUrl: string | undefined;

export function getServerApiBaseUrl() {
  if (cachedServerApiBaseUrl !== undefined) {
    return cachedServerApiBaseUrl;
  }

  const baseUrl = process.env.SERVER_API_BASE_URL?.trim();

  if (!baseUrl) {
    throw new Error("SERVER_API_BASE_URL is required for backend proxy requests.");
  }

  cachedServerApiBaseUrl = baseUrl.replace(/\/+$/, "");
  return cachedServerApiBaseUrl;
}
export const SERVER_TENANT_ID = process.env.SERVER_TENANT_ID ?? "tenant_default";

function parseJwtPayload(token: string) {
  const parts = token.split(".");
  if (parts.length < 2 || !parts[1]) return null;

  try {
    const base64 = parts[1].replace(/-/g, "+").replace(/_/g, "/");
    const padded = base64.padEnd(Math.ceil(base64.length / 4) * 4, "=");
    const json = Buffer.from(padded, "base64").toString("utf8");
    return JSON.parse(json) as { exp?: unknown };
  } catch {
    return null;
  }
}

function getBearerToken(authHeader: string) {
  const match = authHeader.match(/^Bearer\s+(.+)$/i);
  return match?.[1]?.trim() ?? "";
}

function isBearerTokenUsable(authHeader: string) {
  const token = getBearerToken(authHeader);
  if (!token) return false;

  const payload = parseJwtPayload(token);
  if (!payload) return false;

  if (typeof payload.exp === "number") {
    return payload.exp * 1000 > Date.now() + 5_000;
  }

  return true;
}

export function readCookie(request: Request, name: string) {
  const cookie = request.headers.get("cookie") ?? "";
  const match = cookie
    .split("; ")
    .find((row) => row.startsWith(`${name}=`));

  return match ? decodeURIComponent(match.split("=")[1] ?? "") : "";
}

export function resolveBackendAuth(request: Request) {
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

  if (!authHeader || !isBearerTokenUsable(authHeader)) {
    return {
      error: NextResponse.json(
        { message: "Missing or invalid bearer token" },
        { status: 401 }
      ),
      headers: null,
    };
  }

  return {
    error: null,
    headers: {
      Authorization: authHeader,
      "X-Tenant-ID": tenantId,
    },
  };
}

export async function passThroughJsonResponse(response: Response) {
  if (response.status === 204 || response.status === 205) {
    return new NextResponse(null, {
      status: response.status,
    });
  }

  const text = await response.text();
  const contentType = response.headers.get("content-type") ?? "application/json";

  return new NextResponse(text, {
    status: response.status,
    headers: {
      "Content-Type": contentType,
    },
  });
}
