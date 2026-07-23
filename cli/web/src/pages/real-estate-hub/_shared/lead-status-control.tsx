import { useEffect, useMemo, useState, useSyncExternalStore } from "react";
import { Loader2 } from "lucide-react";
import { Select, SelectOption } from "@/components/ui/select";
import { Badge } from "@/components/ui/badge";
import { api } from "@/lib/api";
import type { CrmStage, SourceInboxProfileStatus, SourceInboxResponse } from "@/lib/api-types";
import { cn } from "@/lib/utils";

const STATUS_OPTIONS: Array<{ value: SourceInboxProfileStatus | "none"; label: string }> = [
  { value: "none", label: "No status" },
  { value: "new_lead", label: "New Lead" },
  { value: "attempted_contact", label: "Attempted Contact" },
  { value: "prospect", label: "Prospect" },
  { value: "client", label: "Client" },
  { value: "pending_deal", label: "Pending Deal" },
  { value: "closed", label: "Closed" },
  { value: "referred", label: "Referred" },
  { value: "realtor_contact", label: "Realtor Contact" },
  { value: "trash", label: "Trash" },
  { value: "follow_up", label: "Follow Up" },
  { value: "ghosting", label: "Ghosting" },
  { value: "dead", label: "Dead" },
  { value: "closed_seller", label: "Closed Seller" },
  { value: "closed_buyer", label: "Closed Buyer" },
];

// ── Custom pipeline stages (operator-defined, /api/crm/stages) ──────────────
// Module-level cache: one GET per page load shared by every control instance,
// fail-silent to the pinned built-in options above.
let customStages: CrmStage[] = [];
let customStagesPromise: Promise<CrmStage[]> | null = null;
const customStagesListeners = new Set<() => void>();

function subscribeCustomStages(listener: () => void): () => void {
  customStagesListeners.add(listener);
  return () => customStagesListeners.delete(listener);
}

function loadCustomStagesOnce(): Promise<CrmStage[]> {
  if (!customStagesPromise) {
    customStagesPromise = api
      .getCrmStages()
      .then((result) => {
        customStages = Array.isArray(result.stages) ? result.stages : [];
        for (const listener of [...customStagesListeners]) listener();
        return customStages;
      })
      .catch(() => customStages);
  }
  return customStagesPromise;
}

function useCustomStages(): CrmStage[] {
  useEffect(() => {
    void loadCustomStagesOnce();
  }, []);
  return useSyncExternalStore(subscribeCustomStages, () => customStages);
}

const STATUS_BADGE: Record<
  SourceInboxProfileStatus,
  { label: string; variant: "default" | "secondary" | "success" | "warning" | "destructive" | "outline" }
> = {
  new_lead: { label: "new lead", variant: "default" },
  follow_up: { label: "follow up", variant: "warning" },
  ghosting: { label: "ghosting", variant: "secondary" },
  dead: { label: "dead", variant: "destructive" },
  closed_seller: { label: "closed seller", variant: "success" },
  closed_buyer: { label: "closed buyer", variant: "success" },
  attempted_contact: { label: "attempted contact", variant: "warning" },
  prospect: { label: "prospect", variant: "default" },
  client: { label: "client", variant: "success" },
  pending_deal: { label: "pending deal", variant: "warning" },
  closed: { label: "closed", variant: "success" },
  referred: { label: "referred", variant: "secondary" },
  realtor_contact: { label: "realtor contact", variant: "outline" },
  trash: { label: "trash", variant: "destructive" },
};

export function LeadStatusBadge({ status }: { status: SourceInboxProfileStatus | null }) {
  const stages = useCustomStages();
  if (!status) return null;
  const meta = STATUS_BADGE[status];
  if (meta) return <Badge variant={meta.variant}>{meta.label}</Badge>;
  // Operator-defined stage (migration 0037): the DB stores the slug; show the
  // configured label when the stage config knows it, else humanize the slug.
  const custom = stages.find((stage) => stage.key === status);
  const label = (custom?.label ?? String(status).replace(/[_-]+/g, " ")).toLowerCase();
  return <Badge variant="outline">{label}</Badge>;
}

export function LeadStatusControl({
  profileId,
  status,
  onChanged,
  className,
  selectClassName = "w-40",
  selectButtonClassName,
  disabled = false,
}: {
  profileId: string;
  status: SourceInboxProfileStatus | null;
  onChanged?: (nextInbox?: SourceInboxResponse) => void | Promise<void>;
  className?: string;
  selectClassName?: string;
  selectButtonClassName?: string;
  disabled?: boolean;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const customStagesList = useCustomStages();

  const statusOptions = useMemo(() => {
    const seenValues = new Set<string>(STATUS_OPTIONS.map((option) => option.value));
    const seenLabels = new Set<string>(STATUS_OPTIONS.map((option) => option.label.toLowerCase()));
    const merged: Array<{ value: string; label: string }> = [...STATUS_OPTIONS];
    for (const stage of customStagesList) {
      const label = (stage.label || "").trim();
      if (!stage.key || !label) continue;
      if (seenValues.has(stage.key) || seenLabels.has(label.toLowerCase())) continue;
      seenValues.add(stage.key);
      seenLabels.add(label.toLowerCase());
      merged.push({ value: stage.key, label });
    }
    return merged;
  }, [customStagesList]);

  const handleChange = async (next: string) => {
    if (busy || disabled) return;
    setBusy(true);
    setError(null);
    try {
      // Custom stage slugs are accepted by the backend (migration 0037); the
      // union type only names the built-ins, so the cast carries them through.
      const value = next === "none" ? null : (next as SourceInboxProfileStatus);
      const nextInbox = await api.updateSourceInboxProfile(profileId, value);
      await onChanged?.(nextInbox);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className={cn("relative", className)}>
      <div className="flex items-center gap-1.5">
        {busy && <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin text-muted-foreground" aria-hidden />}
        <Select
          value={status ?? "none"}
          onValueChange={handleChange}
          disabled={busy || disabled}
          className={selectClassName}
          buttonClassName={selectButtonClassName}
        >
          {statusOptions.map((option) => (
            <SelectOption key={option.value} value={option.value}>
              {option.label}
            </SelectOption>
          ))}
        </Select>
      </div>
      {error && <p className="mt-1 text-[0.7rem] leading-4 text-destructive">{error}</p>}
    </div>
  );
}
