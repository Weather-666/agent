import { NextResponse } from "next/server";
import {
  getServerApiBaseUrl,
  passThroughJsonResponse,
  resolveBackendAuth,
} from "../_backend";
import { proxyRoute } from "../../_proxy";

export const GET = proxyRoute({
  method: "GET",
  target: (request) =>
    `${getServerApiBaseUrl()}/api/v1/chat/sessions${new URL(request.url).search}`,
  errorMessage: "获取会话列表失败，请稍后重试",
  forwardTenant: true,
  acceptJson: true,
});

// 创建会话即使 body 为空也需向后端发送 `{}`，与旧实现保持一致；
// proxyRoute 在 body 为空时不会发送 body，因此这里保留手写 POST。
export async function POST(request: Request) {
  const auth = resolveBackendAuth(request);
  if (auth.error) return auth.error;

  try {
    const body = await request.json().catch(() => ({}));

    const response = await fetch(`${getServerApiBaseUrl()}/api/v1/chat/sessions`, {
      method: "POST",
      headers: {
        Accept: "application/json",
        "Content-Type": "application/json",
        ...auth.headers,
      },
      body: JSON.stringify(body),
      cache: "no-store",
    });

    return passThroughJsonResponse(response);
  } catch {
    return NextResponse.json(
      { message: "创建会话失败，请稍后重试" },
      { status: 502 }
    );
  }
}
