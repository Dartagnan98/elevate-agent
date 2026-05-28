import { NextRequest, NextResponse } from "next/server";
import { supabase } from "./supabase";

// App-layer rate limiting backed by the `rate_limits` table + the atomic
// `check_rate_limit` Postgres function (migration 0008). Used to throttle the
// public auth endpoints: stops password brute-force, and stops abuse of the
// email-sending endpoints (forgot / login-code) which would otherwise let an
// attacker bomb a victim's inbox and run up the Mailjet bill.

export type RateLimitResult = {
  allowed: boolean;
  remaining: number;
  retryAfter: number; // seconds until the window resets
};

/** Best-effort client IP from proxy headers. */
export function clientIp(req: NextRequest): string {
  return (
    req.headers.get("x-forwarded-for")?.split(",")[0]?.trim() ||
    req.headers.get("x-real-ip")?.trim() ||
    "unknown"
  );
}

/**
 * Atomically count this request against `key` within a fixed window.
 *
 * Fail-open: if the limiter's DB call errors, we ALLOW the request rather than
 * locking everyone out of auth on a limiter hiccup. Availability beats strict
 * enforcement here — the cap is defense-in-depth, not the only control.
 */
export async function rateLimit(
  key: string,
  max: number,
  windowSeconds: number,
): Promise<RateLimitResult> {
  try {
    const { data, error } = await supabase().rpc("check_rate_limit", {
      p_key: key,
      p_max: max,
      p_window_seconds: windowSeconds,
    });
    if (error) {
      console.error("[rate-limit] rpc error:", error.message);
      return { allowed: true, remaining: max, retryAfter: 0 };
    }
    const row = Array.isArray(data) ? data[0] : data;
    return {
      allowed: !!row?.allowed,
      remaining: row?.remaining ?? 0,
      retryAfter: row?.retry_after ?? 0,
    };
  } catch (e) {
    console.error("[rate-limit] exception:", e);
    return { allowed: true, remaining: max, retryAfter: 0 };
  }
}

/** Standard 429 with a Retry-After header. */
export function tooManyRequests(retryAfter: number): NextResponse {
  return NextResponse.json(
    { error: "too many requests" },
    {
      status: 429,
      headers: { "Retry-After": String(Math.max(1, retryAfter)) },
    },
  );
}

/**
 * Convenience: enforce several limit buckets at once (e.g. per-IP AND
 * per-email). Returns the first bucket that trips, or null when all pass.
 */
export async function enforceLimits(
  buckets: Array<{ key: string; max: number; windowSeconds: number }>,
): Promise<RateLimitResult | null> {
  for (const b of buckets) {
    const r = await rateLimit(b.key, b.max, b.windowSeconds);
    if (!r.allowed) return r;
  }
  return null;
}
