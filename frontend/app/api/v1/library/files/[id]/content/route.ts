import { NextResponse } from "next/server";
import {
  getServerApiBaseUrl,
  resolveBackendAuth,
} from "../../../../chat/_backend";

type RouteContext = {
  params: Promise<{ id: string }>;
};

export async function GET(request: Request, { params }: RouteContext) {
  const auth = resolveBackendAuth(request);
  if (auth.error) return auth.error;

  try {
    const { id } = await params;
    const query = new URL(request.url).search;
    const response = await fetch(
      `${getServerApiBaseUrl()}/api/v1/library/files/${encodeURIComponent(id)}/content${query}`,
      {
        method: "GET",
        headers: auth.headers,
        cache: "no-store",
      },
    );

    const headers = new Headers();
    for (const name of ["content-type", "content-disposition", "content-length"]) {
      const value = response.headers.get(name);
      if (value) headers.set(name, value);
    }
    return new NextResponse(response.body, { status: response.status, headers });
  } catch {
    return NextResponse.json(
      { message: "下载资料库文件失败，请稍后重试" },
      { status: 502 },
    );
  }
}
