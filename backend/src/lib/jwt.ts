import { SignJWT, jwtVerify } from "jose";
import crypto from "node:crypto";

const DEV_FALLBACK_SECRET = "dev-only-change-me-before-prod";

function resolveSecret(): string {
  const fromEnv = process.env.JWT_SECRET;
  // Fail hard in production: never sign tokens with the publicly-known dev
  // fallback (anyone could forge admin tokens). Only allow it outside prod.
  if (process.env.NODE_ENV === "production") {
    if (!fromEnv || fromEnv === DEV_FALLBACK_SECRET) {
      throw new Error(
        "JWT_SECRET is not set (or is the dev fallback) in production. " +
          "Set a strong, unique JWT_SECRET before starting the server.",
      );
    }
    if (fromEnv.length < 32) {
      throw new Error("JWT_SECRET must be at least 32 characters in production.");
    }
  }
  return fromEnv || DEV_FALLBACK_SECRET;
}

const secret = new TextEncoder().encode(resolveSecret());

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
