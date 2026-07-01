// CMA wizard — the approved 5-step stepper (Subject → Comparables → Photos →
// Pricing → Generate). One step at a time; review the comps and drop bad ones
// before advancing. Drives the 8-phase checkpointed runner underneath
// (cma-phase-runner.py) so a stall in one phase never loses the rest.
import { useEffect, useState } from "react";
import { api } from "../../../../lib/api";

const NAVY = "#182848", MUTED = "#7b869c", LINE = "#e3e7ef", BLUE = "#5E8AD0", GREEN = "#2f7a4d", TERRA = "#C46340";

type Phase = { id: string; label: string; browser: boolean; manual: boolean; status: string; attempts: number; error?: string | null };
type Comp = { mls: string; address: string; price: string | number; soldDate?: string | null; status?: string; beds?: number; baths?: number; year?: number; excluded?: boolean; compNum?: number };
type TierC = { address: string; price: string | number; suite?: unknown };
type Pricing = { recommendedPrice?: string | null; range?: string | null; strategy?: string | null; better?: TierC[]; comparable?: TierC[]; worse?: TierC[] } | null;

// 8 runner phases grouped into the 5 display steps.
const STEPS: { key: string; label: string; phases: string[]; blurb: string }[] = [
  { key: "subject", label: "Subject", phases: ["collect"], blurb: "Pull the subject property + its sold comps from the MLS." },
  { key: "comparables", label: "Comparables", phases: ["actives"], blurb: "Pull active competition, then confirm the comp set — drop any that don't fit." },
  { key: "photos", label: "Photos", phases: ["photos"], blurb: "Score condition & finish on the subject and each comp (done by the agent)." },
  { key: "pricing", label: "Pricing", phases: ["normalize", "finish"], blurb: "Normalize the comps and build the sandwich pricing." },
  { key: "generate", label: "Generate", phases: ["prospecting", "render", "qa"], blurb: "Capture buyer demand, render the CMA, and run the visual QA gate." },
];

