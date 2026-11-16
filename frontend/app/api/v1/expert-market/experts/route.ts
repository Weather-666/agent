import { NextResponse } from "next/server";
import {
  optionalMarketHeaders,
  passThroughJsonResponse,
  getServerApiBaseUrl,
} from "../_market";

export async function GET(request: Request) {
  const { search } = new URL(request.url);

  try {
    const response = await fetch(`${getServerApiBaseUrl()}/api/v1/expert-market/experts${search}`, {
      method: "GET",
      headers: {
        Accept: "application/json",
        ...optionalMarketHeaders(request),
      },
      cache: "no-store",
    });

    return passThroughJsonResponse(response);
  } catch {
    return NextResponse.json(
      { message: "获取专家市场列表失败，请稍后重试" },
      { status: 502 }
    );
  }
}
