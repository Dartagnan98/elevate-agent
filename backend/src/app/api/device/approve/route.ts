import { NextRequest, NextResponse } from "next/server";
import { z } from "zod";
import { requireAccess } from "@/lib/auth-guard";
import {
  approveDeviceGrant,
  createLicense,
  findDeviceGrantByUserCode,
  logAdminAction,
} from "@/lib/store";
import { generateRefreshToken } from "@/lib/jwt";
import { supabase } from "@/lib/supabase";

export const runtime = "nodejs";

const Body = z.object({
  user_code: z.string().min(4).max(20),
});

export async function POST(req: NextRequest) {
  const auth = await requireAccess(req);
  if (!auth.ok) {
    return NextResponse.json({ error: auth.error }, { status: auth.status });
  }

  const parsed = Body.safeParse(await req.json().catch(() => ({})));
  if (!parsed.success) {
    return NextResponse.json({ error: "bad request" }, { status: 400 });
  }

  const grant = await findDeviceGrantByUserCode(parsed.data.user_code.trim().toUpperCase());
  if (!grant) {
    return NextResponse.json({ error: "not_found" }, { status: 404 });
  }

  if (new Date(grant.expires_at).getTime() < Date.now()) {
    return NextResponse.json({ error: "expired" }, { status: 410 });
  }

  if (grant.status !== "pending") {
    return NextResponse.json({ error: `already ${grant.status}` }, { status: 409 });
  }

  // Pre-create the license so the polling CLI can claim its tokens.
  // Stash the raw refresh token in the device_grants row — it lives there
  // until the CLI polls successfully (typically <30s), then nulled out.
  const refresh = generateRefreshToken();
  const license = await createLicense(
    auth.user.id,
    refresh.hash,
    grant.device_label || "linked-device",
  );

  // Update grant with raw refresh stash before flipping status to approved.
  const { error: stashErr } = await supabase()
    .from("device_grants")
    .update({ refresh_token_plain: refresh.token })
    .eq("id", grant.id);
  if (stashErr) throw stashErr;

  await approveDeviceGrant(grant.id, auth.user.id, license.id);

  await logAdminAction({
    actor_user_id: auth.user.id,
    target_user_id: auth.user.id,
    action: "device.link.approved",
    payload: {
      grant_id: grant.id,
      user_code: grant.user_code,
      device_label: grant.device_label,
      license_id: license.id,
    },
  });

  return NextResponse.json({ ok: true });
}
