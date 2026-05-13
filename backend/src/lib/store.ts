import bcrypt from "bcryptjs";
import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";

import { defaultSkills } from "./skill-seeds";

export type StoreUser = {
  id: string;
  email: string;
  password_hash: string;
  stripe_customer: string | null;
  tier: "pro" | "builder";
  status: "active" | "trialing" | "inactive" | "canceled" | "past_due";
  current_period_end: string | null;
  entitlements: string[];
  created_at: string;
  updated_at: string;
};

export type StoreLicense = {
  id: string;
  user_id: string;
  device_label: string | null;
  refresh_token_hash: string;
  revoked: boolean;
  last_used_at: string | null;
  created_at: string;
};

export type StoreSkill = {
  name: string;
  version: number;
  tier_required: "pro" | "builder";
  manifest: Record<string, unknown>;
  body: string;
  enabled: boolean;
  updated_at: string;
  created_at: string;
};

type SkillInvocation = {
  id: string;
  user_id: string;
  skill_name: string;
  args_hash: string | null;
  ip_address: string | null;
  user_agent: string | null;
  invoked_at: string;
};

type StoreData = {
  users: StoreUser[];
  licenses: StoreLicense[];
  skills: StoreSkill[];
  skill_invocations: SkillInvocation[];
};

const DEFAULT_ENTITLEMENTS = [
  "real_estate_sales",
  "real_estate_marketing",
  "real_estate_admin",
  "real_estate_cma",
];

function now(): string {
  return new Date().toISOString();
}

function id(): string {
  return crypto.randomUUID();
}

function storePath(): string {
  return (
    process.env.ELEVATE_HQ_STORE_PATH ||
    path.join(process.cwd(), ".data", "elevation-hq-store.json")
  );
}

function defaultUser(): StoreUser {
  const timestamp = now();
  const email = (
    process.env.ELEVATE_HQ_DEV_EMAIL || "dev@elevationrealestatehq.com"
  ).toLowerCase();
  const password = process.env.ELEVATE_HQ_DEV_PASSWORD || "elevate-dev";
  const tier = (process.env.ELEVATE_HQ_DEV_TIER === "builder" ? "builder" : "pro") as
    | "pro"
    | "builder";
  const entitlements = (
    process.env.ELEVATE_HQ_DEV_ENTITLEMENTS || DEFAULT_ENTITLEMENTS.join(",")
  )
    .split(",")
    .map((entry) => entry.trim())
    .filter(Boolean);

  return {
    id: id(),
    email,
    password_hash: bcrypt.hashSync(password, 10),
    stripe_customer: process.env.ELEVATE_HQ_DEV_STRIPE_CUSTOMER || null,
    tier,
    status: "active",
    current_period_end: null,
    entitlements,
    created_at: timestamp,
    updated_at: timestamp,
  };
}

function defaultStore(): StoreData {
  const timestamp = now();
  return {
    users: [defaultUser()],
    licenses: [],
    skills: defaultSkills().map((skill) => ({
      ...skill,
      tier_required: skill.tier_required as "pro" | "builder",
      enabled: true,
      updated_at: timestamp,
      created_at: timestamp,
    })),
    skill_invocations: [],
  };
}

function skillSignature(skill: StoreSkill): string {
  return JSON.stringify({
    name: skill.name,
    version: skill.version,
    tier_required: skill.tier_required,
    manifest: skill.manifest,
    body: skill.body,
    enabled: skill.enabled,
  });
}

function reconcileSeedSkills(data: StoreData): { data: StoreData; changed: boolean } {
  const timestamp = now();
  const existing = new Map(data.skills.map((skill) => [skill.name, skill]));
  let changed = false;

  for (const seed of defaultSkills()) {
    const next: StoreSkill = {
      ...seed,
      tier_required: seed.tier_required as "pro" | "builder",
      enabled: true,
      updated_at: timestamp,
      created_at: existing.get(seed.name)?.created_at || timestamp,
    };
    const current = existing.get(seed.name);
    if (!current) {
      data.skills.push(next);
      changed = true;
      continue;
    }

    const isSeedManaged =
      current.manifest?.source === "repo-seed" ||
      seed.manifest?.source === "repo-seed" ||
      ["cma-generator", "listing-outreach", "builder-only-skill"].includes(current.name);
    if (isSeedManaged && skillSignature(current) !== skillSignature(next)) {
      Object.assign(current, next);
      changed = true;
    }
  }

  if (changed) {
    data.skills.sort((a, b) => a.name.localeCompare(b.name));
  }
  return { data, changed };
}

