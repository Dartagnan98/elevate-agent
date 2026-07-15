import type {
  AdminProvinceGuideCoverage,
  AdminSetupReadinessItem,
  AdminSetupSnapshot,
} from "@/lib/api";
import type { AdminSetupDraft } from "@/pages/real-estate-hub/admin-setup";

export type AdminOnboardingDraftField = {
  key: keyof AdminSetupDraft;
  label: string;
  optional?: boolean;
};

export function missingAdminOnboardingFields<T extends AdminOnboardingDraftField>(
  fields: readonly T[],
  draft: AdminSetupDraft,
): T[] {
  return fields.filter((field) => {
    if (field.optional) return false;
    const raw = draft[field.key];
    return typeof raw !== "string" || raw.trim().length === 0;
  });
}

function fallbackReadinessItem(
  setup: AdminSetupSnapshot,
  key: string,
): AdminSetupReadinessItem {
  const item = setup.items.find((candidate) => candidate.key === key);
  return {
    key,
    label: item?.label || key.replaceAll("_", " "),
    category: item?.category,
    status: item?.status ?? "missing",
    provider: item?.provider,
    ready: false,
    state: "missing_value",
    detail: item?.description || "This required setup item is not ready yet.",
    action: "Review this setup item, save it, then run Verify connections.",
    hasValue: Boolean(item?.value),
    updatedAt: item?.updatedAt,
  };
}

export function unresolvedAdminSetupReadiness(
  setup: AdminSetupSnapshot,
): AdminSetupReadinessItem[] {
  const readiness = Array.isArray(setup.readiness) ? setup.readiness : [];
  const unresolved = readiness.filter((item) => item.ready !== true);
  const unresolvedKeys = new Set(unresolved.map((item) => item.key));

  for (const key of setup.missingRequiredKeys ?? []) {
    if (!unresolvedKeys.has(key)) {
      unresolved.push(fallbackReadinessItem(setup, key));
      unresolvedKeys.add(key);
    }
  }

  if (!setup.complete && unresolved.length === 0) {
    unresolved.push({
      key: "setup_verification",
      label: "Setup verification",
      status: "missing",
      ready: false,
      state: "needs_verification",
      detail: "Admin setup has not been verified as complete.",
      action: "Return to the setup form and run Verify connections.",
      hasValue: false,
    });
  }

  return unresolved;
}

export function canClaimAdminSetupReady(setup: AdminSetupSnapshot): boolean {
  const readiness = Array.isArray(setup.readiness) ? setup.readiness : [];
  const requiredCount = Number(setup.requiredCount);
  const completedRequiredCount = Number(setup.completedRequiredCount);
  return (
    setup.complete === true &&
    setup.canStartAdmin === true &&
    setup.launchRequired === false &&
    Number.isFinite(requiredCount) &&
    requiredCount > 0 &&
    readiness.length === requiredCount &&
    completedRequiredCount === requiredCount &&
    (setup.missingRequiredKeys ?? []).length === 0 &&
    unresolvedAdminSetupReadiness(setup).length === 0
  );
}

export type AdminFormsProviderCardModel = {
  exactBeta: boolean;
  visible: boolean;
  available: boolean;
  provider: string;
  title: "Forms provider";
  statusLabel: "provider needed" | "document drafting paused" | "verified";
  message: string;
  buttonLabel: "Connect & verify";
  buttonDisabled: boolean;
  disabledReason: string;
};

/**
 * Project the exact-Beta forms capability into truthful, realtor-facing UI.
 * Stable snapshots omit the capability and therefore keep their existing UI.
 */
