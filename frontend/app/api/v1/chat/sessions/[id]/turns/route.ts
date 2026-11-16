import { NextResponse } from "next/server";
import { resolveBackendAuth, getServerApiBaseUrl } from "../../../_backend";

type RouteContext = {
  params: Promise<{ id: string }>;
};

export async function POST(request: Request, { params }: RouteContext) {
  try {
    const auth = resolveBackendAuth(request);
    if (auth.error) return auth.error;

    const { id } = await params;
    const body = await request.json().catch(() => ({}));

    const response = await fetch(
      `${getServerApiBaseUrl()}/api/v1/chat/sessions/${encodeURIComponent(id)}/turns`,
      {
        method: "POST",
        headers: {
          Accept: "text/event-stream",
          "Content-Type": "application/json",
          ...auth.headers,
        },
        body: JSON.stringify(body),
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
      { message: "创建问答回合失败，请稍后重试" },
      { status: 502 }
    );
  }
}
