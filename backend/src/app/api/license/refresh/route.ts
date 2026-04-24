import { NextRequest, NextResponse } from "next/server";
import { z } from "zod";
import { supabase, DEV_FIXTURE } from "@/lib/supabase";
import { FIXTURE_USER, FIXTURE_LICENSE_ID } from "@/lib/fixtures";
import {
  signAccessToken,
  generateRefreshToken,
  hashRefreshToken,
  TTL,
} from "@/lib/jwt";

export const runtime = "nodejs";

const Body = z.object({ refresh_token: z.string().min(1) });

export async function POST(req: NextRequest) {
  const parsed = Body.safeParse(await req.json().catch(() => ({})));
  if (!parsed.success) return NextResponse.json({ error: "bad request" }, { status: 400 });

  if (DEV_FIXTURE) {
    const next = generateRefreshToken();
    const access = await signAccessToken({
      sub: FIXTURE_USER.id,
      email: FIXTURE_USER.email,
      tier: FIXTURE_USER.tier,
      license_id: FIXTURE_LICENSE_ID,
    });
    return NextResponse.json({
      access_token: access,
      refresh_token: next.token,
      expires_in: TTL.ACCESS_SECONDS,
    });
  }

  const oldHash = hashRefreshToken(parsed.data.refresh_token);
  const { data: license } = await supabase
    .from("licenses")
    .select("id,user_id,revoked")
    .eq("refresh_token_hash", oldHash)
    .maybeSingle();

  if (!license || license.revoked) {
    return NextResponse.json({ error: "invalid or revoked refresh token" }, { status: 401 });
  }

  const { data: active } = await supabase
    .from("active_users")
    .select("user_id,email,tier")
    .eq("user_id", license.user_id)
    .maybeSingle();

  if (!active) {
    await supabase.from("licenses").update({ revoked: true }).eq("id", license.id);
    return NextResponse.json({ error: "subscription inactive" }, { status: 402 });
  }

  // rotate refresh token
  const next = generateRefreshToken();
  await supabase
    .from("licenses")
    .update({ refresh_token_hash: next.hash, last_used_at: new Date().toISOString() })
    .eq("id", license.id);

  const access = await signAccessToken({
    sub: license.user_id,
    email: active.email,
    tier: (active.tier as "pro" | "builder") ?? "pro",
    license_id: license.id,
  });

  return NextResponse.json({
    access_token: access,
    refresh_token: next.token,
    expires_in: TTL.ACCESS_SECONDS,
  });
}
