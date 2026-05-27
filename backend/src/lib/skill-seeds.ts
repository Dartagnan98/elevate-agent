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
  category: string;
  dashboardModules?: string[];
};

type ParseSkillOptions = {
  name?: string;
  source?: string;
  sourcePathRoot?: string;
  tierRequired?: "pro" | "builder";
  manifest?: Record<string, unknown>;
};

type ContentPackSkill = {
  name?: unknown;
  path?: unknown;
  entitlement?: unknown;
  tier_required?: unknown;
  tierRequired?: unknown;
  category?: unknown;
  skillCategory?: unknown;
  section?: unknown;
  sectionLabel?: unknown;
  dashboardModules?: unknown;
  dashboard_modules?: unknown;
  tags?: unknown;
};

type ContentPackManifest = {
  id?: unknown;
  label?: unknown;
  version?: unknown;
  description?: unknown;
  skillsRoot?: unknown;
  skills_root?: unknown;
  defaultJobState?: unknown;
  default_job_state?: unknown;
  skills?: unknown;
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
      category: "real-estate-admin",
    },
    {
      dir: path.join(root, "cli", "skills", "lead-scorer"),
      entitlement: "real_estate_sales",
      category: "real-estate-sales",
    },
    {
      dir: path.join(root, "cli", "skills", "outreach-lanes"),
      entitlement: "real_estate_sales",
      category: "real-estate-sales",
    },
    {
      dir: path.join(root, "cli", "skills", "social-content-engine"),
      entitlement: "real_estate_marketing",
      category: "real-estate-social-media",
      dashboardModules: ["real_estate_marketing"],
    },
    {
      dir: path.join(root, "cli", "skills", "cma"),
      entitlement: "real_estate_cma",
      category: "real-estate-marketing",
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
        category: "real-estate-admin",
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

function frontmatterValue(lines: string[], index: number, rawValue: string): { value: string; nextIndex: number } {
  const marker = rawValue.trim();
  if (marker !== ">" && marker !== "|") return { value: rawValue, nextIndex: index };

  const block: string[] = [];
  let nextIndex = index;
  for (let cursor = index + 1; cursor < lines.length; cursor += 1) {
    const line = lines[cursor];
    if (/^\s+[^\s].*$/.test(line)) {
      block.push(line.trim());
      nextIndex = cursor;
      continue;
    }
    break;
  }
  return {
    value: marker === ">" ? block.join(" ") : block.join("\n"),
    nextIndex,
  };
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

function normalizeTier(value: unknown): "pro" | "builder" {
  return value === "builder" ? "builder" : "pro";
}

function parseSkillFile(
  file: string,
  entitlement: string,
  options: ParseSkillOptions = {},
): SeedSkill | null {
  const raw = fs.readFileSync(file, "utf8");
  const { frontmatter, body } = splitFrontmatter(raw);
  const fallbackName = path.basename(path.dirname(file));
  const sourceRoot = options.sourcePathRoot || repoRoot();
  const manifest: Record<string, unknown> = {
    entitlement,
    source: options.source || "repo-seed",
    source_path: path.relative(sourceRoot, file),
  };
  let name = options.name || fallbackName;
  let tags: string[] = [];

  const lines = frontmatter.split(/\r?\n/);
  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index];
    const match = line.match(/^([A-Za-z0-9_.-]+)\s*:\s*(.+?)\s*$/);
    if (!match) continue;
    const key = match[1];
    const parsedValue = frontmatterValue(lines, index, match[2]);
    const value = parsedValue.value;
    index = parsedValue.nextIndex;
    if (key === "name") {
      name = options.name || unquote(value);
    } else if (key === "description") {
      manifest.description = unquote(value);
    } else if (key === "category") {
      manifest.category = unquote(value);
    } else if (key === "tags") {
      tags = parseList(value);
    }
  }

  const nestedTags = frontmatter.match(/tags:\s*\[([^\]]+)\]/);
  if (tags.length === 0 && nestedTags) {
    tags = parseList(`[${nestedTags[1]}]`);
  }
  if (tags.length > 0) manifest.tags = tags;
  if (options.manifest) Object.assign(manifest, options.manifest);

  return {
    name,
    version: 1,
    tier_required: options.tierRequired || "pro",
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

function splitConfiguredPaths(raw: string | undefined): string[] {
  if (!raw) return [];
  return raw
    .split(/[,\n]/)
    .map((entry) => entry.trim())
    .filter(Boolean)
    .map((entry) => path.resolve(entry));
}

function defaultContentPackManifestCandidates(): string[] {
  const root = repoRoot();
  const home = process.env.HOME ? path.join(process.env.HOME, "elevate-premium") : "";
  return [
    path.resolve(root, "..", "elevate-premium", "elevate-pack.json"),
    path.resolve(root, "..", "elevate-premium", "content-pack.json"),
    home ? path.join(home, "elevate-pack.json") : "",
    home ? path.join(home, "content-pack.json") : "",
  ].filter(Boolean);
}

function configuredContentPackManifests(): string[] {
  const explicit = splitConfiguredPaths(
    process.env.ELEVATE_HQ_CONTENT_PACK_MANIFESTS ||
      process.env.ELEVATE_CONTENT_PACK_MANIFESTS,
  );
  const candidates = explicit.length > 0 ? explicit : defaultContentPackManifestCandidates();
  const seen = new Set<string>();
  const result: string[] = [];
  for (const candidate of candidates) {
    const resolved = path.resolve(candidate);
    if (seen.has(resolved) || !fs.existsSync(resolved)) continue;
    seen.add(resolved);
    result.push(resolved);
  }
  return result;
}

function asText(value: unknown): string {
  return String(value || "").trim();
}

function asList(value: unknown): string[] {
  if (!value) return [];
  const values = Array.isArray(value) ? value : [value];
  return values.map((entry) => asText(entry)).filter(Boolean);
}

function readJsonFile(file: string): ContentPackManifest | null {
  try {
    const parsed = JSON.parse(fs.readFileSync(file, "utf8"));
    return parsed && typeof parsed === "object" ? (parsed as ContentPackManifest) : null;
  } catch {
    return null;
  }
}

function contentPackSkills(): SeedSkill[] {
  const result: SeedSkill[] = [];
  for (const manifestPath of configuredContentPackManifests()) {
    const pack = readJsonFile(manifestPath);
    if (!pack || !Array.isArray(pack.skills)) continue;

    const manifestDir = path.dirname(manifestPath);
    const packId = asText(pack.id) || path.basename(manifestDir);
    const packLabel = asText(pack.label) || packId;
    const packVersion = asText(pack.version);
    const skillsRoot = asText(pack.skillsRoot) || asText(pack.skills_root) || ".";
    const skillsRootPath = path.resolve(manifestDir, skillsRoot);
    const defaultJobState = asText(pack.defaultJobState) || asText(pack.default_job_state);

    for (const rawSkill of pack.skills as ContentPackSkill[]) {
      if (!rawSkill || typeof rawSkill !== "object") continue;
      const relPath = asText(rawSkill.path) || asText(rawSkill.name);
      const entitlement = asText(rawSkill.entitlement);
      if (!relPath || !entitlement) continue;

      const skillPath = path.resolve(skillsRootPath, relPath);
      const skillFile = skillPath.endsWith(".md") ? skillPath : path.join(skillPath, "SKILL.md");
      if (!fs.existsSync(skillFile)) continue;

      const skillName = asText(rawSkill.name);
      const category =
        asText(rawSkill.category) || asText(rawSkill.skillCategory);
      const section = asText(rawSkill.section) || asText(rawSkill.sectionLabel);
      const dashboardModules = [
        ...asList(rawSkill.dashboardModules),
        ...asList(rawSkill.dashboard_modules),
      ];
      const extraTags = asList(rawSkill.tags);
      const extraManifest: Record<string, unknown> = {
        entitlement,
        requires_entitlement: entitlement,
        source: "content-pack",
        content_pack: {
          id: packId,
          label: packLabel,
          version: packVersion || undefined,
          manifest_path: manifestPath,
        },
        pack_id: packId,
        pack_label: packLabel,
        pack_version: packVersion || undefined,
      };
      if (category) extraManifest.category = category;
      if (section) extraManifest.section = section;
      if (dashboardModules.length > 0) extraManifest.dashboard_modules = dashboardModules;
      if (defaultJobState) extraManifest.default_job_state = defaultJobState;
      if (extraTags.length > 0) extraManifest.tags = extraTags;

      const skill = parseSkillFile(skillFile, entitlement, {
        name: skillName || undefined,
        source: "content-pack",
        sourcePathRoot: manifestDir,
        tierRequired: normalizeTier(rawSkill.tier_required || rawSkill.tierRequired),
        manifest: extraManifest,
      });
      if (skill) result.push(skill);
    }
  }
  return result;
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
      const manifest: Record<string, unknown> = { category: root.category };
      if (root.dashboardModules?.length) {
        manifest.dashboard_modules = root.dashboardModules;
      }
      const skill = parseSkillFile(file, root.entitlement, { manifest });
      if (skill) byName.set(skill.name, skill);
    }
  }

  for (const skill of contentPackSkills()) {
    byName.set(skill.name, skill);
  }

  return [...byName.values()].sort((a, b) => a.name.localeCompare(b.name));
}
