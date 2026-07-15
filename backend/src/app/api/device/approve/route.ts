import { NextRequest, NextResponse } from "next/server";
import { z } from "zod";
import { requireAccess } from "@/lib/auth-guard";
import {
  approveDeviceGrant,
  findDeviceGrantByUserCode,
} from "@/lib/store";
import { generateRefreshToken } from "@/lib/jwt";

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

  // The database RPC compare-and-swaps an untouched, unexpired pending grant,
  // creates the matching license, stashes this one-shot refresh bearer, and
  // writes the audit event in one transaction. A concurrent loser cannot
  // create a license or overwrite the winner's account/token binding.
  const refresh = generateRefreshToken();
  let approval: Awaited<ReturnType<typeof approveDeviceGrant>>;
  try {
    approval = await approveDeviceGrant({
      id: grant.id,
      userId: auth.user.id,
      refreshTokenHash: refresh.hash,
      refreshTokenPlain: refresh.token,
    });
  } catch {
    // The RPC is transactional: an error rolls back ownership, license,
    // refresh stash, and audit state together.
    return NextResponse.json({ error: "approval_failed" }, { status: 500 });
  }

  if (approval.result === "not_found") {
    return NextResponse.json({ error: "not_found" }, { status: 404 });
  }
  if (approval.result === "expired") {
    return NextResponse.json({ error: "expired" }, { status: 410 });
  }
  if (approval.result === "invalid") {
    return NextResponse.json({ error: "invalid_grant" }, { status: 409 });
  }
  if (approval.result === "conflict") {
    return NextResponse.json(
      { error: `already ${approval.grant_status}` },
      { status: 409 },
    );
  }

  return NextResponse.json({ ok: true });
}
