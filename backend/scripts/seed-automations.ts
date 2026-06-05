/*
 * Seeds the `automations` table from defaultAutomations().
 *
 * Idempotent: upserts by name. Bumps version forward (never down) so clients
 * cache-bust cleanly, same convention as seed-outreach-only.ts.
 *
 * Usage:
 *   SUPABASE_URL=... SUPABASE_SERVICE_ROLE_KEY=... npx tsx scripts/seed-automations.ts
 */

import { createClient } from "@supabase/supabase-js";
import { defaultAutomations } from "../src/lib/automation-seeds";

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

  const seeds = defaultAutomations();
  for (const a of seeds) {
    const { data: existing } = await sb
      .from("automations")
      .select("name, version")
      .eq("name", a.name)
      .maybeSingle();
    const currentVersion = Number(existing?.version ?? 0);
    const nextVersion = Math.max(currentVersion + 1, a.version);

    const { error } = await sb.from("automations").upsert(
      {
        name: a.name,
        surface: a.surface,
        kind: a.kind,
        schedule: a.schedule,
        skill: a.skill,
        prompt: a.prompt,
        deliver: a.deliver,
        spec: a.spec,
        tier_required: a.tier_required,
        manifest: a.manifest,
        version: nextVersion,
        enabled: true,
      },
      { onConflict: "name" },
    );
    if (error) {
      console.error(`[seed-automations] ${a.name} failed:`, error.message);
      process.exit(1);
    }
    console.log(`[seed-automations] ok ${a.name} (${a.kind}/${a.surface}) v${nextVersion}`);
  }
  console.log(`[seed-automations] done: ${seeds.length} automations`);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
