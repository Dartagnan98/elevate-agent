// Single source of truth for Skyleigh's operator-facing lead pipeline.
//
// Background: the AI classifier + sync pipeline write a fixed set of 6 legacy
// pipeline_status slugs (new_lead, follow_up, ghosting, dead, closed_seller,
// closed_buyer). Skyleigh's operator pipeline is a 9-stage vocabulary. We keep
// both alive: the AI keeps writing its 6 slugs, and everywhere the operator
// SEES a stage we display it in her vocabulary via the legacy -> stage mapping
// below. The operator dropdowns write her 9 slugs directly.
//
// Import this from the contact card, the status pill, the leads table, and the
// reporting chart so there is exactly one place that defines the stages and
// the legacy mapping.

export interface PipelineStage {
  /** Canonical slug written to contacts.pipeline_status. */
  slug: string;
  /** Operator-facing label. */
  label: string;
  /** Tone class reused by the status pill / stage dot (see leads.css). */
  tone: "new" | "buyer" | "seller" | "active" | "potential" | "";
}

// Skyleigh's canonical 9 stages, in pipeline order. "New Lead" reuses the
// existing new_lead slug so the AI's most common value already lands here.
export const PIPELINE_STAGES: PipelineStage[] = [
  { slug: "new_lead", label: "New Lead", tone: "new" },
  { slug: "attempted", label: "Attempted", tone: "buyer" },
  { slug: "prospect", label: "Prospect", tone: "potential" },
  { slug: "client", label: "Client", tone: "active" },
  { slug: "pending_deal", label: "Pending Deal", tone: "seller" },
  { slug: "closed", label: "Closed", tone: "active" },
  { slug: "referred", label: "Referred", tone: "potential" },
  { slug: "realtor_contact", label: "Realtor Contact", tone: "buyer" },
  { slug: "trash", label: "Trash", tone: "" },
];

// Sentinel returned for an empty / unset status.
export const NO_STAGE: PipelineStage = { slug: "", label: "No status", tone: "" };

// Legacy AI/existing pipeline_status slug -> Skyleigh's stage slug.
export const LEGACY_STATUS_TO_STAGE: Record<string, string> = {
  new_lead: "new_lead",
  follow_up: "attempted",
  ghosting: "attempted",
  dead: "trash",
  closed_seller: "closed",
  closed_buyer: "closed",
};

function norm(value: string): string {
  return value.trim().toLowerCase();
}

// Lookup index: her slugs, her labels, legacy slugs, and the legacy display
// labels that older code (statusLabel) produced, all resolving to a stage.
const STAGE_BY_KEY = new Map<string, PipelineStage>();
const STAGE_BY_SLUG = new Map<string, PipelineStage>();
for (const stage of PIPELINE_STAGES) {
  STAGE_BY_SLUG.set(stage.slug, stage);
  STAGE_BY_KEY.set(stage.slug, stage);
  STAGE_BY_KEY.set(norm(stage.label), stage);
}
// Legacy slugs + their old display labels ("Follow Up", "Closed Seller", ...).
const LEGACY_DISPLAY_LABELS: Record<string, string> = {
  new_lead: "new lead",
  follow_up: "follow up",
  ghosting: "ghosting",
  dead: "dead",
  closed_seller: "closed seller",
  closed_buyer: "closed buyer",
};
for (const [legacySlug, stageSlug] of Object.entries(LEGACY_STATUS_TO_STAGE)) {
  const stage = STAGE_BY_SLUG.get(stageSlug);
  if (!stage) continue;
  STAGE_BY_KEY.set(legacySlug, stage);
  const legacyLabel = LEGACY_DISPLAY_LABELS[legacySlug];
  if (legacyLabel) STAGE_BY_KEY.set(legacyLabel, stage);
}

function titleize(value: string): string {
  return value
    .replace(/[_-]+/g, " ")
    .replace(/\s+/g, " ")
    .trim()
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

/**
 * Resolve any pipeline value (her slug, her label, a legacy slug, a legacy
 * display label, or an arbitrary CRM stage string) to a canonical stage.
 * Unknown values pass through titleized so real CRM/admin stages still render.
 */
export function resolvePipelineStage(value: string | null | undefined): PipelineStage {
  const raw = (value ?? "").trim();
  if (!raw) return NO_STAGE;
  const hit = STAGE_BY_KEY.get(norm(raw));
  if (hit) return hit;
  return { slug: norm(raw).replace(/\s+/g, "_"), label: titleize(raw), tone: "" };
}

/** Convenience: the operator-facing label for any pipeline value. */
export function pipelineStageLabel(value: string | null | undefined): string {
  return resolvePipelineStage(value).label;
}

/**
 * The value to feed a <select> whose options are her 9 slugs. When the current
 * status maps into her pipeline we return that stage slug so the dropdown shows
 * the right label without silently rewriting the stored value. Anything outside
 * her 9 (arbitrary CRM stage) returns "" so the select doesn't show a phantom.
 */
export function pipelineSelectValue(value: string | null | undefined): string {
  const stage = resolvePipelineStage(value);
  return STAGE_BY_SLUG.has(stage.slug) ? stage.slug : "";
}

/** Map an operator-picked label back to its slug (for the status-pill write). */
export function pipelineSlugForLabel(label: string): string | null | undefined {
  const key = norm(label);
  if (!key || key === "no status" || key === "none") return null;
  const stage = STAGE_BY_KEY.get(key);
  return stage ? stage.slug : undefined;
}

// Options for the contact-card dropdown (leading "-- None --").
export const PIPELINE_SELECT_OPTIONS: Array<{ value: string; label: string }> = [
  { value: "", label: "-- None --" },
  ...PIPELINE_STAGES.map((s) => ({ value: s.slug, label: s.label })),
];

// Labels for the status pill (leading "No status").
export const PIPELINE_PILL_OPTIONS: string[] = [NO_STAGE.label, ...PIPELINE_STAGES.map((s) => s.label)];
