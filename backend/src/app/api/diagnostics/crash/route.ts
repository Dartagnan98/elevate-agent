import { NextRequest, NextResponse } from "next/server";
import { z } from "zod";
import { requireAccess } from "@/lib/auth-guard";
import { clientIp, enforceLimits, tooManyRequests } from "@/lib/rate-limit";
import { supabase } from "@/lib/supabase";
import { redactSensitive } from "@/lib/redact";

export const runtime = "nodejs";

// B4 — opt-in Electron main-process crash reports. The Python side already has
// its own recorder; this is the desktop shell's blind spot. Only sanitized
// fields are accepted (version/arch/kind + a redacted message + stack +
// startup timeline). Transcript content is never sent.
const Body = z.object({
  version: z.string().max(40).optional(),
  platform: z.string().max(32).optional(),
  arch: z.string().max(32).optional(),
  kind: z.string().max(40).optional(),
  message: z.string().max(600).optional(),
  stack: z.string().max(8000).optional(),
  timeline: z.array(z.string().max(200)).max(60).optional(),
  at: z.number().optional(),
});

function clean(value: string | undefined, maxLen: number): string {
  return redactSensitive(String(value ?? "").replace(/\0/g, "").slice(0, maxLen));
}

function clientTimestamp(ts: number | undefined): string | null {
  if (typeof ts !== "number" || !Number.isFinite(ts) || ts <= 0) return null;
  const ms = ts > 10_000_000_000 ? ts : ts * 1000;
  const date = new Date(ms);
  return Number.isFinite(date.getTime()) ? date.toISOString() : null;
}

export async function POST(req: NextRequest) {
  const guard = await requireAccess(req);
  if (!guard.ok) return NextResponse.json({ error: guard.error }, { status: guard.status });

  const limited = await enforceLimits([
    { key: `crash:ip:${clientIp(req)}`, max: 120, windowSeconds: 300 },
    { key: `crash:license:${guard.claims.license_id}`, max: 60, windowSeconds: 300 },
  ]);
  if (limited) return tooManyRequests(limited.retryAfter);

  const parsed = Body.safeParse(await req.json().catch(() => ({})));
  if (!parsed.success) {
    return NextResponse.json({ error: "bad request" }, { status: 400 });
  }
  const body = parsed.data;

  const row = {
    user_id: guard.user.id,
    license_id: guard.claims.license_id,
    app_version: clean(body.version, 40) || null,
    platform: clean(body.platform, 32) || null,
    arch: clean(body.arch, 32) || null,
    kind: clean(body.kind, 40) || "uncaughtException",
    message: clean(body.message, 600),
    stack: clean(body.stack, 8000),
    timeline: (body.timeline || []).slice(-60).map((entry) => clean(entry, 200)),
    client_ts: clientTimestamp(body.at),
  };

  const { error } = await supabase().from("app_crash_reports").insert(row);
  if (error) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }

  return NextResponse.json({ accepted: true });
}
