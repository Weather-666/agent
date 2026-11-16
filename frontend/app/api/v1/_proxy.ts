import { NextResponse } from "next/server";
import { passThroughJsonResponse, resolveBackendAuth } from "./chat/_backend";

type MaybePromise<T> = T | Promise<T>;

type HttpMethod = "GET" | "POST" | "PUT" | "PATCH" | "DELETE";

type ProxyRouteConfig<P extends Record<string, string>> = {
  /** Backend HTTP method to call. */
  method: HttpMethod;
  /**
   * Builds the absolute backend URL. Receives the incoming request (so callers
   * can forward query strings) and the resolved dynamic route params.
   */
  target: (request: Request, params: P) => MaybePromise<string>;
  /** Message returned with HTTP 502 when the upstream fetch throws. */
  errorMessage: string;
  /**
   * Optional pre-flight check that runs after params resolve but before the
   * backend fetch. Return a `NextResponse` (e.g. a 400) to short-circuit and
   * skip the upstream call; return `null`/`undefined` to proceed. Used by the
   * search routes to reject missing/invalid query params.
   */
  validate?: (request: Request, params: P) => MaybePromise<NextResponse | null | undefined>;
  /**
   * Forward `X-Tenant-ID` alongside `Authorization` by spreading the full
   * resolved auth headers. Defaults to forwarding `Authorization` only, which
   * matches the admin/CRUD proxy routes.
   */
  forwardTenant?: boolean;
  /** Send `Accept: application/json` to the backend. */
  acceptJson?: boolean;
};

const METHODS_WITH_BODY: ReadonlySet<HttpMethod> = new Set([
  "POST",
  "PUT",
  "PATCH",
]);

/**
 * Builds a Next.js route handler that authenticates the caller, forwards the
 * request to the backend, and passes the JSON response straight through.
 *
 * This replaces the near-identical GET/POST/PATCH/DELETE boilerplate that used
 * to be copy-pasted across the `app/api/v1` proxy routes. Streaming, binary and
 * multipart routes keep their bespoke handlers and are not built with this.
 */
export function proxyRoute<
  P extends Record<string, string> = Record<string, string>,
>(config: ProxyRouteConfig<P>) {
  return async (
    request: Request,
    context?: { params: Promise<P> },
  ): Promise<NextResponse> => {
    const auth = resolveBackendAuth(request);
    if (auth.error) return auth.error;

    try {
      const params = context ? await context.params : ({} as P);

      if (config.validate) {
        const invalid = await config.validate(request, params);
        if (invalid) return invalid;
      }

      const headers: Record<string, string> = config.forwardTenant
        ? { ...auth.headers }
        : { Authorization: auth.headers.Authorization };

      if (config.acceptJson) {
        headers.Accept = "application/json";
      }

      // Forward the body only when the request actually carries one. Action
      // endpoints (archive/activate/cancel/…) send an empty body and must not
      // set Content-Type, matching the original hand-written handlers.
      let body: string | undefined;
      if (METHODS_WITH_BODY.has(config.method)) {
        const raw = await request.text();
        if (raw) {
          body = raw;
          headers["Content-Type"] = "application/json";
        }
      }

      const response = await fetch(await config.target(request, params), {
        method: config.method,
        headers,
        body,
        cache: "no-store",
      });

      return passThroughJsonResponse(response);
    } catch {
      return NextResponse.json({ message: config.errorMessage }, { status: 502 });
    }
  };
}
