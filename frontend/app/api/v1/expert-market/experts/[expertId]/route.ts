import { NextResponse } from "next/server";
import {
  optionalMarketHeaders,
  passThroughJsonResponse,
  getServerApiBaseUrl,
} from "../../_market";

type RouteContext = {
  params: Promise<{
    expertId: string;
  }>;
};

export async function GET(request: Request, context: RouteContext) {
  try {
    const { expertId } = await context.params;
    const response = await fetch(
      `${getServerApiBaseUrl()}/api/v1/expert-market/experts/${encodeURIComponent(expertId)}`,
      {
        method: "GET",
        headers: {
          Accept: "application/json",
          ...optionalMarketHeaders(request),
        },
        cache: "no-store",
      }
    );

    return passThroughJsonResponse(response);
  } catch {
    return NextResponse.json(
      { message: "获取专家市场详情失败，请稍后重试" },
      { status: 502 }
    );
  }
}
