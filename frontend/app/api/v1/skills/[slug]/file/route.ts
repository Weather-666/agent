import { NextResponse } from "next/server";
import {
  resolveBackendAuth,
  getServerApiBaseUrl,
} from "../../../chat/_backend";

type RouteContext = {
  params: Promise<{
    slug: string;
  }>;
};

export async function GET(request: Request, context: RouteContext) {
  const auth = resolveBackendAuth(request);
  if (auth.error) return auth.error;

  try {
    const { slug } = await context.params;
    const url = new URL(request.url);
    const response = await fetch(
      `${getServerApiBaseUrl()}/api/v1/skills/${encodeURIComponent(slug)}/file${url.search}`,
      {
        method: "GET",
        headers: {
          Authorization: auth.headers.Authorization,
        },
        cache: "no-store",
      }
    );

    const body = await response.arrayBuffer();
    const headers = new Headers();
    const contentType = response.headers.get("content-type");
    const contentDisposition = response.headers.get("content-disposition");

    if (contentType) headers.set("Content-Type", contentType);
    if (contentDisposition) headers.set("Content-Disposition", contentDisposition);

    return new NextResponse(body, {
      status: response.status,
      headers,
    });
  } catch {
    return NextResponse.json(
      { message: "Failed to load skill file. Please try again later." },
      { status: 502 }
    );
  }
}
