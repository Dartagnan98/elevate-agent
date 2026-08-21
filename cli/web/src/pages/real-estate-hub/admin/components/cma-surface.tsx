// The CMA as a full surface — mockup screens 1-11 all sit on one.
//
// The wizard used to be a collapsible panel inside the deal card, competing for
// the same scroll with Listing Kit, approvals and documents. The mockup gives a
// market evaluation its own screen with one job, which is most of why the built
// thing "didn't look like the mockups" even where the content matched.
//
// Rendered as a layer ABOVE the deal card rather than a route, so closing it
// reveals the card still sitting underneath, which is where Skyleigh asked to
// land. Nothing to navigate back to and no state to restore.
import { useEffect, useState } from "react";
import { useIsMobile } from "../../../../hooks/useIsMobile";
import { createPortal } from "react-dom";
import CmaWizard from "./cma-wizard";

const NAVY = "#182848", INK3 = "#6B7488", LINE = "#DDE2EA";

export default function CmaSurface({
  dealId,
  address,
  area,
  sellerName,
  onClose,
}: {
  dealId: string;
  address?: string | null;
  area?: string | null;
  sellerName?: string | null;
  onClose: () => void;
}) {
  const isMobile = useIsMobile();
  // Mirrors edits made on the Property step so the top bar never disagrees
  // with the field she just changed.
  const [shownAddr, setShownAddr] = useState(address || "");
  useEffect(() => { setShownAddr(address || ""); }, [address]);
  // Esc closes. The comp review also binds Escape (to shut its photo lightbox)
  // and it stops there because it returns early, so the two do not fight: the
  // lightbox swallows the first Esc, this takes the second.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  // The deal card underneath scrolls independently; locking the body while the
  // surface is up stops the page behind it drifting under the fixed layer.
  useEffect(() => {
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => { document.body.style.overflow = prev; };
  }, []);

  return createPortal(
    <div
      role="dialog"
      aria-modal="true"
      aria-label={`Market evaluation${shownAddr ? ` for ${shownAddr}` : ""}`}
      style={{
        // MUST clear the deal card, which is `.ab-modal-backdrop` at z-index 100
        // (admin.css). At 60 the surface opened correctly and rendered BEHIND the
        // card, so the button looked dead. Kept under Ozzie's chat panel (1200)
        // so she can still open chat over an evaluation.
        position: "fixed", inset: 0, zIndex: 1100,
        background: "#F5F7FA", display: "flex", flexDirection: "column",
      }}
    >
      {/* Top bar: address left, seller chip right, exactly the mockup's shape. */}
      <header style={{
        flex: "0 0 auto", display: "flex", alignItems: "center", gap: isMobile ? 8 : 12,
        padding: isMobile ? "9px 11px" : "11px 16px", background: "#fff",
        borderBottom: `1px solid ${LINE}`, flexWrap: "wrap",
      }}>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close the market evaluation"
          style={{
            display: "flex", alignItems: "center", gap: 6, background: "none",
            border: `1px solid ${LINE}`, borderRadius: 8, padding: "6px 11px",
            fontSize: 12.5, fontWeight: 700, color: INK3, cursor: "pointer",
          }}
        >
          {isMobile ? "← Back" : "← Back to the deal"}
        </button>
        <div style={{ minWidth: 0, flex: 1 }}>
          <div style={{ fontSize: 14.5, fontWeight: 700, color: NAVY, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            {shownAddr || "Market evaluation"}
          </div>
          {area && <div style={{ fontSize: 11.5, color: INK3 }}>{area}</div>}
        </div>
        <span style={{
          flex: "0 0 auto", display: isMobile ? "none" : "inline-block",
          fontSize: 10.5, fontWeight: 700, letterSpacing: ".06em",
          textTransform: "uppercase", color: "#fff", background: NAVY,
          borderRadius: 6, padding: "4px 9px", whiteSpace: "nowrap",
        }}>
          {sellerName ? `${sellerName} · CMA` : "Elevation · CMA"}
        </span>
      </header>

      <div style={{ flex: 1, minHeight: 0, overflowY: "auto" }}>
        <div style={{ maxWidth: 1080, margin: "0 auto", padding: isMobile ? "10px 10px 36px" : "14px 16px 40px" }}>
          <CmaWizard dealId={dealId} bare address={shownAddr} onAddressChange={setShownAddr} />
        </div>
      </div>
    </div>,
    document.body,
  );
}
