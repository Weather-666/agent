import { NextResponse } from "next/server";
import { featuredHeaders, passThroughJsonResponse, getServerApiBaseUrl } from "../_featured";

export async function GET(request: Request) {
  const { search } = new URL(request.url);
  try {
    const response = await fetch(`${getServerApiBaseUrl()}/api/v1/featured-market/examples${search}`, {
      method: "GET",
      headers: { Accept: "application/json", ...featuredHeaders(request) },
      cache: "no-store",
    });
    return passThroughJsonResponse(response);
  } catch {
    return NextResponse.json({ message: "获取精选示例失败，请稍后重试" }, { status: 502 });
  }
}
