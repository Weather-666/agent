import { NextResponse } from "next/server";
import {
  passThroughJsonResponse,
  resolveBackendAuth,
  getServerApiBaseUrl,
} from "../_backend";

export async function POST(request: Request) {
  try {
    const auth = resolveBackendAuth(request);
    if (auth.error) return auth.error;

    const body = await request.json().catch(() => ({}));

    const response = await fetch(`${getServerApiBaseUrl()}/api/v1/chat/tasks`, {
      method: "POST",
      headers: {
        Accept: "application/json",
        "Content-Type": "application/json",
        ...auth.headers,
      },
      body: JSON.stringify({ body }),
      cache: "no-store",
    });

    return passThroughJsonResponse(response);
  } catch {
    return NextResponse.json(
      { message: "创建问答任务失败，请稍后重试" },
      { status: 502 }
    );
  }
}
