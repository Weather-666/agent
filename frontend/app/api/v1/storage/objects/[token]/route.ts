import { NextResponse } from "next/server";
import { getServerApiBaseUrl } from "../../../chat/_backend";

type RouteContext = {
  params: Promise<{
    token: string;
  }>;
};

// Proxies presigned object-store uploads/downloads to the backend when the
// local storage backend returns same-origin URLs (/api/v1/storage/objects/{token}).
// The token in the path is itself the authorization, so no bearer header is added.
// MinIO/S3 backends return absolute URLs that bypass this route entirely.

export async function PUT(request: Request, { params }: RouteContext) {
  const { token } = await params;

  try {
    const headers: Record<string, string> = {};
    const contentType = request.headers.get("content-type");
    if (contentType) headers["content-type"] = contentType;

    // Buffer the body: undici rejects streamed request bodies here, and this
    // proxy only serves the local storage backend (capped at the backend's
    // max upload size). MinIO/S3 uploads use absolute URLs and skip this route.
    const body = Buffer.from(await request.arrayBuffer());

    const response = await fetch(
      `${getServerApiBaseUrl()}/api/v1/storage/objects/${token}`,
      {
        method: "PUT",
        headers,
        body,
        cache: "no-store",
      }
    );

    if (!response.ok) {
      const text = await response.text();
      return new NextResponse(text || null, { status: response.status });
    }

    return new NextResponse(null, { status: response.status });
  } catch {
    return NextResponse.json(
      { message: "上传文件到存储失败，请稍后重试" },
      { status: 502 }
    );
  }
}

export async function GET(_request: Request, { params }: RouteContext) {
  const { token } = await params;

  try {
    const response = await fetch(
      `${getServerApiBaseUrl()}/api/v1/storage/objects/${token}`,
      {
        method: "GET",
        cache: "no-store",
      }
    );

    if (!response.ok) {
      const text = await response.text();
      return new NextResponse(text || null, { status: response.status });
    }

    const headers = new Headers();
    const contentType = response.headers.get("content-type");
    if (contentType) headers.set("content-type", contentType);
    const contentDisposition = response.headers.get("content-disposition");
    if (contentDisposition) headers.set("content-disposition", contentDisposition);

    return new NextResponse(response.body, {
      status: response.status,
      headers,
    });
  } catch {
    return NextResponse.json(
      { message: "下载文件失败，请稍后重试" },
      { status: 502 }
    );
  }
}
