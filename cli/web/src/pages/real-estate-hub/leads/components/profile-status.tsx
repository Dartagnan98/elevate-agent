import { useEffect, useRef, useState } from "react";

import { ChevronDown } from "../../admin/icons";
import { PIPELINE_PILL_OPTIONS, resolvePipelineStage } from "../pipeline-stages";

// Skyleigh's 9 stages (+ "No status"). Legacy AI values (follow_up, ghosting,
// dead, closed_*) render mapped into her vocabulary via resolvePipelineStage.
const PROFILE_STATUS_OPTIONS = PIPELINE_PILL_OPTIONS;

export function StatusPill({
  status,
  onChange,
  className,
}: {
  status: string;
  onChange: (s: string) => void;
  className?: string;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement | null>(null);

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

  // Resolve the incoming value (her label, a legacy label, or a raw slug) into
  // her canonical stage so existing/AI rows render in her vocabulary.
  const resolved = resolvePipelineStage(status);
  const display = status ? resolved.label : "No status";
  const cls = status ? resolved.tone : "";

  return (
    <div className="lb-status-wrap" ref={ref} onClick={(e) => e.stopPropagation()}>
      <button
        type="button"
        className={"lb-profile-status " + cls + (className ? " " + className : "")}
        aria-expanded={open}
        onClick={(e) => {
          e.stopPropagation();
          setOpen((o) => !o);
        }}
      >
        <span>{display}</span>
        <ChevronDown className="lb-profile-status-caret" />
      </button>
      {open && (
        <div className="lb-status-menu" role="listbox">
          {PROFILE_STATUS_OPTIONS.map((s) => {
            const sCls = s === "No status" ? "" : resolvePipelineStage(s).tone;
            const selected = s === display;
            return (
              <button
                key={s}
                type="button"
                role="option"
                aria-selected={selected}
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
