import { useEffect, useId, useRef, useState } from "react";

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

  const display = status || "No status";
  const cls = PROFILE_STATUS_CLASS[display] || "";
  const selectedIndex = Math.max(0, PROFILE_STATUS_OPTIONS.indexOf(display));

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
    if (event.key === "ArrowDown") next = (Math.max(current, -1) + 1) % PROFILE_STATUS_OPTIONS.length;
    else if (event.key === "ArrowUp") next = (current <= 0 ? PROFILE_STATUS_OPTIONS.length : current) - 1;
    else if (event.key === "Home") next = 0;
    else if (event.key === "End") next = PROFILE_STATUS_OPTIONS.length - 1;
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
          {PROFILE_STATUS_OPTIONS.map((s, index) => {
            const sCls = PROFILE_STATUS_CLASS[s] || "";
            const selected = s === display;
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
