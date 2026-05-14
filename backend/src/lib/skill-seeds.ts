import fs from "node:fs";
import path from "node:path";

import { FIXTURE_SKILLS } from "./fixtures";

export type SeedSkill = {
  name: string;
  version: number;
  tier_required: "pro" | "builder";
  manifest: Record<string, unknown>;
  body: string;
};

type SeedRoot = {
  dir: string;
  entitlement: string;
};

function repoRoot(): string {
  const cwd = process.cwd();
  return path.basename(cwd) === "backend" ? path.dirname(cwd) : cwd;
}

function defaultSeedRoots(): SeedRoot[] {
  const root = repoRoot();
  return [
    {
      dir: path.join(root, "cli", "skills", "real-estate-admin"),
      entitlement: "real_estate_admin",
    },
    {
      dir: path.join(root, "cli", "skills", "lead-scorer"),
      entitlement: "real_estate_sales",
    },
    {
      dir: path.join(root, "cli", "skills", "outreach-lanes"),
      entitlement: "real_estate_sales",
    },
    {
      dir: path.join(root, "cli", "skills", "social-content-engine"),
      entitlement: "real_estate_marketing",
    },
    {
      dir: path.join(root, "cli", "skills", "cma"),
      entitlement: "real_estate_cma",
    },
  ];
}

function configuredSeedRoots(): SeedRoot[] {
  const raw = process.env.ELEVATE_HQ_SKILL_SEED_DIRS;
  if (!raw) return defaultSeedRoots();
  return raw
    .split(/[,\n]/)
    .map((entry) => entry.trim())
    .filter(Boolean)
    .map((entry) => {
      const [entitlement, dir] = entry.includes("=")
        ? entry.split("=", 2)
        : ["real_estate_admin", entry];
      return {
        entitlement: entitlement.trim() || "real_estate_admin",
        dir: path.resolve(dir.trim()),
      };
    });
}

function unquote(value: string): string {
  const text = value.trim();
  if (
    (text.startsWith('"') && text.endsWith('"')) ||
    (text.startsWith("'") && text.endsWith("'"))
  ) {
    return text.slice(1, -1);
  }
  return text;
}

function parseList(value: string): string[] {
  const text = value.trim();
  if (!text.startsWith("[") || !text.endsWith("]")) return [];
  return text
    .slice(1, -1)
    .split(",")
    .map((item) => unquote(item))
    .map((item) => item.trim())
    .filter(Boolean);
}

function splitFrontmatter(raw: string): { frontmatter: string; body: string } {
  if (!raw.startsWith("---")) return { frontmatter: "", body: raw };
  const end = raw.indexOf("\n---", 3);
  if (end < 0) return { frontmatter: "", body: raw };
  const after = raw.indexOf("\n", end + 4);
  return {
    frontmatter: raw.slice(3, end).trim(),
    body: raw.slice(after >= 0 ? after + 1 : end + 4),
  };
}

function parseSkillFile(file: string, entitlement: string): SeedSkill | null {
  const raw = fs.readFileSync(file, "utf8");
  const { frontmatter, body } = splitFrontmatter(raw);
  const fallbackName = path.basename(path.dirname(file));
  const manifest: Record<string, unknown> = {
    entitlement,
    source: "repo-seed",
    source_path: path.relative(repoRoot(), file),
  };
  let name = fallbackName;
  let tags: string[] = [];

  for (const line of frontmatter.split(/\r?\n/)) {
    const match = line.match(/^\s*([A-Za-z0-9_.-]+)\s*:\s*(.+?)\s*$/);
    if (!match) continue;
    const key = match[1];
    const value = match[2];
    if (key === "name") {
      name = unquote(value);
    } else if (key === "description") {
      manifest.description = unquote(value);
    } else if (key === "tags") {
      tags = parseList(value);
    }
  }

  const nestedTags = frontmatter.match(/tags:\s*\[([^\]]+)\]/);
  if (tags.length === 0 && nestedTags) {
    tags = parseList(`[${nestedTags[1]}]`);
  }
  if (tags.length > 0) manifest.tags = tags;

  return {
    name,
    version: 1,
    tier_required: "pro",
    manifest,
    body: body.trimStart(),
  };
}

function collectSkillFiles(root: string): string[] {
  if (!fs.existsSync(root)) return [];
  const direct = path.join(root, "SKILL.md");
  if (fs.existsSync(direct)) return [direct];

  return fs
    .readdirSync(root, { withFileTypes: true })
    .filter((entry) => entry.isDirectory())
    .map((entry) => path.join(root, entry.name, "SKILL.md"))
    .filter((file) => fs.existsSync(file));
}

export function defaultSkills(): SeedSkill[] {
  const byName = new Map<string, SeedSkill>();
  for (const skill of FIXTURE_SKILLS) {
    byName.set(skill.name, {
      ...skill,
      tier_required: skill.tier_required as "pro" | "builder",
    });
  }

  for (const root of configuredSeedRoots()) {
    for (const file of collectSkillFiles(root.dir)) {
      const skill = parseSkillFile(file, root.entitlement);
      if (skill) byName.set(skill.name, skill);
    }
  }

  return [...byName.values()].sort((a, b) => a.name.localeCompare(b.name));
}
