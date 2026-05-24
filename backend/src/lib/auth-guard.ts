import { NextRequest } from "next/server";
import { verifyAccessToken, AccessClaims } from "./jwt";
import { findActiveUser, findLicenseById, touchLicense, StoreUser } from "./store";

export async function requireAccess(
  req: NextRequest,
): Promise<
  | { ok: true; claims: AccessClaims; user: StoreUser }
  | { ok: false; status: number; error: string }
> {
  const header = req.headers.get("authorization") || "";
  const match = header.match(/^Bearer\s+(.+)$/);
  if (!match) return { ok: false, status: 401, error: "missing bearer token" };

  let claims: AccessClaims;
  try {
    claims = await verifyAccessToken(match[1]);
  } catch {
    return { ok: false, status: 401, error: "invalid or expired token" };
  }

  const license = await findLicenseById(claims.license_id);

  if (!license || license.revoked) {
    return { ok: false, status: 403, error: "license revoked" };
  }

  const active = await findActiveUser(claims.sub);

  if (!active) {
    return { ok: false, status: 402, error: "subscription inactive" };
  }

  await touchLicense(claims.license_id);

  return { ok: true, claims, user: active };
}
