import { NextRequest, NextResponse } from "next/server";
import { requireAccess } from "@/lib/auth-guard";
import { findDeviceGrantByUserCode } from "@/lib/store";

export const runtime = "nodejs";

export async function GET(req: NextRequest) {
  const auth = await requireAccess(req);
  if (!auth.ok) {
    return NextResponse.json({ error: auth.error }, { status: auth.status });
  }

  const code = new URL(req.url).searchParams.get("code");
  if (!code) {
    return NextResponse.json({ error: "missing code" }, { status: 400 });
  }

  const grant = await findDeviceGrantByUserCode(code.trim().toUpperCase());
  if (!grant) {
    return NextResponse.json({ error: "not_found" }, { status: 404 });
  }

  const expired = new Date(grant.expires_at).getTime() < Date.now();

  return NextResponse.json({
    user_code: grant.user_code,
    device_label: grant.device_label,
    status: expired && grant.status === "pending" ? "expired" : grant.status,
    expires_at: grant.expires_at,
    created_at: grant.created_at,
    ip_addr: grant.ip_addr,
    user_agent: grant.user_agent,
  });
}
