import type { StoreSkill, StoreUser } from "./store";

const TIER_RANK: Record<string, number> = { pro: 1, builder: 2 };

function asList(value: unknown): string[] {
  if (!value) return [];
  if (typeof value === "string") return [value];
  if (!Array.isArray(value)) return [];
  return value.map((entry) => String(entry || "").trim()).filter(Boolean);
}

export function requiredEntitlements(manifest: Record<string, unknown>): string[] {
  const access = manifest.access && typeof manifest.access === "object" ? manifest.access : {};
  const required = [
    ...asList(manifest.entitlement),
    ...asList(manifest.requires_entitlement),
    ...asList(manifest.required_entitlement),
    ...asList(manifest.entitlements),
    ...asList(manifest.requires_entitlements),
    ...asList(manifest.required_entitlements),
    ...asList((access as Record<string, unknown>).entitlement),
    ...asList((access as Record<string, unknown>).requires_entitlement),
    ...asList((access as Record<string, unknown>).required_entitlement),
    ...asList((access as Record<string, unknown>).entitlements),
    ...asList((access as Record<string, unknown>).requires_entitlements),
    ...asList((access as Record<string, unknown>).required_entitlements),
  ];

  return [...new Set(required)];
}

// Generic tier + entitlement gate for any catalog item carrying
// { tier_required, manifest } — skills and automations share the same rules.
export function userCanAccessGated(
  user: StoreUser,
  item: { tier_required: string; manifest: Record<string, unknown> },
): boolean {
  const userRank = TIER_RANK[user.tier] ?? 0;
  const requiredRank = TIER_RANK[item.tier_required] ?? 999;
  if (userRank < requiredRank) return false;

  const required = requiredEntitlements(item.manifest);
  if (required.length === 0) return true;

  const granted = new Set(user.entitlements || []);
  return required.every((entitlement) => granted.has(entitlement));
}

export function userCanAccessSkill(user: StoreUser, skill: StoreSkill): boolean {
  return userCanAccessGated(user, skill);
}
