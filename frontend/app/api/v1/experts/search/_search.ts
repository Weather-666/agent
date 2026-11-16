import { NextResponse } from "next/server";
import { getServerApiBaseUrl } from "../../chat/_backend";
import { proxyRoute } from "../../_proxy";

type ExpertSearchConfig = {
  /** Query-string key read from the incoming request and forwarded upstream. */
  param: string;
  /** Backend path suffix under `/api/v1/experts/search/`. */
  segment: string;
  /** 400 message when the param is missing (or not in `allowed`). */
  invalidMessage: string;
  /** 502 message when the upstream fetch throws. */
  errorMessage: string;
  /** When set, the trimmed value must be a member of this set. */
  allowed?: ReadonlySet<string>;
};

/**
 * Builds a GET handler for the `experts/search/*` routes. They all read a single
 * required query param, optionally constrain it to an allowed set, and forward
 * it to the matching backend endpoint — the only differences are the param name,
 * the path segment, the allowed values, and the localized error copy.
 */
export function expertSearchRoute(config: ExpertSearchConfig) {
  const readValue = (request: Request) =>
    new URL(request.url).searchParams.get(config.param)?.trim();

  return proxyRoute({
    method: "GET",
    validate: (request) => {
      const value = readValue(request);
      if (!value || (config.allowed && !config.allowed.has(value))) {
        return NextResponse.json({ message: config.invalidMessage }, { status: 400 });
      }
      return null;
    },
    target: (request) => {
      const query = new URLSearchParams({ [config.param]: readValue(request)! });
      return `${getServerApiBaseUrl()}/api/v1/experts/search/${config.segment}?${query}`;
    },
    errorMessage: config.errorMessage,
  });
}
