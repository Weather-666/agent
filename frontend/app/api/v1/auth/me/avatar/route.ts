import { NextResponse } from "next/server";
import {
  passThroughJsonResponse,
  resolveBackendAuth,
  getServerApiBaseUrl,
} from "../../../chat/_backend";

export async function PUT(request: Request) {
  const auth = resolveBackendAuth(request);
  if (auth.error) return auth.error;

  try {
    // Re-read the multipart body and forward it. Do NOT set Content-Type
    // manually — fetch derives the multipart boundary from the FormData.
    const form = await request.formData();
    const response = await fetch(`${getServerApiBaseUrl()}/api/v1/auth/me/avatar`, {
      method: "PUT",
      headers: {
        ...auth.headers,
      },
      body: form,
      cache: "no-store",
    });

    return passThroughJsonResponse(response);
  } catch {
    return NextResponse.json(
      { message: "上传头像失败，请稍后重试" },
      { status: 502 }
    );
  }
}
