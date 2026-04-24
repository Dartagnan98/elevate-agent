import { NextRequest } from "next/server";
import { verifyAccessToken, AccessClaims } from "./jwt";
import { supabase, DEV_FIXTURE } from "./supabase";

export async function requireAccess(
  req: NextRequest,
): Promise<{ ok: true; claims: AccessClaims } | { ok: false; status: number; error: string }> {
  const header = req.headers.get("authorization") || "";
  const match = header.match(/^Bearer\s+(.+)$/);
  if (!match) return { ok: false, status: 401, error: "missing bearer token" };

  let claims: AccessClaims;
  try {
    claims = await verifyAccessToken(match[1]);
  } catch {
    return { ok: false, status: 401, error: "invalid or expired token" };
  }

  if (DEV_FIXTURE) {
    return { ok: true, claims };
  }

  const { data: license } = await supabase
    .from("licenses")
    .select("id,revoked")
    .eq("id", claims.license_id)
    .maybeSingle();

  if (!license || license.revoked) {
    return { ok: false, status: 403, error: "license revoked" };
  }

  const { data: active } = await supabase
    .from("active_users")
    .select("user_id")
    .eq("user_id", claims.sub)
    .maybeSingle();

  if (!active) {
    return { ok: false, status: 402, error: "subscription inactive" };
  }

  await supabase
    .from("licenses")
    .update({ last_used_at: new Date().toISOString() })
    .eq("id", claims.license_id);

  return { ok: true, claims };
}
