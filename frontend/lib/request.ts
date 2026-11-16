import axios, { AxiosError, type AxiosInstance, type AxiosRequestConfig } from "axios";

const BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "";
const TENANT_ID = process.env.NEXT_PUBLIC_TENANT_ID ?? "tenant_default";
const REQUEST_TIMEOUT = 15000;
const TOKEN_STORAGE_KEY = "access_token";
const REFRESH_TOKEN_STORAGE_KEY = "refresh_token";
const TENANT_STORAGE_KEY = "tenant_id";
const USER_ID_STORAGE_KEY = "user_id";
export const AUTH_EXPIRED_EVENT = "winwise:auth-expired";

// Admin-side isolated keys
const ADMIN_TOKEN_KEY = "admin_access_token";
const ADMIN_REFRESH_TOKEN_KEY = "admin_refresh_token";
export const ADMIN_AUTH_EXPIRED_EVENT = "winwise:admin-auth-expired";

type JwtPayload = {
  sub?: string;
  tenantId?: string;
  tenant_id?: string;
  activeTenantId?: string;
  active_tenant_id?: string;
};

function decodeJwtPayload(token: string): JwtPayload {
  try {
    const payload = token.split(".")[1];
    if (!payload || typeof window === "undefined") return {};

    const normalizedPayload = payload.replace(/-/g, "+").replace(/_/g, "/");
    return JSON.parse(window.atob(normalizedPayload)) as JwtPayload;
  } catch {
    return {};
  }
}

function readToken() {
  if (typeof window === "undefined") {
    return "";
  }

  return window.localStorage.getItem(TOKEN_STORAGE_KEY) ?? "";
}

function writeToken(token: string) {
  if (typeof window === "undefined") {
    return;
  }

  window.localStorage.setItem(TOKEN_STORAGE_KEY, token);
  document.cookie = `${TOKEN_STORAGE_KEY}=${encodeURIComponent(token)}; Path=/; Max-Age=2592000; SameSite=Lax`;

  const payload = decodeJwtPayload(token);

  const tenantId =
    payload.activeTenantId ||
    payload.active_tenant_id ||
    payload.tenantId ||
    payload.tenant_id;

  if (tenantId) {
    window.localStorage.setItem(TENANT_STORAGE_KEY, tenantId);
    document.cookie = `${TENANT_STORAGE_KEY}=${encodeURIComponent(tenantId)}; Path=/; Max-Age=2592000; SameSite=Lax`;
  }

  if (payload.sub) {
    window.localStorage.setItem(USER_ID_STORAGE_KEY, payload.sub);
    document.cookie = `${USER_ID_STORAGE_KEY}=${encodeURIComponent(payload.sub)}; Path=/; Max-Age=2592000; SameSite=Lax`;
  }
}

function writeRefreshToken(token: string) {
  if (typeof window === "undefined") {
    return;
  }

  window.localStorage.setItem(REFRESH_TOKEN_STORAGE_KEY, token);
  document.cookie = `${REFRESH_TOKEN_STORAGE_KEY}=${encodeURIComponent(token)}; Path=/; Max-Age=2592000; SameSite=Lax`;
}

function clearCookie(name: string) {
  document.cookie = `${name}=; Path=/; Max-Age=0; SameSite=Lax`;
}

function clearToken() {
  if (typeof window === "undefined") {
    return;
  }

  window.localStorage.removeItem(TOKEN_STORAGE_KEY);
  clearCookie(TOKEN_STORAGE_KEY);
}

export function clearAuthState({ notify = false }: { notify?: boolean } = {}) {
  if (typeof window === "undefined") {
    return;
  }

  window.localStorage.removeItem(TOKEN_STORAGE_KEY);
  window.localStorage.removeItem(REFRESH_TOKEN_STORAGE_KEY);
  window.localStorage.removeItem(TENANT_STORAGE_KEY);
  window.localStorage.removeItem(USER_ID_STORAGE_KEY);
  window.localStorage.removeItem("user_email");
  window.localStorage.removeItem("user_name");
  window.localStorage.removeItem("admin_email");
  clearCookie(TOKEN_STORAGE_KEY);
  clearCookie(REFRESH_TOKEN_STORAGE_KEY);
  clearCookie(TENANT_STORAGE_KEY);
  clearCookie(USER_ID_STORAGE_KEY);
  clearCookie("user_email");
  clearCookie("user_name");
  clearCookie("ww_demo_admin");

  if (notify) {
    window.dispatchEvent(new Event(AUTH_EXPIRED_EVENT));
  }
}

