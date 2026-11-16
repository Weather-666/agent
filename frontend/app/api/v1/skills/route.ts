import { NextResponse } from "next/server";
import {
  passThroughJsonResponse,
  resolveBackendAuth,
  getServerApiBaseUrl,
} from "../chat/_backend";
import { proxyRoute } from "../_proxy";

export const GET = proxyRoute({
  method: "GET",
  target: (request) =>
    `${getServerApiBaseUrl()}/api/v1/skills${new URL(request.url).search}`,
  errorMessage: "Failed to load skills. Please try again later.",
});

// multipart 上传保持手写处理，不走 proxyRoute（proxyRoute 只转发 JSON body）。
export async function POST(request: Request) {
  const auth = resolveBackendAuth(request);
  if (auth.error) return auth.error;

  try {
    const formData = await request.formData();
    const response = await fetch(`${getServerApiBaseUrl()}/api/v1/skills`, {
      method: "POST",
      headers: {
        Authorization: auth.headers.Authorization,
      },
      body: formData,
      cache: "no-store",
    });

    return passThroughJsonResponse(response);
  } catch {
    return NextResponse.json(
      { message: "Failed to upload skill. Please try again later." },
      { status: 502 }
    );
  }
}
