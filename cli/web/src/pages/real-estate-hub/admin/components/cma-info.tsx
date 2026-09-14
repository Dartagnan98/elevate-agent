// The (i) affordance the approved mockup specifies: "explanations live behind
// (i) popovers rather than in body copy". The impeccable craft floor says the
// same. I had been writing a paragraph of helper text under every control, which
// is onboarding copy in a tool Skyleigh uses daily -- noise by the second use.
//
// A control gets a label. The reasoning goes in here.
import { useEffect, useRef, useState } from "react";

const NAVY = "#182848", LINE = "#DDE2EA";

export default function CmaInfo({ children, label }: { children: React.ReactNode; label?: string }) {
  const [open, setOpen] = useState(false);
  const wrap = useRef<HTMLSpanElement | null>(null);

  useEffect(() => {
    if (!open) return;
    const away = (e: MouseEvent) => {
      if (wrap.current && !wrap.current.contains(e.target as Node)) setOpen(false);
    };
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", away);
    window.addEventListener("keydown", esc);
    return () => { document.removeEventListener("mousedown", away); window.removeEventListener("keydown", esc); };
  }, [open]);

  return (
    <span ref={wrap} style={{ position: "relative", display: "inline-flex", verticalAlign: "middle" }}>
      <button
        type="button"
        onClick={(e) => { e.stopPropagation(); setOpen((v) => !v); }}
        aria-label={label || "What this means"}
        aria-expanded={open}
        style={{
          // A real 44pt hit area. The dot is an inner span so the ring draws at
          // 18px while the button that catches her thumb is 44px, and an equal
          // negative margin keeps the layout footprint at 18px so no heading
          // grows. This block used to say "44pt hit area via padding" while
          // setting padding: 0 -- the comment was the only defence and it was
          // not true, so on a phone this was an 18px target.
          width: 44, height: 44, margin: -13, padding: 0,
          border: "none", background: "transparent", cursor: "pointer",
          display: "inline-flex", alignItems: "center", justifyContent: "center",
          WebkitTapHighlightColor: "transparent",
        }}
      >
        <span
          aria-hidden="true"
          style={{
            width: 18, height: 18, borderRadius: "50%",
            border: `1px solid ${open ? NAVY : "#B9C2D2"}`,
            background: open ? NAVY : "transparent",
            color: open ? "#fff" : "#6B7488",
            fontSize: 11, fontWeight: 700, lineHeight: 1,
            display: "inline-flex", alignItems: "center", justifyContent: "center",
          }}
        >i</span>
      </button>
      {open && (
        <span
          role="note"
          style={{
            position: "absolute", top: 24, left: 0, zIndex: 30,
            width: 260, maxWidth: "78vw", padding: "10px 12px",
            background: "#fff", border: `1px solid ${LINE}`, borderRadius: 9,
            boxShadow: "0 8px 24px rgba(24,40,72,.16)",
            fontSize: 13, lineHeight: 1.5, fontWeight: 400, color: "#4A5468",
            textTransform: "none", letterSpacing: 0, textAlign: "left",
          }}
        >
          {children}
        </span>
      )}
    </span>
  );
}