export default function CmaWizard({ dealId }: { dealId: string }) {
  const [phases, setPhases] = useState<Phase[]>([]);
  const [pdfUrl, setPdfUrl] = useState<string>("");
  const [comps, setComps] = useState<{ sold: Comp[]; active: Comp[] }>({ sold: [], active: [] });
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState("");
  const [viewIdx, setViewIdx] = useState<number | null>(null);
  const [open, setOpen] = useState(true);
  const [regen, setRegen] = useState("");
  const [pricing, setPricing] = useState<Pricing>(null);
  const [take, setTake] = useState({ price: "", rationale: "" });
  const [prospectMls, setProspectMls] = useState("");

  const load = () => api.getCmaPhases(dealId)
    .then(async (r) => {
      setPhases(r.phases || []); setPdfUrl(r.pdfUrl || "");
      if ((r.phases || []).some((p: Phase) => p.id === "collect" && p.status === "done")) {
        try { setComps(await api.getCmaComps(dealId)); } catch { /* ignore */ }
      }
    })
    .catch(() => setPhases([]))
    .finally(() => setLoading(false));
  useEffect(() => { void load(); }, [dealId]);

  // Poll while a phase runs (backend runs detached).
  useEffect(() => {
    if (!phases.some((p) => p.status === "running")) return;
    const t = setTimeout(() => { void load(); }, 4000);
    return () => clearTimeout(t);
  }, [phases]); // eslint-disable-line react-hooks/exhaustive-deps

  // Pull the pricing breakdown once the pricing engine (normalize) has run.
  useEffect(() => {
    if (phases.some((p) => p.id === "normalize" && p.status === "done")) {
      api.getCmaPricing(dealId).then(setPricing).catch(() => { /* ignore */ });
    }
  }, [phases, dealId]);

  const byId = (id: string) => phases.find((p) => p.id === id);
  const stepStatus = (s: typeof STEPS[number]) => {
    const ps = s.phases.map(byId).filter(Boolean) as Phase[];
    if (ps.length && ps.every((p) => p.status === "done")) return "done";
    if (ps.some((p) => p.status === "running")) return "running";
    if (ps.some((p) => p.status === "failed")) return "failed";
    return "todo";
  };
  const stepDone = (s: typeof STEPS[number]) => stepStatus(s) === "done";
  const curIdx = Math.min(STEPS.findIndex((s) => !stepDone(s)) === -1 ? STEPS.length - 1 : STEPS.findIndex((s) => !stepDone(s)), STEPS.length - 1);
  const shown = viewIdx ?? curIdx;
  const step = STEPS[shown];
  const done = STEPS.filter(stepDone).length;

  // next runnable (deterministic, deps-met-ish) phase in the shown step
  const nextRunnable = step.phases.map(byId).find((p) => p && p.status !== "done" && !p.manual);
  const blockingManual = step.phases.map(byId).find((p) => p && p.status !== "done" && p.manual);

  const run = async (id: string) => {
    setBusy(id);
    try { await api.runCmaPhase(dealId, id); await load(); } finally { setBusy(""); }
  };
  const skipPhotos = async () => {
    setBusy("skip");
    try { await api.skipCmaPhotos(dealId); await load(); } finally { setBusy(""); }
  };
  const regenerate = async () => {
    setBusy("regen");
    try { await api.regenerateCmaComps(dealId, regen); setViewIdx(1); await load(); } finally { setBusy(""); }
  };
  const doReprice = async () => {
    if (!take.price.trim()) return;
    setBusy("reprice");
    try {
      await api.repriceCma(dealId, take.price, take.rationale);
      setTimeout(() => { void api.getCmaPricing(dealId).then(setPricing).catch(() => { /* ignore */ }); void load(); }, 4500);
    } finally { setBusy(""); }
  };
  const captureProspecting = async () => {
    if (!prospectMls) return;
    setBusy("prospect");
    try { await api.captureCmaProspecting(dealId, prospectMls); await load(); } finally { setBusy(""); }
  };
  const reloadComps = () => api.getCmaComps(dealId).then(setComps).catch(() => { /* ignore */ });
  const toggleComp = (mls: string, kind: "sold" | "active") =>
    api.toggleCmaComp(dealId, mls, kind).then(reloadComps).catch(() => { /* ignore */ });

  const compRows = (title: string, list: Comp[], kind: "sold" | "active") => {
    const kept = list.filter((c) => !c.excluded).length;
    return (
      <div style={{ marginTop: 12, border: `1px solid ${LINE}`, borderRadius: 10, padding: "11px 13px", background: "#fbfcfe" }}>
        <div style={{ fontSize: 11, fontWeight: 800, color: MUTED, textTransform: "uppercase", letterSpacing: 0.4, marginBottom: 7 }}>{title} — {kept} of {list.length} kept · untick to drop a bad comp</div>
        {list.map((c) => (
          <div key={c.mls + c.address} style={{ display: "flex", alignItems: "center", gap: 10, padding: "6px 2px", borderTop: "1px solid #f0f2f7", fontSize: 12.5, opacity: c.excluded ? 0.45 : 1 }}>
            <input type="checkbox" checked={!c.excluded} onChange={() => toggleComp(c.mls, kind)} style={{ cursor: "pointer", flex: "0 0 auto" }} />
            {c.compNum != null && (
              <img src={`/api/admin/deals/${encodeURIComponent(dealId)}/cma/comp-photo/${c.compNum}`} alt=""
                onError={(e) => { (e.currentTarget as HTMLImageElement).style.visibility = "hidden"; }}
                style={{ width: 44, height: 33, objectFit: "cover", borderRadius: 5, flex: "0 0 auto", background: "#eef1f6", border: `1px solid ${LINE}` }} />
            )}
            <span style={{ flex: 1, fontWeight: 700, color: NAVY, textDecoration: c.excluded ? "line-through" : "none" }}>{c.address}</span>
            <span style={{ color: MUTED }}>{c.beds}bd/{c.baths}ba{c.year ? ` · ${c.year}` : ""}</span>
            <span style={{ fontWeight: 800, color: NAVY, minWidth: 78, textAlign: "right" }}>{String(c.price)}</span>
            <span style={{ fontSize: 10.5, color: MUTED, minWidth: 62 }}>{c.soldDate || c.status}</span>
          </div>
        ))}
      </div>
    );
  };

  const lblPS: React.CSSProperties = { fontSize: 10, fontWeight: 700, color: "#9aa4b8", textTransform: "uppercase", display: "block", marginBottom: 3 };
  const inPS: React.CSSProperties = { width: "100%", border: "1px solid #dde3ee", borderRadius: 7, padding: "8px 10px", fontSize: 12.5, fontWeight: 600, color: "#1c2433", background: "#fff", fontFamily: "inherit" };
  const tierRows = (label: string, list: TierC[] | undefined, color: string) =>
    (list || []).map((c, i) => (
      <div key={label + i + c.address} style={{ display: "flex", alignItems: "center", gap: 10, padding: "5px 2px", borderTop: "1px solid #f0f2f7", fontSize: 12.5 }}>
        <span style={{ fontSize: 9.5, fontWeight: 800, color: "#fff", background: color, borderRadius: 5, padding: "2px 7px", whiteSpace: "nowrap" }}>{label}</span>
        <span style={{ flex: 1, fontWeight: 700, color: NAVY }}>{c.address}{c.suite ? <span style={{ fontWeight: 400, color: MUTED }}> · suite</span> : null}</span>
        <span style={{ fontWeight: 800, color: NAVY }}>{typeof c.price === "number" ? `$${c.price.toLocaleString()}` : String(c.price || "")}</span>
      </div>
    ));

  // ---- stepper ----
  const dot = (n: number) => {
    const st = stepStatus(STEPS[n]);
    const isView = n === shown;
    if (st === "done") return { bg: GREEN, fg: "#fff", txt: "✓", ring: isView ? "0 0 0 3px #d6eade" : "none" };
    if (isView) return { bg: TERRA, fg: "#fff", txt: String(n + 1), ring: "0 0 0 4px #f5dccf" };
    if (st === "running") return { bg: "#fdf1e9", fg: TERRA, txt: "…", ring: "none" };
    if (st === "failed") return { bg: "#fdeaea", fg: "#d44", txt: "!", ring: "none" };
    return { bg: "#e7ebf2", fg: "#9aa4b8", txt: String(n + 1), ring: "none" };
  };

  return (
    <section style={{ border: `1px solid ${LINE}`, borderRadius: 12, marginTop: 14, overflow: "hidden", background: "#fff" }}>
      <header onClick={() => setOpen((o) => !o)} style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "13px 18px", background: NAVY, color: "#fff", cursor: "pointer" }}>
        <div style={{ fontWeight: 700, fontSize: 14 }}>CMA — Market Evaluation
          <span style={{ fontWeight: 400, fontSize: 12, color: "#b9c4dc", marginLeft: 8 }}>Step {Math.min(shown + 1, 5)} of 5</span>
        </div>
        <span style={{ fontSize: 12, color: "#b9c4dc" }}>{done}/5 · {open ? "▾" : "▸"}</span>
      </header>
      {open && (
        <div style={{ padding: "16px 18px" }}>
          {loading && <div style={{ fontSize: 12, color: MUTED }}>Loading…</div>}
          {!loading && (<>
            {/* stepper */}
            <div style={{ display: "flex", alignItems: "center", marginBottom: 18 }}>
              {STEPS.map((s, n) => {
                const d = dot(n); const st = stepStatus(s);
                return (
                  <div key={s.key} style={{ display: "flex", alignItems: "center", flex: n < STEPS.length - 1 ? 1 : "0 0 auto" }}>
                    <div onClick={() => setViewIdx(n)} style={{ display: "flex", alignItems: "center", cursor: "pointer" }}>
                      <span style={{ width: 28, height: 28, borderRadius: "50%", flex: "0 0 auto", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 12.5, fontWeight: 700, background: d.bg, color: d.fg, boxShadow: d.ring === "none" ? undefined : d.ring }}>{d.txt}</span>
                      <span style={{ fontSize: 11.5, fontWeight: n === shown ? 700 : 600, marginLeft: 7, whiteSpace: "nowrap", color: st === "done" ? GREEN : n === shown ? NAVY : "#9aa4b8" }}>{s.label}</span>
                    </div>
                    {n < STEPS.length - 1 && <div style={{ flex: 1, height: 3, background: stepDone(s) ? GREEN : "#e7ebf2", margin: "0 8px", borderRadius: 2 }} />}
                  </div>
                );
              })}
            </div>

            {/* step panel */}
            <div style={{ border: `1px solid ${LINE}`, borderRadius: 12, padding: "16px 18px" }}>
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                <h2 style={{ fontSize: 14.5, color: NAVY, margin: 0 }}>{step.label}</h2>
                <span style={{ fontSize: 10.5, fontWeight: 700, borderRadius: 6, padding: "3px 9px",
                  background: stepStatus(step) === "done" ? "#eaf5ee" : stepStatus(step) === "failed" ? "#fdeaea" : stepStatus(step) === "running" ? "#fdf1e9" : "#eef1f6",
                  color: stepStatus(step) === "done" ? GREEN : stepStatus(step) === "failed" ? "#d44" : stepStatus(step) === "running" ? TERRA : MUTED }}>{stepStatus(step)}</span>
              </div>
              <div style={{ fontSize: 12, color: MUTED, marginTop: 4, marginBottom: 12 }}>{step.blurb}</div>

              {step.key === "comparables" && stepDone(STEPS[0]) && comps.sold.length > 0 && compRows("Sold comps", comps.sold, "sold")}
              {step.key === "comparables" && byId("actives")?.status === "done" && comps.active.length > 0 && compRows("Active comps", comps.active, "active")}

              {step.key === "comparables" && stepDone(STEPS[0]) && (
                <div style={{ marginTop: 14, border: `1px solid ${LINE}`, borderRadius: 10, padding: "12px 13px", background: "#fbfcfe" }}>
                  <div style={{ fontSize: 11, fontWeight: 800, color: MUTED, textTransform: "uppercase", letterSpacing: 0.4, marginBottom: 7 }}>Regenerate comps — what to change in the search</div>
                  <textarea value={regen} onChange={(e) => setRegen(e.target.value)} rows={2}
                    placeholder="e.g. expand to Westsyde + Westmount + North Kamloops, target $635k, suite priority"
                    style={{ width: "100%", border: `1px solid #dde3ee`, borderRadius: 8, padding: "8px 10px", fontSize: 12.5, fontFamily: "inherit", color: "#1c2433", resize: "vertical" }} />
                  <div style={{ display: "flex", alignItems: "center", gap: 11, marginTop: 9 }}>
                    <button onClick={regenerate} disabled={!!busy}
                      style={{ fontSize: 12.5, fontWeight: 700, padding: "8px 16px", borderRadius: 9, border: "none", background: busy ? "#d7dce6" : TERRA, color: busy ? "#8a93a6" : "#fff", cursor: busy ? "wait" : "pointer" }}>
                      {busy === "regen" ? "Re-pulling…" : "Regenerate comps"}</button>
                    <span style={{ fontSize: 11, color: MUTED }}>Re-pulls from Xposure with your changes (areas + target price), then re-runs from here.</span>
                  </div>
                </div>
              )}

              {step.key === "pricing" && pricing && (
                <div style={{ marginTop: 4 }}>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", background: NAVY, color: "#fff", borderRadius: 10, padding: "12px 16px", marginBottom: 12 }}>
                    <span style={{ fontSize: 11.5, fontWeight: 700, color: "#aeb9d4" }}>RECOMMENDED</span>
                    <span style={{ fontSize: 21, fontWeight: 800 }}>{pricing.recommendedPrice || "—"}{pricing.range ? <span style={{ fontSize: 11.5, fontWeight: 600, color: "#aeb9d4", marginLeft: 10 }}>range {pricing.range}</span> : null}</span>
                  </div>
                  {((pricing.better?.length || 0) + (pricing.comparable?.length || 0) + (pricing.worse?.length || 0)) > 0 && (
                    <div style={{ border: `1px solid ${LINE}`, borderRadius: 10, padding: "10px 13px", marginBottom: 12, background: "#fbfcfe" }}>
                      <div style={{ fontSize: 11, fontWeight: 800, color: MUTED, textTransform: "uppercase", letterSpacing: 0.4, marginBottom: 6 }}>How it priced — your home vs the comps</div>
                      {tierRows("BETTER", pricing.better, GREEN)}
                      <div style={{ background: "#fff4ec", border: `1px dashed ${TERRA}`, borderRadius: 8, padding: "7px 11px", fontSize: 12.5, fontWeight: 700, color: "#8a4a25", margin: "7px 0" }}>▶ YOUR HOME — positioned at {pricing.recommendedPrice || "—"}</div>
                      {tierRows("COMPARABLE", pricing.comparable, "#6b7689")}
                      {tierRows("WORSE", pricing.worse, TERRA)}
                    </div>
                  )}
                  {pricing.strategy && (
                    <div style={{ border: `1px solid ${LINE}`, borderRadius: 10, padding: "11px 13px", marginBottom: 12, fontSize: 12.5, color: "#384256", lineHeight: 1.55 }}>{String(pricing.strategy)}</div>
                  )}
                  <div style={{ border: `1.5px solid ${TERRA}`, borderRadius: 11, padding: "13px 15px", background: "#fffdfb" }}>
                    <div style={{ fontSize: 13, fontWeight: 800, color: NAVY, marginBottom: 9 }}>Your take — tell it what it's missing</div>
                    <div style={{ display: "flex", gap: 12, alignItems: "flex-start" }}>
                      <label style={{ flex: "0 0 130px" }}><span style={lblPS}>Target list price</span>
                        <input value={take.price} placeholder="$635,000" onChange={(e) => setTake((t) => ({ ...t, price: e.target.value }))} style={inPS} /></label>
                      <label style={{ flex: 1 }}><span style={lblPS}>Why (folded into the CMA + re-prices)</span>
                        <input value={take.rationale} placeholder="Suite = rental income; repainted; kept comps support it" onChange={(e) => setTake((t) => ({ ...t, rationale: e.target.value }))} style={inPS} /></label>
                    </div>
                    <button onClick={doReprice} disabled={!!busy || !take.price.trim()}
                      style={{ background: (busy || !take.price.trim()) ? "#d7dce6" : "#044B35", color: (busy || !take.price.trim()) ? "#8a93a6" : "#fff", border: "none", fontSize: 13, fontWeight: 700, padding: "10px 18px", borderRadius: 9, marginTop: 10, cursor: busy ? "wait" : "pointer" }}>
                      {busy === "reprice" ? "Re-pricing…" : "Re-price with my take →"}</button>
                    <div style={{ fontSize: 11, color: MUTED, marginTop: 7 }}>Forces your exact number, folds your reasoning in, and re-derives the sandwich + comp descriptions + final PDF.</div>
                  </div>

                  <div style={{ marginTop: 12, border: `1px solid ${LINE}`, borderRadius: 10, padding: "12px 14px", background: "#fbfcfe" }}>
                    <div style={{ fontSize: 11, fontWeight: 800, color: MUTED, textTransform: "uppercase", letterSpacing: 0.4, marginBottom: 7 }}>Buyer-demand prospecting</div>
                    {byId("prospecting")?.status === "done" ? (
                      <div style={{ fontSize: 12.5, fontWeight: 700, color: GREEN }}>✓ Buyer demand captured — ready to Generate.</div>
                    ) : (byId("prospecting")?.status === "running" || busy === "prospect") ? (
                      <div style={{ fontSize: 12.5, color: TERRA, fontWeight: 700 }}>Capturing from Xposure… (one last login, ~1–2 min — keep going)</div>
                    ) : (
                      <>
                        <div style={{ fontSize: 12, color: "#384256", marginBottom: 7 }}>Pick the active listing to anchor the buyer-demand pull (one priced near your number reads cleanest):</div>
                        <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
                          <select value={prospectMls} onChange={(e) => setProspectMls(e.target.value)}
                            style={{ flex: 1, minWidth: 220, border: "1px solid #dde3ee", borderRadius: 7, padding: "8px 10px", fontSize: 12.5, color: "#1c2433", background: "#fff" }}>
                            <option value="">Select an active comp…</option>
                            {comps.active.filter((c) => !c.excluded).map((c) => (
                              <option key={c.mls} value={c.mls}>{c.address} — {String(c.price)}</option>
                            ))}
                          </select>
                          <button onClick={captureProspecting} disabled={!!busy || !prospectMls}
                            style={{ fontSize: 12.5, fontWeight: 700, padding: "9px 16px", borderRadius: 9, border: "none", background: (busy || !prospectMls) ? "#d7dce6" : NAVY, color: (busy || !prospectMls) ? "#8a93a6" : "#fff", cursor: busy ? "wait" : "pointer" }}>
                            Capture buyer demand</button>
                        </div>
                      </>
                    )}
                  </div>
                </div>
              )}
              {step.key === "pricing" && !pricing && stepDone(step) && (
                <div style={{ fontSize: 12.5, color: MUTED, marginTop: 8 }}>Loading pricing breakdown…</div>
              )}

              {/* failed phase error */}
              {step.phases.map(byId).filter((p) => p?.status === "failed").map((p) => (
                <div key={p!.id} style={{ fontSize: 11.5, color: "#d44", marginTop: 8 }}>{p!.label}: {(p!.error || "").slice(0, 110)}</div>
              ))}

              {/* action row */}
              <div style={{ display: "flex", alignItems: "center", gap: 12, marginTop: 14 }}>
                {stepStatus(step) === "running"
                  ? <span style={{ fontSize: 12.5, fontWeight: 700, color: TERRA }}>running… {byId(step.phases.find((id) => byId(id)?.status === "running") || "")?.browser ? "(browser)" : ""}</span>
                  : stepDone(step)
                  ? <span style={{ fontSize: 13, fontWeight: 700, color: GREEN }}>✓ {step.label} complete</span>
                  : nextRunnable
                  ? <button onClick={() => run(nextRunnable.id)} disabled={!!busy}
                      style={{ fontSize: 13, fontWeight: 700, padding: "9px 18px", borderRadius: 9, border: "none", background: busy ? "#d7dce6" : NAVY, color: busy ? "#8a93a6" : "#fff", cursor: busy ? "wait" : "pointer" }}>
                      {busy === nextRunnable.id ? "Running…" : `Run ${nextRunnable.label}`}</button>
                  : blockingManual
                  ? <span style={{ fontSize: 12.5, color: MUTED }}><b style={{ color: NAVY }}>{blockingManual.label}</b> — capture via the CMA agent, then it advances</span>
                  : <span style={{ fontSize: 12.5, color: MUTED }}>Waiting on an earlier step.</span>}
                {step.key === "generate" && pdfUrl && (
                  <a href={pdfUrl} target="_blank" rel="noreferrer" style={{ fontSize: 13, fontWeight: 700, color: BLUE, textDecoration: "none" }}>Open CMA PDF ↗</a>
                )}
                {step.key === "photos" && !stepDone(step) && stepStatus(step) !== "running" && (
                  <button onClick={skipPhotos} disabled={!!busy} title="No usable photos — score finish neutral and continue (price-based CMA)"
                    style={{ fontSize: 12.5, fontWeight: 700, padding: "8px 14px", borderRadius: 8, border: `1px solid ${LINE}`, background: "#fff", color: NAVY, cursor: busy ? "wait" : "pointer" }}>
                    {busy === "skip" ? "Skipping…" : "Skip — no photos"}</button>
                )}
              </div>
            </div>

            {/* nav */}
            <div style={{ display: "flex", justifyContent: "space-between", marginTop: 14 }}>
              <button onClick={() => setViewIdx(Math.max(0, shown - 1))} disabled={shown === 0}
                style={{ fontSize: 13, fontWeight: 600, padding: "10px 16px", borderRadius: 9, border: `1px solid ${LINE}`, background: "#fff", color: shown === 0 ? "#c7cedb" : MUTED, cursor: shown === 0 ? "default" : "pointer" }}>← Back</button>
              <button onClick={() => setViewIdx(Math.min(STEPS.length - 1, shown + 1))} disabled={shown === STEPS.length - 1 || !stepDone(step)}
                title={!stepDone(step) ? "Finish this step first" : ""}
                style={{ fontSize: 13.5, fontWeight: 700, padding: "11px 20px", borderRadius: 9, border: "none", background: (shown === STEPS.length - 1 || !stepDone(step)) ? "#d7dce6" : NAVY, color: (shown === STEPS.length - 1 || !stepDone(step)) ? "#8a93a6" : "#fff", cursor: (shown === STEPS.length - 1 || !stepDone(step)) ? "default" : "pointer" }}>
                Continue →</button>
            </div>
          </>)}
        </div>
      )}
    </section>
  );
}
