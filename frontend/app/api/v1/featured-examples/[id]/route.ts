import { NextResponse } from "next/server";
import {
  adminFeaturedHeaders,
  passThroughJsonResponse,
  getServerApiBaseUrl,
} from "../../featured-categories/_featured-admin";

export async function GET(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  try {
    const response = await fetch(
      `${getServerApiBaseUrl()}/api/v1/featured-examples/${encodeURIComponent(id)}`,
      {
        method: "GET",
        headers: { Accept: "application/json", ...adminFeaturedHeaders(request) },
        cache: "no-store",
      }
    );
    return passThroughJsonResponse(response);
  } catch {
    return NextResponse.json({ message: "获取示例失败，请稍后重试" }, { status: 502 });
  }
}

export async function PATCH(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  try {
    const body = await request.text();
    const response = await fetch(
      `${getServerApiBaseUrl()}/api/v1/featured-examples/${encodeURIComponent(id)}`,
      {
        method: "PATCH",
        headers: { "Content-Type": "application/json", Accept: "application/json", ...adminFeaturedHeaders(request) },
        body,
        cache: "no-store",
      }
    );
    return passThroughJsonResponse(response);
  } catch {
    return NextResponse.json({ message: "编辑示例失败，请稍后重试" }, { status: 502 });
  }
}

export async function DELETE(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  try {
    const response = await fetch(
      `${getServerApiBaseUrl()}/api/v1/featured-examples/${encodeURIComponent(id)}`,
      {
        method: "DELETE",
        headers: { Accept: "application/json", ...adminFeaturedHeaders(request) },
        cache: "no-store",
      }
    );
    return passThroughJsonResponse(response);
  } catch {
    return NextResponse.json({ message: "删除示例失败，请稍后重试" }, { status: 502 });
  }
}
