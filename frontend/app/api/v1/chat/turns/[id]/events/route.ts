import { NextResponse } from "next/server";
import { resolveBackendAuth, getServerApiBaseUrl } from "../../../_backend";

type RouteContext = {
  params: Promise<{ id: string }>;
};

export async function GET(request: Request, { params }: RouteContext) {
  try {
    const auth = resolveBackendAuth(request);
    if (auth.error) return auth.error;

    const { id } = await params;
    const url = new URL(request.url);
    const after = url.searchParams.get("after");
    const search = after ? `?after=${encodeURIComponent(after)}` : "";

    const response = await fetch(
      `${getServerApiBaseUrl()}/api/v1/chat/turns/${encodeURIComponent(id)}/events${search}`,
      {
        method: "GET",
        headers: {
          Accept: "text/event-stream",
          ...auth.headers,
        },
        cache: "no-store",
      }
    );

    if (!response.ok || !response.body) {
      const text = await response.text().catch(() => "");
      const contentType = response.headers.get("content-type") ?? "application/json";

      return new NextResponse(text || response.statusText, {
        status: response.status,
        headers: {
          "Content-Type": contentType,
        },
      });
    }

    return new NextResponse(response.body, {
      status: response.status,
      headers: {
        "Cache-Control": "no-cache, no-transform",
        "Content-Type": response.headers.get("content-type") ?? "text/event-stream",
        Connection: "keep-alive",
      },
    });
  } catch {
    return NextResponse.json(
      { message: "订阅问答回合事件失败，请稍后重试" },
      { status: 502 }
    );
  }
}
