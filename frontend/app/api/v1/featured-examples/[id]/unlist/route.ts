import { NextResponse } from "next/server";
import {
  adminFeaturedHeaders,
  passThroughJsonResponse,
  getServerApiBaseUrl,
} from "../../../featured-categories/_featured-admin";

export async function POST(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  try {
    const response = await fetch(
      `${getServerApiBaseUrl()}/api/v1/featured-examples/${encodeURIComponent(id)}/unlist`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json", ...adminFeaturedHeaders(request) },
        body: "{}",
        cache: "no-store",
      }
    );
    return passThroughJsonResponse(response);
  } catch {
    return NextResponse.json({ message: "下架操作失败，请稍后重试" }, { status: 502 });
  }
}
