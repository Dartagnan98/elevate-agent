/*
 * Seeds a Supabase project with optional demo users and bundled skills.
 *
 * Usage:
 *   SUPABASE_URL=... \
 *   SUPABASE_SERVICE_ROLE_KEY=... \
 *   OWNER_EMAIL=owner@example.com OWNER_PASSWORD=... \
 *   AGENT_EMAIL=agent@example.com AGENT_PASSWORD=... \
 *   npx tsx scripts/seed-supabase.ts
 *
 * Idempotent: re-running upserts by email.
 */

import bcrypt from "bcryptjs";
import { createClient } from "@supabase/supabase-js";

import { defaultSkills } from "../src/lib/skill-seeds";

type SeedUser = {
  email: string;
  password: string;
  tier: "pro" | "builder";
  status: "active";
  role: "owner" | "admin" | "user";
  entitlements: string[];
  is_developer?: boolean;
};

function env(name: string, fallback?: string): string {
  const v = process.env[name] ?? fallback;
  if (!v) throw new Error(`missing env: ${name}`);
  return v.replace(/\\n/g, "").trim();
}

function flag(name: string): boolean {
  return ["1", "true", "yes", "on"].includes(String(process.env[name] || "").toLowerCase());
}

class SeedOnlyWebSocket {
  constructor() {
    throw new Error("Realtime is disabled for the seed script");
  }
}

async function main() {
  const url = env("SUPABASE_URL");
  const key = env("SUPABASE_SERVICE_ROLE_KEY");
  const sb = createClient(url, key, {
    auth: { persistSession: false, autoRefreshToken: false },
    db: { schema: "public" },
    realtime: { transport: SeedOnlyWebSocket as never },
  });

  const skillsOnly = flag("SEED_SKILLS_ONLY");

  if (!skillsOnly) {
    const users: SeedUser[] = [
      {
        email: env("OWNER_EMAIL", "owner@example.com"),
        password: env("OWNER_PASSWORD"),
        tier: "builder",
        status: "active",
        role: "owner",
        entitlements: [
          "real_estate_sales",
          "real_estate_marketing",
          "real_estate_admin",
          "real_estate_cma",
        ],
        is_developer: true,
      },
      {
        email: env("AGENT_EMAIL", "agent@example.com"),
        password: env("AGENT_PASSWORD"),
        tier: "pro",
        status: "active",
        role: "user",
        entitlements: [
          "real_estate_sales",
          "real_estate_marketing",
          "real_estate_admin",
          "real_estate_cma",
        ],
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
            is_developer: u.is_developer ?? false,
          },
          { onConflict: "email" },
        )
        .select("id, email, tier, role, entitlements, is_developer")
        .single();
      if (error) {
        console.error(`[seed] ${u.email} failed:`, error.message);
        process.exit(1);
      }
      console.log(`[seed] ok ${data.email} (${data.role}/${data.tier}) entitlements=${JSON.stringify(data.entitlements)} dev=${data.is_developer}`);
    }
  } else {
    console.log("[seed] user seed skipped (SEED_SKILLS_ONLY=1)");
  }

  const skills = defaultSkills();
  for (const skill of skills) {
    const { error } = await sb
      .from("skills")
      .upsert(
        {
          name: skill.name,
          version: skill.version,
          tier_required: skill.tier_required,
          manifest: skill.manifest,
          body: skill.body,
        },
        { onConflict: "name" },
      );
    if (error) {
      console.error(`[seed] skill ${skill.name} failed:`, error.message);
      process.exit(1);
    }
  }
  console.log(`[seed] ok ${skills.length} skills`);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
