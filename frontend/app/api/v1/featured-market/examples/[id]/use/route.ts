import { NextResponse } from "next/server";
import { featuredHeaders, passThroughJsonResponse, getServerApiBaseUrl } from "../../../_featured";

export async function POST(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  try {
    const response = await fetch(
      `${getServerApiBaseUrl()}/api/v1/featured-market/examples/${encodeURIComponent(id)}/use`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json", ...featuredHeaders(request) },
        body: "{}",
        cache: "no-store",
      }
    );
    return passThroughJsonResponse(response);
  } catch {
    return NextResponse.json({ message: "使用示例失败，请稍后重试" }, { status: 502 });
  }
}