/**
 * Build an absolute API URL for raw `fetch`/`EventSource` callers.
 *
 * The axios instance below prepends `baseURL` (NEXT_PUBLIC_API_BASE_URL)
 * automatically, but native `fetch`/`EventSource` do not. Next.js `basePath` is
 * also NOT applied to raw fetch — it only rewrites `next/link`, the router, and
 * `next/image`. So a bare `fetch("/api/v1/...")` would resolve against the origin
 * with no prefix and miss the app when it is mounted under a basePath
 * (e.g. "/amazonexperts").
 *
 * Always route non-axios API requests through this helper so they hit the exact
 * same URL axios would — whether the base points at a same-origin basePath or an
 * external backend host. This is the single source of truth for that prefix.
 */
export function apiUrl(path: string) {
  return `${BASE_URL}${path}`;
}

export function setAccessToken(token: string) {
  writeToken(token);
}

export function getAccessToken() {
  return readToken();
}

export function getRefreshToken() {
  if (typeof window === "undefined") {
    return "";
  }

  return window.localStorage.getItem(REFRESH_TOKEN_STORAGE_KEY) ?? "";
}

export function getTenantId() {
  if (typeof window === "undefined") {
    return TENANT_ID;
  }

  const tokenTenantId = (() => {
    const payload = decodeJwtPayload(readToken());
    return (
      payload.activeTenantId ||
      payload.active_tenant_id ||
      payload.tenantId ||
      payload.tenant_id ||
      ""
    );
  })();

  return tokenTenantId || window.localStorage.getItem(TENANT_STORAGE_KEY) || TENANT_ID;
}

export function getUserId() {
  if (typeof window === "undefined") {
    return "";
  }

  return window.localStorage.getItem(USER_ID_STORAGE_KEY) ?? "";
}

export function removeAccessToken() {
  clearToken();
}

export function removeRefreshToken() {
  if (typeof window === "undefined") {
    return;
  }

  window.localStorage.removeItem(REFRESH_TOKEN_STORAGE_KEY);
  clearCookie(REFRESH_TOKEN_STORAGE_KEY);
}

export function saveAuthTokens(tokens: { accessToken: string; refreshToken?: string }) {
  writeToken(tokens.accessToken);

  if (tokens.refreshToken) {
    writeRefreshToken(tokens.refreshToken);
  }
}

export type ApiResponse<T = unknown> = {
  code?: number | string;
  message?: string;
  data: T;
};

type MaybeApiResponse<T> = T | ApiResponse<T>;

export type ApiError = {
  message: string;
  code?: number | string;
  status?: number;
  raw?: unknown;
};

const request: AxiosInstance = axios.create({
  baseURL: BASE_URL,
  timeout: REQUEST_TIMEOUT,
  withCredentials: true,
});

let refreshPromise: Promise<{ accessToken: string; refreshToken?: string }> | null = null;

request.interceptors.request.use((config) => {
  const token = readToken();
  const tenantId = getTenantId();
  const userId = getUserId();

  config.headers = config.headers ?? {};
  config.headers["X-Tenant-ID"] = tenantId;

  if (userId) {
    config.headers["X-User-ID"] = userId;
  }

  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }

  return config;
});

request.interceptors.response.use(
  (response) => response,
  async (error: AxiosError<ApiResponse>) => {
    const originalConfig = error.config as (AxiosRequestConfig & {
      _retry?: boolean;
    }) | undefined;

    const isAuthEndpoint =
      originalConfig?.url?.includes("/api/v1/auth/login") ||
      originalConfig?.url?.includes("/api/v1/auth/refresh");

    if (error.response?.status === 401 && originalConfig && !isAuthEndpoint) {
      // Attempt a one-time silent token refresh before giving up.
      if (!originalConfig._retry) {
        const refreshToken = getRefreshToken();

        if (refreshToken) {
          originalConfig._retry = true;

          try {
            refreshPromise ??= requestData(
              axios.post<{ accessToken: string; refreshToken?: string }>(
                "/api/v1/auth/refresh",
                { refreshToken },
                {
                  baseURL: BASE_URL,
                  timeout: REQUEST_TIMEOUT,
                  withCredentials: true,
                }
              )
            );

            const tokens = await refreshPromise;
            refreshPromise = null;
            saveAuthTokens(tokens);
            originalConfig.headers = originalConfig.headers ?? {};
            originalConfig.headers.Authorization = `Bearer ${tokens.accessToken}`;
            return request(originalConfig);
          } catch {
            refreshPromise = null;
          }
        }
      }

      // Terminal 401 (no refresh token, refresh failed, or the retried request
      // is still unauthorized): clear the session and notify globally so the
      // layout redirects to the login page. This is the single source of truth
      // for session-expiry redirects.
      clearAuthState({ notify: true });
    }

    const status = error.response?.status;
    const responseData = error.response?.data;

    const normalizedError: ApiError = {
      message: responseData?.message ?? error.message ?? "Request failed",
      code: responseData?.code,
      status,
      raw: error,
    };

    return Promise.reject(normalizedError);
  }
);

