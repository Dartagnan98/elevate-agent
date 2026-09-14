// Where the home sits — the Pricing step's answer, built from POSITIONS.
//
// Skyleigh's method, in her words: "we don't do calculations like that. We just
// move the property to be better or worse than other properties could've sold."
// So this screen has no arithmetic in it. The cheapest comp that beats her
// seller's home is the ceiling, the dearest one it beats is the floor, and she
// types the launch price between them. Nothing invents a number for her.
//
// What this replaced: a band reading "RECOMMENDED $475,500" derived from price
// per square foot, comp averaging, score interpolation and a seasonal
// adjustment — none of which she does, and which landed on one comp's exact sale
// price because that comp had been double-counted.
//
// Each row says whether the position came from HER note or from the tool's own
// read, because a machine's guess must never be mistaken for her judgement.
import { useCallback, useEffect, useState } from "react";
import { api } from "../../../../lib/api";
import { useIsMobile } from "../../../../hooks/useIsMobile";
import CmaInfo from "./cma-info";

const NAVY = "#182848", MUTED = "#6B7488", LINE = "#e3e7ef",
      TERRA = "#C46340", BLUE = "#5E8AD0", INK2 = "#4A5468";

type Row = import("../../../../lib/api").CmaBracketRow;
type ActiveRow = import("../../../../lib/api").CmaActiveRow;

const money = (n?: number | null) =>
  n == null ? "" : "$" + Math.round(n).toLocaleString("en-CA");

