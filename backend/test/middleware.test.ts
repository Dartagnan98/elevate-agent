import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { NextRequest } from "next/server";
import { config, middleware } from "../src/middleware";

function captureInfo(run: () => void): string[] {
  const original = console.info;
  const lines: string[] = [];
  console.info = (...args: unknown[]) => {
    lines.push(args.map(String).join(" "));
  };
  try {
    run();
  } finally {
    console.info = original;
  }
  return lines;
}

describe("hosted middleware request correlation", () => {
  it("echoes sanitized request ids and logs session hints", () => {
    let response: Response | undefined;
    const lines = captureInfo(() => {
      response = middleware(
        new NextRequest("https://api.elevationrealestatehq.com/api/health", {
          headers: {
            "x-request-id": "rid 123",
            "x-elevate-session-id": "sess abc",
          },
        }),
      );
    });

    assert.equal(response?.headers.get("x-request-id"), "rid_123");
    assert.equal(lines.length, 1);
    assert.match(
      lines[0],
      /\[request\] request_id=rid_123 session_id=sess_abc method=GET path=\/api\/health/,
    );
  });

  it("generates request ids when callers do not provide one", () => {
    let response: Response | undefined;
    const lines = captureInfo(() => {
      response = middleware(
        new NextRequest("https://api.elevationrealestatehq.com/api/me", {
          headers: {
            cookie: "elevate_session=session-cookie",
          },
        }),
      );
    });

    const requestId = response?.headers.get("x-request-id") ?? "";
    assert.match(
      requestId,
      /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/,
    );
    assert.match(lines[0], new RegExp(`request_id=${requestId}`));
    assert.match(lines[0], /session_id=session-cookie method=GET path=\/api\/me/);
  });

  it("applies only to hosted API routes", () => {
    assert.deepEqual(config.matcher, ["/api/:path*"]);
  });
});
