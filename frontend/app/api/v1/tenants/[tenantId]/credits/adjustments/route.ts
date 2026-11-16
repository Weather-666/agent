import { NextResponse } from "next/server";
import { getServerApiBaseUrl, resolveBackendAuth, passThroughJsonResponse } from "../../../../chat/_backend";

type RouteContext = {
  params: Promise<{ tenantId: string }>;
};

export async function POST(request: Request, { params }: RouteContext) {
  const auth = resolveBackendAuth(request);
  if (auth.error) return auth.error;

  try {
    const { tenantId } = await params;
    const idempotencyKey = request.headers.get("idempotency-key") ?? "";
    const body = await request.text();

    const response = await fetch(
      `${getServerApiBaseUrl()}/api/v1/tenants/${encodeURIComponent(tenantId)}/credits/adjustments`,
      {
        method: "POST",
        headers: {
          Authorization: auth.headers.Authorization,
          "Content-Type": "application/json",
          ...(idempotencyKey ? { "Idempotency-Key": idempotencyKey } : {}),
        },
        body,
        cache: "no-store",
      }
    );

    return passThroughJsonResponse(response);
  } catch {
    return NextResponse.json({ message: "创建积分调账失败，请稍后重试" }, { status: 502 });
  }
}
