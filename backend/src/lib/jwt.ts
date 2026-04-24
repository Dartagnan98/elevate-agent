import { SignJWT, jwtVerify } from "jose";
import crypto from "node:crypto";

const secret = new TextEncoder().encode(
  process.env.JWT_SECRET || "dev-only-change-me-before-prod",
);

const ISSUER = "elevate";
const ACCESS_TTL_SECONDS = 60 * 60;               // 1 hour
const REFRESH_TTL_SECONDS = 60 * 60 * 24 * 90;    // 90 days

export type AccessClaims = {
  sub: string;        // user id (uuid)
  email: string;
  tier: "pro" | "builder";
  license_id: string;
};

export async function signAccessToken(claims: AccessClaims): Promise<string> {
  return new SignJWT({ ...claims })
    .setProtectedHeader({ alg: "HS256" })
    .setIssuer(ISSUER)
    .setIssuedAt()
    .setExpirationTime(`${ACCESS_TTL_SECONDS}s`)
    .sign(secret);
}

export async function verifyAccessToken(token: string): Promise<AccessClaims> {
  const { payload } = await jwtVerify(token, secret, { issuer: ISSUER });
  return payload as unknown as AccessClaims;
}

export function generateRefreshToken(): { token: string; hash: string } {
  const token = crypto.randomBytes(32).toString("base64url");
  const hash = crypto.createHash("sha256").update(token).digest("hex");
  return { token, hash };
}

export function hashRefreshToken(token: string): string {
  return crypto.createHash("sha256").update(token).digest("hex");
}

export const TTL = {
  ACCESS_SECONDS: ACCESS_TTL_SECONDS,
  REFRESH_SECONDS: REFRESH_TTL_SECONDS,
};