export function adminFormsProviderCardModel(
  setup: AdminSetupSnapshot | null,
): AdminFormsProviderCardModel {
  const capability = setup?.capabilities?.formsProvider;
  const item = setup?.items.find((candidate) => candidate.key === "forms_provider");
  const provider = String(item?.provider || setup?.profile.formsProvider || "").trim();
  const exactBeta = capability !== undefined;
  const available = capability?.available === true;
  const paused = exactBeta && !available;
  const fallbackMessage = provider
    ? "Admin is ready, but live MLC and CPS drafting stays paused until forms-provider access is verified. Use the named provider manually in the meantime."
    : "Choose the forms provider your brokerage uses. Admin can start after setup, but MLC and CPS drafting stays manual until live access is verified.";

  return {
    exactBeta,
    visible: paused,
    available,
    provider,
    title: "Forms provider",
    statusLabel: available
      ? "verified"
      : provider
        ? "document drafting paused"
        : "provider needed",
    message: String(capability?.message || "").trim() || fallbackMessage,
    buttonLabel: "Connect & verify",
    buttonDisabled: paused,
    disabledReason: paused
      ? "Automatic live forms verification is not available in this Beta build. Elevation will hold MLC and CPS drafting for manual completion instead of claiming a connection."
      : "",
  };
}

export type AdminSetupShellState = "loading" | "error" | "onboarding" | "ready";

export function resolveAdminSetupShellState(input: {
  loading: boolean;
  error: string | null;
  setup: AdminSetupSnapshot | null;
  forceOnboarding: boolean;
}): AdminSetupShellState {
  if (input.loading) return "loading";
  if (input.error || !input.setup) return "error";
  if (input.forceOnboarding || !canClaimAdminSetupReady(input.setup)) {
    return "onboarding";
  }
  return "ready";
}

export type ProvinceGuideAvailability =
  | "idle"
  | "loading"
  | "error"
  | "available"
  | "unavailable";

export function provinceGuideAvailability(input: {
  province: string;
  coverage: AdminProvinceGuideCoverage[];
  loading: boolean;
  error: string | null;
}): ProvinceGuideAvailability {
  const province = input.province.trim().toUpperCase();
  if (!province) return "idle";
  if (input.error) return "error";
  if (input.loading) return "loading";
  return input.coverage.some((item) => item.province === province)
    ? "available"
    : "unavailable";
}

export type AdminOnboardingSeedResult = {
  missing: boolean;
  error: string | null;
};

export type AdminOnboardingSeedOutcome =
  | { kind: "running" }
  | { kind: "complete" }
  | { kind: "missing" }
  | { kind: "error"; message: string };

export const ADMIN_ONBOARDING_SEED_TIMEOUT_MS = 60_000;

export async function runAdminOnboardingSeedWithTimeout(
  runSeed: () => Promise<AdminOnboardingSeedResult>,
  timeoutMs = ADMIN_ONBOARDING_SEED_TIMEOUT_MS,
): Promise<AdminOnboardingSeedOutcome> {
  let timeoutId: ReturnType<typeof setTimeout> | undefined;
  const timeout = new Promise<AdminOnboardingSeedOutcome>((resolve) => {
    timeoutId = setTimeout(() => {
      resolve({
        kind: "error",
        message:
          "The setup check took longer than one minute. Your answers are still saved. Retry the check or review the setup form.",
      });
    }, timeoutMs);
  });
  const request = Promise.resolve()
    .then(runSeed)
    .then<AdminOnboardingSeedOutcome>((result) => {
      if (result.error) return { kind: "error", message: result.error };
      return result.missing ? { kind: "missing" } : { kind: "complete" };
    })
    .catch<AdminOnboardingSeedOutcome>((error: unknown) => ({
      kind: "error",
      message: error instanceof Error ? error.message : String(error),
    }));

  try {
    return await Promise.race([request, timeout]);
  } finally {
    if (timeoutId !== undefined) clearTimeout(timeoutId);
  }
}

export type AdminOnboardingSeedingStepState = "pending" | "active" | "done";

export function adminOnboardingSeedingStepState(
  outcome: AdminOnboardingSeedOutcome,
  index: number,
): AdminOnboardingSeedingStepState {
  if (outcome.kind === "complete") return "done";
  if (outcome.kind === "running" && index === 0) return "active";
  return "pending";
}

export async function saveBeforeAdminOnboardingAdvance(
  save: () => Promise<boolean>,
  advance: () => void,
): Promise<boolean> {
  if (!(await save())) return false;
  advance();
  return true;
}

export const ADMIN_ONBOARDING_EXIT_FALLBACK_MS = 450;

export function adminOnboardingExitDelay(prefersReducedMotion: boolean): number {
  return prefersReducedMotion ? 0 : ADMIN_ONBOARDING_EXIT_FALLBACK_MS;
}
