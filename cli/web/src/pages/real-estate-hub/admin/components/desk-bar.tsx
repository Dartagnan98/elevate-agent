import type { ReactNode } from "react";
import { ChevronDown } from "../icons";
import "./desk-sections.css";

/**
 * Shared collapsible desk bar used by Critical dates + Approvals so the two
 * read as a matched pair. tone drives the accent: "alert" (red, time pressure),
 * "neutral" (quiet), "info" (blue count pill, sign-off pressure).
 */
export function DeskBar({
  tone,
  leftIcon,
  label,
  summary,
  pill,
  expanded,
  onToggle,
  children,
}: {
  tone: "alert" | "neutral" | "info";
  leftIcon: ReactNode;
  label: string;
  summary?: ReactNode;
  pill?: ReactNode;
  expanded: boolean;
  onToggle: () => void;
  children?: ReactNode;
}) {
  return (
    <section className={`dsk-bar dsk-${tone}${expanded ? " open" : ""}`}>
      <button
        type="button"
        className="dsk-bar-head"
        aria-expanded={expanded}
        onClick={onToggle}
      >
        <span className="dsk-bar-left">
          {tone === "alert" && <span className="dsk-bar-dot" aria-hidden />}
          <span className="dsk-bar-ic" aria-hidden>{leftIcon}</span>
          <span className="dsk-bar-label">{label}</span>
          {summary != null && <span className="dsk-bar-summary">{summary}</span>}
        </span>
        <span className="dsk-bar-right">
          {pill}
          <span className="dsk-bar-toggle">
            {expanded ? "Collapse" : "Expand"}
            <span className={"dsk-chev" + (expanded ? " up" : "")}><ChevronDown /></span>
          </span>
        </span>
      </button>
      {expanded && <div className="dsk-bar-body">{children}</div>}
    </section>
  );
}
