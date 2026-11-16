import { NextResponse } from "next/server";

let cachedAuthApiBaseUrl: string | undefined;

function getAuthApiBaseUrl() {
  if (cachedAuthApiBaseUrl !== undefined) {
    return cachedAuthApiBaseUrl;
  }

  const baseUrl = process.env.SERVER_API_BASE_URL?.trim();

  if (!baseUrl) {
    throw new Error("SERVER_API_BASE_URL is required for backend proxy requests.");
  }

  cachedAuthApiBaseUrl = baseUrl.replace(/\/+$/, "");
  return cachedAuthApiBaseUrl;
}

export async function proxyAuthRequest(request: Request, path: string) {
  try {
    const body = await request.json();

    const response = await fetch(`${getAuthApiBaseUrl()}${path}`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(body),
      cache: "no-store",
    });

    const text = await response.text();
    const contentType = response.headers.get("content-type") ?? "application/json";

    return new NextResponse(text, {
      status: response.status,
      headers: {
        "Content-Type": contentType,
      },
    });
  } catch {
    return NextResponse.json(
      { message: "认证服务暂时不可用，请稍后重试" },
      { status: 502 }
    );
  }
}
