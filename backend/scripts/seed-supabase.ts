/*
 * Seeds the elevate-hq Supabase project with the two real users.
 *
 * Usage:
 *   SUPABASE_URL=... \
 *   SUPABASE_SERVICE_ROLE_KEY=... \
 *   OWNER_EMAIL=dartagnan@ctrlstrategies.com OWNER_PASSWORD=... \
 *   SKYLEIGH_EMAIL=skyleigh@... SKYLEIGH_PASSWORD=... \
 *   npx tsx scripts/seed-supabase.ts
 *
 * Idempotent: re-running upserts by email.
 */

import bcrypt from "bcryptjs";
import { createClient } from "@supabase/supabase-js";

type SeedUser = {
  email: string;
  password: string;
  tier: "pro" | "builder";
  status: "active";
  role: "owner" | "admin" | "user";
  entitlements: string[];
};

function env(name: string, fallback?: string): string {
  const v = process.env[name] ?? fallback;
  if (!v) throw new Error(`missing env: ${name}`);
  return v;
}

async function main() {
  const url = env("SUPABASE_URL");
  const key = env("SUPABASE_SERVICE_ROLE_KEY");
  const sb = createClient(url, key, {
    auth: { persistSession: false, autoRefreshToken: false },
    db: { schema: "public" },
  });

  const users: SeedUser[] = [
    {
      email: env("OWNER_EMAIL", "dartagnan@ctrlstrategies.com"),
      password: env("OWNER_PASSWORD"),
      tier: "builder",
      status: "active",
      role: "owner",
      entitlements: [],
    },
    {
      email: env("SKYLEIGH_EMAIL", "skyleigh.mccallum@exprealty.com"),
      password: env("SKYLEIGH_PASSWORD"),
      tier: "pro",
      status: "active",
      role: "user",
      entitlements: ["real_estate", "cma", "outreach"],
    },
  ];

  for (const u of users) {
    const password_hash = await bcrypt.hash(u.password, 12);
    const { data, error } = await sb
      .from("users")
      .upsert(
        {
          email: u.email.toLowerCase(),
          password_hash,
          tier: u.tier,
          status: u.status,
          role: u.role,
          entitlements: u.entitlements,
        },
        { onConflict: "email" },
      )
      .select("id, email, tier, role, entitlements")
      .single();
    if (error) {
      console.error(`[seed] ${u.email} failed:`, error.message);
      process.exit(1);
    }
    console.log(`[seed] ok ${data.email} (${data.role}/${data.tier}) entitlements=${JSON.stringify(data.entitlements)}`);
  }
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
