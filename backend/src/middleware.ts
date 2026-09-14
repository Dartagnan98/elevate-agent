import { NextRequest, NextResponse } from "next/server";

const REQUEST_ID_HEADER = "x-request-id";
const SESSION_ID_HEADERS = ["x-elevate-session-id", "x-session-id"];
const LOG_TOKEN_RE = /[^A-Za-z0-9_.:-]+/g;

function cleanLogToken(value: string | null | undefined, maxLen = 96): string {
  const cleaned = (value ?? "").trim().replace(LOG_TOKEN_RE, "_").slice(0, maxLen);
  return cleaned || "-";
}

function requestIdForLog(request: NextRequest): string {
  const incoming = cleanLogToken(request.headers.get(REQUEST_ID_HEADER));
  return incoming === "-" ? crypto.randomUUID() : incoming;
}

function sessionIdForLog(request: NextRequest): string {
  for (const header of SESSION_ID_HEADERS) {
    const value = cleanLogToken(request.headers.get(header), 140);
    if (value !== "-") return value;
  }
  return cleanLogToken(request.cookies.get("elevate_session")?.value, 140);
}

export function middleware(request: NextRequest) {
  const requestId = requestIdForLog(request);
  const sessionId = sessionIdForLog(request);
  console.info(
    `[request] request_id=${requestId} session_id=${sessionId} method=${request.method} path=${request.nextUrl.pathname}`,
  );

  const requestHeaders = new Headers(request.headers);
  requestHeaders.set(REQUEST_ID_HEADER, requestId);
  const response = NextResponse.next({
    request: { headers: requestHeaders },
  });
  response.headers.set(REQUEST_ID_HEADER, requestId);
  return response;
}

export const config = {
  matcher: ["/api/:path*"],
};
