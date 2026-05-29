import { NextRequest, NextResponse } from "next/server";

export const runtime = "nodejs";

// Elevation is INVITE-ONLY. Open self-serve sign-up is disabled — accounts are
// created only by accepting an admin invitation (see /api/invitations/accept).
// This endpoint is kept as an explicit, hard 403 so any old client or bookmark
// hitting /signup gets a clear answer instead of silently creating an account.
export async function POST(_req: NextRequest) {
  return NextResponse.json(
    {
      error: "sign-up is invite-only",
      detail: "Accounts are created by invitation. Ask an admin to invite you.",
    },
    { status: 403 },
  );
}
