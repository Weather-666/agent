import { NextResponse } from "next/server";
import {
  passThroughJsonResponse,
  getServerApiBaseUrl,
} from "../../../chat/_backend";

export async function POST(request: Request) {
  try {
    const body = await request.json();
    const response = await fetch(`${getServerApiBaseUrl()}/api/v1/users/platform/activate`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(body),
      cache: "no-store",
    });

    return passThroughJsonResponse(response);
  } catch {
    return NextResponse.json(
      { message: "激活平台用户失败，请稍后重试" },
      { status: 502 }
    );
  }
}
