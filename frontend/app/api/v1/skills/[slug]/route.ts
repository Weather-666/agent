import { getServerApiBaseUrl } from "../../chat/_backend";
import { proxyRoute } from "../../_proxy";

const skillUrl = (slug: string) =>
  `${getServerApiBaseUrl()}/api/v1/skills/${encodeURIComponent(slug)}`;

export const GET = proxyRoute({
  method: "GET",
  target: (_request, { slug }: { slug: string }) => skillUrl(slug),
  errorMessage: "Failed to load skill details. Please try again later.",
});

export const PUT = proxyRoute({
  method: "PUT",
  target: (_request, { slug }: { slug: string }) => skillUrl(slug),
  errorMessage: "Failed to update skill. Please try again later.",
});

export const DELETE = proxyRoute({
  method: "DELETE",
  target: (request, { slug }: { slug: string }) =>
    `${skillUrl(slug)}${new URL(request.url).search}`,
  errorMessage: "Failed to delete skill. Please try again later.",
});
