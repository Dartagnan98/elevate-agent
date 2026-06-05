/*
 * Surgical re-seed of ONLY the `outreach` skill row in Supabase.
 *
 * Reuses defaultSkills() so the frontmatter/body split + manifest match the
 * normal seed exactly, but touches a single row and bumps version FORWARD
 * (never downgrades) so clients cache-bust cleanly.
 *
 * Usage:
 *   SUPABASE_URL=... SUPABASE_SERVICE_ROLE_KEY=... npx tsx scripts/seed-outreach-only.ts
 */

import { createClient } from "@supabase/supabase-js";
import { defaultSkills } from "../src/lib/skill-seeds";

function env(name: string): string {
  const v = process.env[name];
  if (!v) throw new Error(`missing env: ${name}`);
  return v.replace(/\\n/g, "").trim();
}

class SeedOnlyWebSocket {
  constructor() {
    throw new Error("Realtime is disabled for the seed script");
  }
}

async function main() {
  const sb = createClient(env("SUPABASE_URL"), env("SUPABASE_SERVICE_ROLE_KEY"), {
    auth: { persistSession: false, autoRefreshToken: false },
    db: { schema: "public" },
    realtime: { transport: SeedOnlyWebSocket as never },
  });

  const skill = defaultSkills().find((s) => s.name === "outreach");
  if (!skill) {
    console.error("[seed-outreach] outreach skill not found in defaultSkills()");
    process.exit(1);
  }

  const { data: existing, error: readErr } = await sb
    .from("skills")
    .select("name, version, enabled")
    .eq("name", "outreach")
    .maybeSingle();
  if (readErr) {
    console.error("[seed-outreach] read failed:", readErr.message);
    process.exit(1);
  }

  const currentVersion = Number(existing?.version ?? 0);
  const nextVersion = Math.max(currentVersion + 1, skill.version + 1);

  console.log(
    `[seed-outreach] current v${currentVersion} (${existing ? "exists" : "missing"}) -> writing v${nextVersion}, body ${skill.body.length} chars`,
  );

  const { error } = await sb.from("skills").upsert(
    {
      name: skill.name,
      version: nextVersion,
      tier_required: skill.tier_required,
      manifest: skill.manifest,
      body: skill.body,
      enabled: true,
    },
    { onConflict: "name" },
  );
  if (error) {
    console.error("[seed-outreach] upsert failed:", error.message);
    process.exit(1);
  }
  console.log(`[seed-outreach] ok: outreach now v${nextVersion}`);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
