import { NextResponse } from "next/server";
import { adminFeaturedHeaders, passThroughJsonResponse, getServerApiBaseUrl } from "./_featured-admin";

export async function GET(request: Request) {
  try {
    const response = await fetch(`${getServerApiBaseUrl()}/api/v1/featured-categories`, {
      method: "GET",
      headers: { Accept: "application/json", ...adminFeaturedHeaders(request) },
      cache: "no-store",
    });
    return passThroughJsonResponse(response);
  } catch {
    return NextResponse.json({ message: "获取分类失败，请稍后重试" }, { status: 502 });
  }
}

export async function POST(request: Request) {
  try {
    const body = await request.text();
    const response = await fetch(`${getServerApiBaseUrl()}/api/v1/featured-categories`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json", ...adminFeaturedHeaders(request) },
      body,
      cache: "no-store",
    });
    return passThroughJsonResponse(response);
  } catch {
    return NextResponse.json({ message: "新增分类失败，请稍后重试" }, { status: 502 });
  }
}
