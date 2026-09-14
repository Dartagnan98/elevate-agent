import { useEffect, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import "./kit-workspace.css";

export default function WizardSurface({ title, subtitle, label, onClose, beforeClose, children, closeLabel = "← Back to the deal", className = "" }: {
  title: string; subtitle?: string; label: string; onClose: () => void;
  beforeClose?: () => Promise<void>; children: ReactNode; closeLabel?: string; className?: string;
}) {
  const root = useRef<HTMLDivElement>(null);
  const [closing, setClosing] = useState(false);
  const [error, setError] = useState("");
  const closeRef = useRef<() => void>(() => {});
  closeRef.current = () => {
    if (closing) return;
    (document.activeElement as HTMLElement | null)?.blur();
    setClosing(true); setError("");
    Promise.resolve().then(() => beforeClose?.()).then(onClose).catch(() => {
      setError("Some changes haven't saved. Retry saving below, then return to the deal.");
    }).finally(() => setClosing(false));
  };
  useEffect(() => {
    const opener = document.activeElement as HTMLElement | null;
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    root.current?.focus();
    const key = (event: KeyboardEvent) => {
      // Leave nested document dialogs to handle their own keyboard interaction.
      const dialogs = [...document.querySelectorAll('[role="dialog"]')];
      if (dialogs.at(-1) !== root.current) return;
      if (event.key === "Escape") {
        event.preventDefault(); event.stopImmediatePropagation(); closeRef.current();
      }
      if (event.key === "Tab") {
        const items = [...(root.current?.querySelectorAll<HTMLElement>('button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled), summary, a[href], [tabindex="0"]') || [])].filter(el => el.getClientRects().length);
        const first = items[0], last = items.at(-1);
        if (!first) { event.preventDefault(); return; }
        if (event.shiftKey && (document.activeElement === first || document.activeElement === root.current)) { event.preventDefault(); last?.focus(); }
        else if (!event.shiftKey && (document.activeElement === last || document.activeElement === root.current)) { event.preventDefault(); first.focus(); }
      }
    };
    document.addEventListener("keydown", key, true);
    return () => { document.removeEventListener("keydown", key, true); document.body.style.overflow = overflow; opener?.focus(); };
  }, []);
  return createPortal(<div ref={root} tabIndex={-1} role="dialog" aria-modal="true" aria-label={label} className={`kit-workspace ${className}`} onClick={e => e.stopPropagation()}>
    <header className="kit-workspace-header">
      <button type="button" className="kit-secondary" disabled={closing} onClick={() => closeRef.current()}>{closing ? "Saving…" : closeLabel}</button>
      <div className="kit-workspace-title"><strong>{title}</strong><span>{subtitle || label}</span></div>
    </header>
    {error && <div role="alert" className="kit-workspace-error">{error}</div>}
    <div className="kit-workspace-scroll"><div className="kit-workspace-content">{children}</div></div>
  </div>, document.body);
}