function readStore(): StoreData {
  const file = storePath();
  fs.mkdirSync(path.dirname(file), { recursive: true });
  if (!fs.existsSync(file)) {
    const seed = defaultStore();
    fs.writeFileSync(file, JSON.stringify(seed, null, 2));
    return seed;
  }
  const parsed = JSON.parse(fs.readFileSync(file, "utf8")) as StoreData;
  const reconciled = reconcileSeedSkills(parsed);
  if (reconciled.changed) writeStore(reconciled.data);
  return reconciled.data;
}

function writeStore(data: StoreData): void {
  const file = storePath();
  fs.mkdirSync(path.dirname(file), { recursive: true });
  const tmp = `${file}.tmp`;
  fs.writeFileSync(tmp, JSON.stringify(data, null, 2));
  fs.renameSync(tmp, file);
}

export function findUserByEmail(email: string): StoreUser | null {
  const data = readStore();
  return data.users.find((user) => user.email === email.toLowerCase()) || null;
}

export function findActiveUser(userId: string): StoreUser | null {
  const data = readStore();
  const user = data.users.find((entry) => entry.id === userId) || null;
  if (!user || !["active", "trialing"].includes(user.status)) return null;
  return user;
}

export function findUserByStripeCustomer(stripeCustomer: string): StoreUser | null {
  const data = readStore();
  return data.users.find((user) => user.stripe_customer === stripeCustomer) || null;
}

export function createLicense(
  userId: string,
  refreshTokenHash: string,
  deviceLabel?: string | null,
): StoreLicense {
  const data = readStore();
  const license: StoreLicense = {
    id: id(),
    user_id: userId,
    device_label: deviceLabel || null,
    refresh_token_hash: refreshTokenHash,
    revoked: false,
    last_used_at: null,
    created_at: now(),
  };
  data.licenses.push(license);
  writeStore(data);
  return license;
}

export function findLicenseByRefreshHash(hash: string): StoreLicense | null {
  const data = readStore();
  return data.licenses.find((license) => license.refresh_token_hash === hash) || null;
}

export function findLicenseById(licenseId: string): StoreLicense | null {
  const data = readStore();
  return data.licenses.find((license) => license.id === licenseId) || null;
}

export function rotateLicenseRefreshToken(licenseId: string, nextHash: string): void {
  const data = readStore();
  const license = data.licenses.find((entry) => entry.id === licenseId);
  if (!license) return;
  license.refresh_token_hash = nextHash;
  license.last_used_at = now();
  writeStore(data);
}

export function touchLicense(licenseId: string): void {
  const data = readStore();
  const license = data.licenses.find((entry) => entry.id === licenseId);
  if (!license) return;
  license.last_used_at = now();
  writeStore(data);
}

export function revokeLicense(licenseId: string): void {
  const data = readStore();
  const license = data.licenses.find((entry) => entry.id === licenseId);
  if (!license) return;
  license.revoked = true;
  writeStore(data);
}

export function revokeLicensesForUser(userId: string): void {
  const data = readStore();
  let changed = false;
  for (const license of data.licenses) {
    if (license.user_id === userId) {
      license.revoked = true;
      changed = true;
    }
  }
  if (changed) writeStore(data);
}

export function updateUserSubscription(
  userId: string,
  values: Partial<
    Pick<StoreUser, "status" | "tier" | "current_period_end" | "stripe_customer">
  >,
): void {
  const data = readStore();
  const user = data.users.find((entry) => entry.id === userId);
  if (!user) return;
  Object.assign(user, values, { updated_at: now() });
  writeStore(data);
}

export function listEnabledSkills(): StoreSkill[] {
  const data = readStore();
  return data.skills.filter((skill) => skill.enabled).sort((a, b) => a.name.localeCompare(b.name));
}

export function getEnabledSkill(name: string): StoreSkill | null {
  const data = readStore();
  return data.skills.find((skill) => skill.name === name && skill.enabled) || null;
}

export function logSkillInvocation(input: Omit<SkillInvocation, "id" | "invoked_at">): void {
  const data = readStore();
  data.skill_invocations.push({ id: id(), invoked_at: now(), ...input });
  writeStore(data);
}
