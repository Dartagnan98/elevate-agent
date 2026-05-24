import { NextRequest, NextResponse } from "next/server";
import { requireAdmin } from "@/lib/admin-guard";
import { searchAll } from "@/lib/store";

export const runtime = "nodejs";

export async function GET(req: NextRequest) {
  const guard = await requireAdmin(req);
  if (!guard.ok) return NextResponse.json({ error: guard.error }, { status: guard.status });

  const q = req.nextUrl.searchParams.get("q") || "";
  const limit = Math.min(50, Math.max(1, Number(req.nextUrl.searchParams.get("limit")) || 10));
  const results = await searchAll(q, limit);
  return NextResponse.json(results);
}