export type RequestConfig = AxiosRequestConfig;
export default request;

export async function requestData<T>(promise: Promise<{ data: MaybeApiResponse<T> }>): Promise<T> {
  const response = await promise;
  const payload = response.data;

  if (
    payload &&
    typeof payload === "object" &&
    "data" in payload &&
    ("code" in payload || "message" in payload)
  ) {
    return (payload as ApiResponse<T>).data;
  }

  return payload as T;
}

// ── Admin-side auth (isolated from user-side) ──────────────────────────────

function readAdminToken() {
  if (typeof window === "undefined") return "";
  return window.localStorage.getItem(ADMIN_TOKEN_KEY) ?? "";
}

function writeAdminToken(token: string) {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(ADMIN_TOKEN_KEY, token);
  document.cookie = `${ADMIN_TOKEN_KEY}=${encodeURIComponent(token)}; Path=/; Max-Age=2592000; SameSite=Lax`;
}

function writeAdminRefreshToken(token: string) {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(ADMIN_REFRESH_TOKEN_KEY, token);
  document.cookie = `${ADMIN_REFRESH_TOKEN_KEY}=${encodeURIComponent(token)}; Path=/; Max-Age=2592000; SameSite=Lax`;
}

export function getAdminAccessToken() {
  return readAdminToken();
}

export function getAdminRefreshToken() {
  if (typeof window === "undefined") return "";
  return window.localStorage.getItem(ADMIN_REFRESH_TOKEN_KEY) ?? "";
}

export function saveAdminAuthTokens(tokens: { accessToken: string; refreshToken?: string }) {
  writeAdminToken(tokens.accessToken);
  if (tokens.refreshToken) writeAdminRefreshToken(tokens.refreshToken);
}

export function clearAdminAuthState({ notify = false }: { notify?: boolean } = {}) {
  if (typeof window === "undefined") return;
  window.localStorage.removeItem(ADMIN_TOKEN_KEY);
  window.localStorage.removeItem(ADMIN_REFRESH_TOKEN_KEY);
  window.localStorage.removeItem("admin_email");
  clearCookie(ADMIN_TOKEN_KEY);
  clearCookie(ADMIN_REFRESH_TOKEN_KEY);
  clearCookie("ww_demo_admin");
  if (notify) {
    window.dispatchEvent(new Event(ADMIN_AUTH_EXPIRED_EVENT));
  }
}

export const adminRequest: AxiosInstance = axios.create({
  baseURL: BASE_URL,
  timeout: REQUEST_TIMEOUT,
  withCredentials: true,
});

let adminRefreshPromise: Promise<{ accessToken: string; refreshToken?: string }> | null = null;

adminRequest.interceptors.request.use((config) => {
  const token = readAdminToken();
  const payload = decodeJwtPayload(token);
  const tenantId =
    payload.activeTenantId ||
    payload.active_tenant_id ||
    payload.tenantId ||
    payload.tenant_id ||
    TENANT_ID;

  config.headers = config.headers ?? {};
  config.headers["X-Tenant-ID"] = tenantId;
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

adminRequest.interceptors.response.use(
  (response) => response,
  async (error: AxiosError<ApiResponse>) => {
    const originalConfig = error.config as (AxiosRequestConfig & { _retry?: boolean }) | undefined;

    const isAuthEndpoint =
      originalConfig?.url?.includes("/api/v1/auth/login") ||
      originalConfig?.url?.includes("/api/v1/auth/refresh");

    if (error.response?.status === 401 && originalConfig && !isAuthEndpoint) {
      if (!originalConfig._retry) {
        const refreshToken = getAdminRefreshToken();
        if (refreshToken) {
          originalConfig._retry = true;
          try {
            adminRefreshPromise ??= requestData(
              axios.post<{ accessToken: string; refreshToken?: string }>(
                "/api/v1/auth/refresh",
                { refreshToken },
                { baseURL: BASE_URL, timeout: REQUEST_TIMEOUT, withCredentials: true }
              )
            );
            const tokens = await adminRefreshPromise;
            adminRefreshPromise = null;
            saveAdminAuthTokens(tokens);
            originalConfig.headers = originalConfig.headers ?? {};
            originalConfig.headers.Authorization = `Bearer ${tokens.accessToken}`;
            return adminRequest(originalConfig);
          } catch {
            adminRefreshPromise = null;
          }
        }
      }
      clearAdminAuthState({ notify: true });
    }

    const status = error.response?.status;
    const responseData = error.response?.data;
    const normalizedError: ApiError = {
      message: responseData?.message ?? error.message ?? "Request failed",
      code: responseData?.code,
      status,
      raw: error,
    };
    return Promise.reject(normalizedError);
  }
);
