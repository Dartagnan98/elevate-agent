import type { StatusResponse } from "@/lib/api";
import { isRealtorBetaStatus } from "@/lib/beta-runtime";

export type ApprovalChoice = "always" | "deny" | "once" | "session";
export type ApprovalSurfacePolicy = "restricted" | "standard";
export type PermissionModeId =
  | "acceptEdits"
  | "bypassPermissions"
  | "default"
  | "plan";

const REALTOR_BETA_PERMISSION_MODES = new Set<PermissionModeId>([
  "default",
  "plan",
]);

export function approvalSurfacePolicyForStatus(
  status: StatusResponse | null | undefined,
): ApprovalSurfacePolicy {
  // Do not briefly advertise unsupported authority while the signed runtime
  // receipt is still loading (or could not be read). A confirmed non-Beta
  // status restores the complete Stable surface unchanged.
  if (status == null) return "restricted";
  return isRealtorBetaStatus(status) ? "restricted" : "standard";
}

export function permissionModeAvailable(
  mode: PermissionModeId,
  policy: ApprovalSurfacePolicy,
): boolean {
  return policy === "standard" || REALTOR_BETA_PERMISSION_MODES.has(mode);
}

export function approvalChoicesForPolicy(
  policy: ApprovalSurfacePolicy,
): readonly ApprovalChoice[] {
  return policy === "restricted"
    ? (["once", "deny"] as const)
    : (["once", "session", "always", "deny"] as const);
}

export function filterApprovalSettingsSchema<T>(
  schema: Record<string, T> | null,
  policy: ApprovalSurfacePolicy,
): Record<string, T> | null {
  if (!schema || policy === "standard") return schema;
  return Object.fromEntries(
    Object.entries(schema).filter(
      ([key]) => !key.startsWith("approvals.") && key !== "command_allowlist",
    ),
  );
}
