import { NextRequest, NextResponse } from "next/server";
import { z } from "zod";
import { requireAccess } from "@/lib/auth-guard";
import { requireAdmin } from "@/lib/admin-guard";
import { clientIp, enforceLimits, tooManyRequests } from "@/lib/rate-limit";
import { supabase } from "@/lib/supabase";

export const runtime = "nodejs";

// ERB bug reporter — the desktop shell POSTs a "Report a bug" submission here so
// the whole team's reports collect centrally instead of in each user's local
// ~/.elevate/bug-reports store. The client authenticates with the same access
// token (Authorization: Bearer <access_token>) it already holds for every other
// hosted call, so nothing new needs provisioning on the device.
//
// The accepted payload mirrors the desktop client's BugReportIn
// (cli/elevate_cli/web_routes/bug_reports.py): a note plus an optional
// screenshot data URL and lightweight page/deal/version/console context. Every
// field except the note is optional — a missing optional field must never 500.

// Backstop cap on a single screenshot (~5 MB of base64). The client already
// downscales; oversized or malformed captures are dropped (stored null), never
// rejected.
const MAX_SCREENSHOT_CHARS = 5 * 1024 * 1024;

const Body = z
  .object({
    note: z.string().optional(),
    screenshot: z.string().optional(), // data URL
    page: z.string().optional(),
    pageTitle: z.string().optional(),
    dealId: z.string().optional(),
    dealTitle: z.string().optional(),
    userAgent: z.string().optional(),
    viewport: z.string().optional(),
    reporter: z.string().optional(),
    appVersion: z.string().optional(),
    version: z.string().optional(),
    consoleErrors: z.array(z.string()).optional(),
    // Forward-compat: accept a free-form context object and merge it under the
    // structured fields below.
    context: z.record(z.unknown()).optional(),
  })
  .passthrough();

function trimmed(value: unknown, maxLen: number): string {
  return String(value ?? "").replace(/\0/g, "").slice(0, maxLen);
}

function safeScreenshot(value: string | undefined): string | null {
  if (!value || typeof value !== "string") return null;
  if (!value.startsWith("data:") || !value.includes(",")) return null;
  if (value.length > MAX_SCREENSHOT_CHARS) return null;
  return value;
}

export async function POST(req: NextRequest) {
  const guard = await requireAccess(req);
  if (!guard.ok) return NextResponse.json({ error: guard.error }, { status: guard.status });

  const limited = await enforceLimits([
    { key: `bug:ip:${clientIp(req)}`, max: 60, windowSeconds: 300 },
    { key: `bug:license:${guard.claims.license_id}`, max: 30, windowSeconds: 300 },
  ]);
  if (limited) return tooManyRequests(limited.retryAfter);

  const parsed = Body.safeParse(await req.json().catch(() => ({})));
  if (!parsed.success) {
    return NextResponse.json({ error: "bad request" }, { status: 400 });
  }
  const body = parsed.data;

  const note = trimmed(body.note, 8000).trim();
  if (!note) {
    return NextResponse.json({ error: "a description is required" }, { status: 400 });
  }

  // Everything the client sends about *who* is advisory. The row's reporter
  // identity comes from the verified access token, never the request body.
  const context: Record<string, unknown> = {
    ...(body.context && typeof body.context === "object" ? body.context : {}),
    page: body.page ? trimmed(body.page, 500) : null,
    pageTitle: body.pageTitle ? trimmed(body.pageTitle, 300) : null,
    dealId: body.dealId ? trimmed(body.dealId, 200) : null,
    dealTitle: body.dealTitle ? trimmed(body.dealTitle, 300) : null,
    userAgent: body.userAgent ? trimmed(body.userAgent, 500) : null,
    viewport: body.viewport ? trimmed(body.viewport, 60) : null,
    reporterLabel: body.reporter ? trimmed(body.reporter, 200) : null,
    consoleErrors: (body.consoleErrors || []).slice(0, 20).map((entry) => trimmed(entry, 1000)),
  };

  const row = {
    user_id: guard.user.id,
    license_id: guard.claims.license_id,
    reporter_email: guard.user.email,
    app_version: trimmed(body.appVersion || body.version, 40) || null,
    note,
    context,
    screenshot: safeScreenshot(body.screenshot),
    status: "open",
  };

  const { data, error } = await supabase()
    .from("bug_reports")
    .insert(row)
    .select("id")
    .single();
  if (error) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }

  return NextResponse.json({ id: data?.id ?? null, ok: true });
}

export async function GET(req: NextRequest) {
  // Review surface — gated behind HQ admin auth (owner/admin role), NOT the
  // client entitlement that the POST path accepts.
  const guard = await requireAdmin(req);
  if (!guard.ok) return NextResponse.json({ error: guard.error }, { status: guard.status });

  // Use new URL(...) rather than req.nextUrl so the handler is drivable with a
  // plain Request in tests as well as a NextRequest in production.
  const sp = new URL(req.url).searchParams;
  const status = sp.get("status");
  const limit = Math.min(200, Math.max(1, Number(sp.get("limit")) || 100));

  let query = supabase()
    .from("bug_reports")
    .select("*")
    .order("created_at", { ascending: false })
    .limit(limit);
  if (status) query = query.eq("status", status);

  const { data, error } = await query;
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });

  return NextResponse.json({ reports: data || [] });
}