export default function CmaBracket({ dealId, onRepriced }: {
  dealId: string; onRepriced?: () => void;
}) {
  const isMobile = useIsMobile();
  const [b, setB] = useState<Awaited<ReturnType<typeof api.getCmaBracket>> | null>(null);
  const [price, setPrice] = useState("");
  const [why, setWhy] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [open, setOpen] = useState<string | null>(null);
  // Progress label while the reprice rebuild polls. MUST stay above the
  // `if (!b?.available) return null` early return: a hook declared after it
  // changes the hook count when `available` flips false -> true, which is
  // React error #310 and unmounts the entire app (white screen on the
  // Pricing step as soon as the bracket loads).
  const [stage, setStage] = useState("");

  const load = useCallback(async () => {
    try {
      const r = await api.getCmaBracket(dealId);
      setB(r);
      if (r?.chosen && !price) setPrice(String(r.chosen).replace(/[^0-9]/g, ""));
    } catch { /* the step still renders, just without the ladder */ }
  }, [dealId]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => { void load(); }, [load]);

  if (!b?.available) return null;

  const ceiling = b.ceiling ?? null, floor = b.floor ?? null;
  const n = Number(String(price).replace(/[^0-9]/g, "")) || 0;
  const tooHigh = !!(ceiling && n && n >= ceiling);
  const tooLow = !!(floor && n && n <= floor);

  // Setting the price re-derives the sandwich, the comp write-ups and the PDF.
  // That runs DETACHED with its output discarded and takes a few minutes, so the
  // old "fire it and reload after 4.5 seconds" left the screen looking untouched
  // and the button looking broken -- the third control in this wizard to have
  // exactly that shape. Poll the phases until the report has actually rebuilt.
  // (The `stage` progress label is declared with the other hooks above the
  // early return.)
  const save = async () => {
    if (!n || busy) return;
    setBusy(true); setErr(""); setStage("Setting your price…");
    try {
      await api.repriceCma(dealId, String(n), why.trim());
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Could not set that price.");
      setBusy(false); setStage("");
      return;
    }
    // ~4 minutes of headroom; the chain is normally well under that.
    for (let i = 0; i < 60; i++) {
      await new Promise((r) => setTimeout(r, 4000));
      try {
        const ph = await api.getCmaPhases(dealId);
        const by = Object.fromEntries((ph.phases || []).map((x) => [x.id, x.status]));
        if (by.render === "done" && by.normalize === "done" && by.finish === "done") {
          setStage(""); setBusy(false);
          await load(); onRepriced?.();
          return;
        }
        const running = (ph.phases || []).find((x) => x.status === "running");
        setStage(running ? `Rebuilding: ${running.label.toLowerCase()}…` : "Rebuilding the report…");
        if ((ph.phases || []).some((x) => x.status === "failed")) {
          setErr("The rebuild stopped partway. Your price is saved; try Generate on the Report step.");
          break;
        }
      } catch { /* keep polling; a blip is not a failure */ }
    }
    setBusy(false); setStage("");
    await load(); onRepriced?.();
  };

  const compRow = (r: Row, tone: "above" | "level" | "below") => {
    const isOpen = open === r.mls;
    const tint = tone === "above" ? "#F7F9FC" : tone === "below" ? "#F7F9FC" : "#FFFDFB";
    return (
      <div key={r.mls} style={{ borderTop: `1px solid ${LINE}`, background: tint }}>
        <button type="button" onClick={() => setOpen(isOpen ? null : r.mls)}
          aria-expanded={isOpen}
          style={{ width: "100%", textAlign: "left", font: "inherit", background: "transparent",
                   border: "none", minHeight: 44, padding: "9px 13px", cursor: r.note ? "pointer" : "default",
                   display: "flex", alignItems: "baseline", gap: 10 }}>
          <span style={{ flex: 1, minWidth: 0, fontSize: 13, color: NAVY, fontWeight: 600 }}>
            {r.address}
            <span style={{ display: "block", fontSize: 11, fontWeight: 400, color: MUTED, marginTop: 2 }}>
              {r.label || "not positioned yet"}
              {r.source === "tool" && <span style={{ color: TERRA }}> · the tool's read</span>}
              {r.source === "yours" && <span style={{ color: BLUE }}> · yours</span>}
            </span>
          </span>
          <span style={{ fontSize: 13.5, fontWeight: 800, color: NAVY, fontVariantNumeric: "tabular-nums" }}>
            {money(r.price)}
          </span>
        </button>
        {isOpen && r.note && (
          <p style={{ margin: 0, padding: "0 13px 11px", fontSize: 12.5, lineHeight: 1.55, color: INK2 }}>{r.note}</p>
        )}
      </div>
    );
  };

  return (
    <div style={{ marginBottom: 14 }}>
      <h3 style={{ margin: "0 0 3px", fontSize: isMobile ? 17 : 16, fontWeight: 700, color: NAVY, display: "flex", alignItems: "center", gap: 7 }}>
        Where your home sits
        <CmaInfo label="How this price is set">
          There is no calculation here. The cheapest comparable that beats this home sets the
          ceiling, the dearest one it beats sets the floor, and you choose the launch price
          between them. Change a comp's position on the Comparables step and this moves.
        </CmaInfo>
      </h3>
      <p style={{ margin: "0 0 11px", fontSize: 13.5, color: MUTED, lineHeight: 1.5, maxWidth: "68ch" }}>
        {ceiling && floor
          ? <>Your comps put this home between <b style={{ color: NAVY }}>{money(floor)}</b> and <b style={{ color: NAVY }}>{money(ceiling)}</b>.</>
          : ceiling ? <>Everything you kept beats this home. {money(ceiling)} is the ceiling.</>
          : floor ? <>This home beats everything you kept. {money(floor)} is the floor.</>
          : <>Position a few comps on the Comparables step and the bracket appears here.</>}
      </p>

      <div style={{ border: `1px solid ${LINE}`, borderRadius: 12, overflow: "hidden", background: "#fff" }}>
        <div style={{ padding: "7px 13px", background: "#F7F9FC", fontSize: 10.5, fontWeight: 900, letterSpacing: ".08em", textTransform: "uppercase", color: MUTED }}>
          Sells for more than yours
        </div>
        {b.above.length ? b.above.map((r) => compRow(r, "above"))
          : <div style={{ padding: "9px 13px", fontSize: 12.5, color: MUTED, borderTop: `1px solid ${LINE}` }}>Nothing above yet.</div>}

        {/* the subject, placed into the ladder rather than shown beside it */}
        <div style={{ borderTop: `2px solid ${NAVY}`, borderBottom: `2px solid ${NAVY}`, background: "#FBF1EC", padding: "12px 13px" }}>
          <div style={{ fontSize: 10.5, fontWeight: 900, letterSpacing: ".08em", textTransform: "uppercase", color: TERRA, marginBottom: 7 }}>
            Your seller's home
          </div>
          <div style={{ display: "flex", gap: 9, alignItems: "center", flexWrap: "wrap" }}>
            <span style={{ fontSize: 15, fontWeight: 800, color: NAVY }}>$</span>
            <input value={price} inputMode="numeric"
              onChange={(e) => setPrice(e.target.value.replace(/[^0-9,]/g, ""))}
              aria-label="Launch price"
              placeholder={floor && ceiling ? String(Math.round((floor + ceiling) / 2)) : "launch price"}
              style={{ font: "inherit", fontSize: 17, fontWeight: 800, color: NAVY, width: 150,
                       padding: "9px 11px", borderRadius: 8, border: `1px solid ${LINE}`,
                       background: "#fff", fontVariantNumeric: "tabular-nums" }} />
            <button type="button" onClick={() => void save()} disabled={busy || !n}
              style={{ minHeight: 44, border: "none", borderRadius: 8, padding: "11px 18px",
                       fontSize: 13, fontWeight: 800, font: "inherit",
                       background: busy || !n ? "#d7dce6" : TERRA, color: busy || !n ? "#8a93a6" : "#fff",
                       cursor: busy || !n ? "default" : "pointer" }}>
              {busy ? (stage || "Setting…") : "Use this price"}
            </button>
          </div>
          {busy && stage && (
            <div style={{ marginTop: 8, fontSize: 12.5, color: TERRA, fontWeight: 600, lineHeight: 1.45 }}>
              {stage} This takes a couple of minutes. You can keep working.
            </div>
          )}
          {(tooHigh || tooLow) && (
            <div style={{ marginTop: 8, fontSize: 12.5, color: "#8a5a12", lineHeight: 1.45 }}>
              {tooHigh
                ? <>That sits at or above {money(ceiling)}, a home your comps say beats this one. Fine if you mean it, worth a second look if not.</>
                : <>That sits at or below {money(floor)}, a home your comps say this one beats.</>}
            </div>
          )}
          <label style={{ display: "block", marginTop: 10 }}>
            <span style={{ display: "block", fontSize: 11, fontWeight: 700, color: MUTED, marginBottom: 4 }}>
              Why this number (goes in the report)
            </span>
            <input value={why} onChange={(e) => setWhy(e.target.value)}
              placeholder="Optional. Left blank, the comps speak for themselves."
              style={{ font: "inherit", fontSize: 13, width: "100%", boxSizing: "border-box",
                       padding: "9px 11px", borderRadius: 8, border: `1px solid ${LINE}`, background: "#fff" }} />
          </label>
        </div>

        {b.level.length > 0 && (
          <>
            <div style={{ padding: "7px 13px", background: "#F7F9FC", fontSize: 10.5, fontWeight: 900, letterSpacing: ".08em", textTransform: "uppercase", color: MUTED, borderTop: `1px solid ${LINE}` }}>
              Competes closely
            </div>
            {b.level.map((r) => compRow(r, "level"))}
          </>
        )}

        <div style={{ padding: "7px 13px", background: "#F7F9FC", fontSize: 10.5, fontWeight: 900, letterSpacing: ".08em", textTransform: "uppercase", color: MUTED, borderTop: `1px solid ${LINE}` }}>
          Yours sells for more than these
        </div>
        {b.below.length ? b.below.map((r) => compRow(r, "below"))
          : <div style={{ padding: "9px 13px", fontSize: 12.5, color: MUTED, borderTop: `1px solid ${LINE}` }}>Nothing below yet.</div>}
      </div>

      {/* ON THE MARKET NOW.
          Solds are what a buyer actually paid, so only they set the bracket above.
          These are who the seller is up against this week, and they are reported
          without ever moving the ceiling or the floor: "competition, not evidence
          of value". What earns their place is what the market has already done to
          them -- a listing that has sat, or has already been cut, is the argument
          against launching high, made with evidence instead of assertion. */}
      {!!b.actives?.length && (
        <div style={{ marginTop: 14, border: `1px solid ${LINE}`, borderRadius: 12, overflow: "hidden", background: "#fff" }}>
          <div style={{ padding: "9px 13px", background: "#F7F9FC", borderBottom: `1px solid ${LINE}`, display: "flex", alignItems: "center", gap: 7 }}>
            <span style={{ fontSize: 10.5, fontWeight: 900, letterSpacing: ".08em", textTransform: "uppercase", color: MUTED }}>
              On the market now
            </span>
            <CmaInfo label="How actives are used">
              Competition, not evidence of value, so these never move the bracket. What they
              do show is what the market is doing to homes priced above it right now.
            </CmaInfo>
          </div>
          {b.actives.map((a: ActiveRow) => {
            const undercuts = !!(n && a.listPrice && a.listPrice < n);
            return (
              <div key={a.mls} style={{ borderTop: `1px solid ${LINE}`, padding: "10px 13px" }}>
                <div style={{ display: "flex", alignItems: "baseline", gap: 10 }}>
                  <span style={{ flex: 1, minWidth: 0, fontSize: 13, fontWeight: 600, color: NAVY }}>
                    {a.address}
                    <span style={{ display: "block", fontSize: 11.5, fontWeight: 400, color: a.cut ? TERRA : MUTED, marginTop: 2 }}>
                      {a.story}
                    </span>
                  </span>
                  <span style={{ textAlign: "right", fontVariantNumeric: "tabular-nums" }}>
                    <span style={{ fontSize: 13.5, fontWeight: 800, color: NAVY }}>{money(a.listPrice)}</span>
                    {!!a.cut && a.origPrice && (
                      <span style={{ display: "block", fontSize: 11, color: MUTED, textDecoration: "line-through" }}>
                        {money(a.origPrice)}
                      </span>
                    )}
                  </span>
                </div>
                {undercuts && (
                  <div style={{ marginTop: 6, fontSize: 12, color: "#8a5a12", lineHeight: 1.45 }}>
                    Asking less than your number. A buyer sees both.
                  </div>
                )}
                {a.note && (
                  <p style={{ margin: "7px 0 0", fontSize: 12.5, lineHeight: 1.55, color: INK2 }}>{a.note}</p>
                )}
              </div>
            );
          })}
        </div>
      )}

      {!!b.unpositioned && (
        <p style={{ margin: "9px 0 0", fontSize: 12.5, color: MUTED, lineHeight: 1.5 }}>
          {b.unpositioned} comp{b.unpositioned === 1 ? " has" : "s have"} no position yet, so
          {b.unpositioned === 1 ? " it sits" : " they sit"} level with the home. Set them on the
          Comparables step to tighten the bracket.
        </p>
      )}
      {err && <div style={{ marginTop: 8, fontSize: 12.5, color: "#9B3B2E" }}>{err}</div>}
    </div>
  );
}
