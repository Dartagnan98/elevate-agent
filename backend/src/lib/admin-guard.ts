import { NextRequest } from "next/server";
import { requireAccess } from "./auth-guard";
import { AccessClaims } from "./jwt";
import { StoreUser } from "./store";

export async function requireAdmin(
  req: NextRequest,
): Promise<
  | { ok: true; claims: AccessClaims; user: StoreUser }
  | { ok: false; status: number; error: string }
> {
  const guard = await requireAccess(req);
  if (!guard.ok) return guard;
  if (guard.user.role !== "owner" && guard.user.role !== "admin") {
    return { ok: false, status: 403, error: "admin role required" };
  }
  return guard;
}
