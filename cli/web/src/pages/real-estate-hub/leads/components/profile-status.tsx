import { useEffect, useId, useMemo, useRef, useState, useSyncExternalStore } from "react";

import { api } from "@/lib/api";
import type { CrmStage } from "@/lib/api-types";
import { ChevronDown } from "../../admin/icons";

const PROFILE_STATUS_OPTIONS = [
  "No status",
  "New Lead",
  "Follow Up",
  "Ghosting",
  "Dead",
  "Closed Buyer",
  "Closed Seller",
];

const PROFILE_STATUS_CLASS: Record<string, string> = {
  "New Lead": "new",
  "Follow Up": "buyer",
  Ghosting: "potential",
  Dead: "",
  "Closed Buyer": "active",
  "Closed Seller": "seller",
  "Closed Sell…": "active",
  "Active lead": "active",
  "New leads": "new",
  "Buyer track": "buyer",
  "Seller CMA": "seller",
  Potential: "potential",
};

/**
 * Mirror of the backend slugger (PUT /api/crm/stages and
 * contacts.is_valid_pipeline_status): lowercase, collapse non-alphanumeric
 * runs to "_", strip leading/trailing "_". This slug is what the backend
 * stores in contacts.pipeline_status for a custom stage.
 */
export function stageKeyForLabel(label: string): string {
  return label
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "");
}

// ── Custom pipeline stages (operator-defined, /api/crm/stages) ──────────────
// Module-level store: one GET per page load shared by every pill instance.
// leads-board primes it after PUT so new stages appear without a reload.
let customStages: CrmStage[] = [];
let customStagesPromise: Promise<CrmStage[]> | null = null;
const customStagesListeners = new Set<() => void>();

function subscribeCustomStages(listener: () => void): () => void {
  customStagesListeners.add(listener);
  return () => customStagesListeners.delete(listener);
}

export function setCustomStagesCache(stages: CrmStage[]): void {
  customStages = stages;
  customStagesPromise = Promise.resolve(stages);
  for (const listener of [...customStagesListeners]) listener();
}

export function loadCustomStagesOnce(): Promise<CrmStage[]> {
  if (!customStagesPromise) {
    customStagesPromise = api
      .getCrmStages()
      .then((result) => {
        setCustomStagesCache(Array.isArray(result.stages) ? result.stages : []);
        return customStages;
      })
      // Fail-silent: the pinned built-in options still work without config.
      .catch(() => customStages);
  }
  return customStagesPromise;
}

export function useCustomStages(): CrmStage[] {
  useEffect(() => {
    void loadCustomStagesOnce();
  }, []);
  return useSyncExternalStore(subscribeCustomStages, () => customStages);
}

export function StatusPill({
  status,
  onChange,
  className,
  disabled = false,
}: {
  status: string;
  onChange: (s: string) => void;
  className?: string;
  disabled?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement | null>(null);
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const optionRefs = useRef<Array<HTMLButtonElement | null>>([]);
  const menuId = useId();
  const customStagesList = useCustomStages();

  const options = useMemo(() => {
    const seen = new Set(PROFILE_STATUS_OPTIONS.map((option) => option.toLowerCase()));
    const merged = [...PROFILE_STATUS_OPTIONS];
    for (const stage of customStagesList) {
      const label = (stage.label || "").trim();
      if (!label || seen.has(label.toLowerCase())) continue;
      seen.add(label.toLowerCase());
      merged.push(label);
    }
    return merged;
  }, [customStagesList]);

  useEffect(() => {
    if (!open) return;
    const onDocClick = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: globalThis.KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onDocClick);
    window.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDocClick);
      window.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const raw = status || "No status";
  // A custom stage round-trips as its slug (label → slug → humanized label);
  // show the operator's exact configured label whenever the config knows it.
  const customMatch = customStagesList.find(
    (stage) =>
      stage.label.trim().toLowerCase() === raw.trim().toLowerCase()
      || stage.key === stageKeyForLabel(raw),
  );
  const display = customMatch?.label ?? raw;
  const cls = PROFILE_STATUS_CLASS[display] || "";
  const selectedIndex = Math.max(
    0,
    options.findIndex((option) => option.toLowerCase() === display.toLowerCase()),
  );

  useEffect(() => {
    if (!open) return;
    const frame = window.requestAnimationFrame(() => optionRefs.current[selectedIndex]?.focus());
    return () => window.cancelAnimationFrame(frame);
  }, [open, selectedIndex]);

  const handleListKeyDown = (event: React.KeyboardEvent<HTMLDivElement>) => {
    const current = optionRefs.current.indexOf(document.activeElement as HTMLButtonElement);
    if (event.key === "Escape") {
      event.preventDefault();
      setOpen(false);
      triggerRef.current?.focus();
      return;
    }
    let next = current;
    if (event.key === "ArrowDown") next = (Math.max(current, -1) + 1) % options.length;
    else if (event.key === "ArrowUp") next = (current <= 0 ? options.length : current) - 1;
    else if (event.key === "Home") next = 0;
    else if (event.key === "End") next = options.length - 1;
    else return;
    event.preventDefault();
    optionRefs.current[next]?.focus();
  };

  return (
    <div className="lb-status-wrap" ref={ref} onClick={(e) => e.stopPropagation()}>
      <button
        ref={triggerRef}
        type="button"
        className={"lb-profile-status " + cls + (className ? " " + className : "")}
        aria-expanded={open}
        aria-haspopup="listbox"
        aria-controls={open ? menuId : undefined}
        disabled={disabled}
        onKeyDown={(event) => {
          if (event.key === "ArrowDown" || event.key === "ArrowUp") {
            event.preventDefault();
            setOpen(true);
          }
        }}
        onClick={(e) => {
          e.stopPropagation();
          setOpen((o) => !o);
        }}
      >
        <span>{display}</span>
        <ChevronDown className="lb-profile-status-caret" />
      </button>
      {open && (
        <div id={menuId} className="lb-status-menu" role="listbox" onKeyDown={handleListKeyDown}>
          {options.map((s, index) => {
            const sCls = PROFILE_STATUS_CLASS[s] || "";
            const selected = s.toLowerCase() === display.toLowerCase();
            return (
              <button
                ref={(element) => { optionRefs.current[index] = element; }}
                key={s}
                type="button"
                role="option"
                aria-selected={selected}
                disabled={disabled}
                className="lb-status-menu-row"
                onClick={() => {
                  onChange(s);
                  setOpen(false);
                }}
              >
                <span className={"lb-status-menu-dot " + sCls} aria-hidden="true" />
                <span>{s}</span>
                <svg
                  className="lb-status-menu-check"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2.5"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  aria-hidden="true"
                >
                  <path d="M5 12l4 4 10-10" />
                </svg>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
