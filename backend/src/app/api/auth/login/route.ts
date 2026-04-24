import { NextRequest, NextResponse } from "next/server";
import bcrypt from "bcryptjs";
import { z } from "zod";
import { supabase, DEV_FIXTURE } from "@/lib/supabase";
import { FIXTURE_USER, FIXTURE_LICENSE_ID } from "@/lib/fixtures";
import { signAccessToken, generateRefreshToken, TTL } from "@/lib/jwt";

export const runtime = "nodejs";

const Body = z.object({
  email: z.string().email(),
  password: z.string().min(1),
  device_label: z.string().optional(),
});

export async function POST(req: NextRequest) {
  const parsed = Body.safeParse(await req.json().catch(() => ({})));
  if (!parsed.success) return NextResponse.json({ error: "bad request" }, { status: 400 });
  const { email, password, device_label } = parsed.data;

  if (DEV_FIXTURE) {
    // Any password works against dev@... in fixture mode.
    if (email.toLowerCase() !== FIXTURE_USER.email || password.length < 1) {
      return NextResponse.json({ error: "invalid credentials (fixture)" }, { status: 401 });
    }
    const refresh = generateRefreshToken();
    const access = await signAccessToken({
      sub: FIXTURE_USER.id,
      email: FIXTURE_USER.email,
      tier: FIXTURE_USER.tier,
      license_id: FIXTURE_LICENSE_ID,
    });
    return NextResponse.json({
      access_token: access,
      refresh_token: refresh.token,
      license_id: FIXTURE_LICENSE_ID,
      tier: FIXTURE_USER.tier,
      expires_in: TTL.ACCESS_SECONDS,
    });
  }

  const { data: user } = await supabase
    .from("users")
    .select("id,email,password_hash")
    .eq("email", email.toLowerCase())
    .maybeSingle();

  if (!user || !user.password_hash || !(await bcrypt.compare(password, user.password_hash))) {
    return NextResponse.json({ error: "invalid credentials" }, { status: 401 });
  }

  const { data: active } = await supabase
    .from("active_users")
    .select("user_id,tier,status,current_period_end")
    .eq("user_id", user.id)
    .maybeSingle();

  if (!active) {
    return NextResponse.json({ error: "no active subscription" }, { status: 402 });
  }

  const refresh = generateRefreshToken();
  const { data: license, error: licenseErr } = await supabase
    .from("licenses")
    .insert({
      user_id: user.id,
      device_label: device_label || null,
      refresh_token_hash: refresh.hash,
    })
    .select("id")
    .single();

  if (licenseErr || !license) {
    return NextResponse.json({ error: "could not issue license" }, { status: 500 });
  }

  const access = await signAccessToken({
    sub: user.id,
    email: user.email,
    tier: (active.tier as "pro" | "builder") ?? "pro",
    license_id: license.id,
  });

  return NextResponse.json({
    access_token: access,
    refresh_token: refresh.token,
    license_id: license.id,
    tier: active.tier,
    expires_in: TTL.ACCESS_SECONDS,
  });
}
