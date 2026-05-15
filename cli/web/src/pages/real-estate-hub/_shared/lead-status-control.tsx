import { useState } from "react";
import { Loader2 } from "lucide-react";
import { Select, SelectOption } from "@/components/ui/select";
import { Badge } from "@/components/ui/badge";
import { api } from "@/lib/api";
import type { SourceInboxProfileStatus } from "@/lib/api";
import { cn } from "@/lib/utils";

const STATUS_OPTIONS: Array<{ value: SourceInboxProfileStatus | "none"; label: string }> = [
  { value: "none", label: "No status" },
  { value: "new_lead", label: "New Lead" },
  { value: "follow_up", label: "Follow Up" },
  { value: "ghosting", label: "Ghosting" },
  { value: "dead", label: "Dead" },
  { value: "closed_seller", label: "Closed Seller" },
  { value: "closed_buyer", label: "Closed Buyer" },
];

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
};

export function LeadStatusBadge({ status }: { status: SourceInboxProfileStatus | null }) {
  if (!status) return null;
  const meta = STATUS_BADGE[status];
  if (!meta) return null;
  return <Badge variant={meta.variant}>{meta.label}</Badge>;
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
  onChanged?: () => void | Promise<void>;
  className?: string;
  selectClassName?: string;
  selectButtonClassName?: string;
  disabled?: boolean;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleChange = async (next: string) => {
    if (busy || disabled) return;
    setBusy(true);
    setError(null);
    try {
      const value = next === "none" ? null : (next as SourceInboxProfileStatus);
      await api.updateSourceInboxProfile(profileId, value);
      await onChanged?.();
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
          {STATUS_OPTIONS.map((option) => (
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
