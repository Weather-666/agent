import { NextResponse } from "next/server";
import { adminFeaturedHeaders, passThroughJsonResponse, getServerApiBaseUrl } from "../../../_featured-admin";

export async function PUT(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  try {
    const body = await request.text();
    const response = await fetch(
      `${getServerApiBaseUrl()}/api/v1/featured-categories/${encodeURIComponent(id)}/examples/order`,
      {
        method: "PUT",
        headers: { "Content-Type": "application/json", Accept: "application/json", ...adminFeaturedHeaders(request) },
        body,
        cache: "no-store",
      }
    );
    return passThroughJsonResponse(response);
  } catch {
    return NextResponse.json({ message: "更新示例排序失败，请稍后重试" }, { status: 502 });
  }
}
