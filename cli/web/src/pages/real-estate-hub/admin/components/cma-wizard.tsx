// CMA wizard: the approved mockup's 4 steps (Property, Comparables, Pricing,
// Report). One step at a time; review the comps and drop bad ones before
// advancing. Drives the 8-phase checkpointed runner underneath
// (cma-phase-runner.py) so a stall in one phase never loses the rest.
//
// Hosted full-screen by CmaSurface (see cma-surface.tsx), opened from the deal
// card. It renders standalone too, so nothing here may assume a chrome around it.
import { useCallback, useEffect, useState } from "react";
import { api } from "../../../../lib/api";
import { useIsMobile } from "../../../../hooks/useIsMobile";
import CmaCompReview from "./cma-comp-review";
import CmaBuyerDemand from "./cma-buyer-demand";
import CmaAddressField from "./cma-address-field";
import CmaSubjectFacts from "./cma-subject-facts";
import CmaMyRead from "./cma-my-read";
import CmaApprovedDesign from "./cma-approved-design";
import CmaPositioned from "./cma-positioned";
import CmaBracket from "./cma-bracket";
import CmaInfo from "./cma-info";
import CmaReportBuild from "./cma-report-build";

const NAVY = "#182848", MUTED = "#7b869c", LINE = "#e3e7ef", BLUE = "#5E8AD0", GREEN = "#2f7a4d", TERRA = "#C46340";

type Phase = { id: string; label: string; browser: boolean; manual: boolean; status: string; attempts: number; error?: string | null };
type Comp = { mls: string; address: string; price: string | number; soldDate?: string | null; status?: string; beds?: number; baths?: number; year?: number; excluded?: boolean; compNum?: number; setAsideReason?: string | null; setAsideText?: string | null; carriedOver?: boolean };
type TierC = import("./cma-positioned").TierComp;
type Pricing = { recommendedPrice?: string | null; range?: string | null; strategy?: string | null; better?: TierC[]; comparable?: TierC[]; worse?: TierC[]; expired?: import("./cma-positioned").ExpiredBand | null; freshness?: import("./cma-positioned").Freshness | null } | null;

// The 8 runner phases grouped into the APPROVED MOCKUP's 4 steps.
//
// The old 5 steps were named after what the RUNNER does (Subject, Comparables,
// Photos, Pricing, Generate). The mockup names them after what Skyleigh is
// DECIDING, which is why it read as a different tool: photos are not a stage of
// a pipeline to her, they are part of describing the property; buyer demand is
// not a stage either, it is a pricing argument.
//
//   Property     collect + photos     her home: its facts and its photos
//   Comparables  actives              what it is worth against
//   Pricing      normalize + finish + prospecting   the number, and what moving it buys
//   Report       render + qa          what the seller actually sees
//
// `photos` and `prospecting` are both manual:true in the runner, so they are
// skipped by nextRunnable and driven by their own UI inside the step. That is
// what makes this a regrouping rather than a rewrite.
const STEPS: { key: string; label: string; phases: string[]; blurb: string }[] = [
  { key: "property", label: "Property", phases: ["collect", "photos"], blurb: "Pull the property and its sold comps from the MLS, then add the photos." },
  { key: "comparables", label: "Comparables", phases: ["actives"], blurb: "Pull active competition, then confirm the comp set and drop any that don't fit." },
  { key: "pricing", label: "Pricing", phases: ["normalize", "finish", "prospecting"], blurb: "Build the sandwich pricing, then capture how many buyers each price reaches." },
  { key: "report", label: "Report", phases: ["render", "qa"], blurb: "Render the CMA and run the visual QA gate." },
];

export default function CmaWizard({ dealId, bare = false, address = "", onAddressChange }: {
  dealId: string; bare?: boolean; address?: string | null;
  onAddressChange?: (next: string) => void;
}) {
  const isMobile = useIsMobile();
  const [phases, setPhases] = useState<Phase[]>([]);
  const [reportReady, setReportReady] = useState(false);
  const [reportVersion, setReportVersion] = useState("");
  const [revision, setRevision] = useState(0);
  const [pdfUrl, setPdfUrl] = useState<string>("");
  const [comps, setComps] = useState<{ sold: Comp[]; active: Comp[]; subject?: import('../../../../lib/api').CmaFacts | null }>({ sold: [], active: [] });
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState("");
  const [viewIdx, setViewIdx] = useState<number | null>(null);
  const [open, setOpen] = useState(true);
  const [regen, setRegen] = useState("");
  const [savedList, setSavedList] = useState("");
  const [listState, setListState] = useState<{ state: string; error?: string; solds?: number; actives?: number; compsPulled?: number } | null>(null);
  const [pricing, setPricing] = useState<Pricing>(null);
  const [prospectMls, setProspectMls] = useState("");
  const [photosUrl, setPhotosUrl] = useState("");
  const [photosSaved, setPhotosSaved] = useState(false);
  const [photosUrlSet, setPhotosUrlSet] = useState(false); // a link is saved on the deal
  const [editingPhotos, setEditingPhotos] = useState(false);
  const [noPhotos, setNoPhotos] = useState(false);         // agent chose "no photos"
  const [scoring, setScoring] = useState(false);           // photo run dispatched, awaiting result
  const [runErr, setRunErr] = useState("");                // last phase-dispatch error, surfaced inline
  // The address prop is the source of truth (the surface owns it and re-feeds it
  // after a save). The override only covers the gap when this component is used
  // WITHOUT an onAddressChange parent, and it is keyed by dealId so it can never
  // leak one property's address onto another. Deriving it this way avoids a
  // setState-inside-useEffect prop-sync, which cascades renders.
  const [addrOverride, setAddrOverride] = useState<{ id: string; value: string } | null>(null);
  const addr = addrOverride && addrOverride.id === dealId ? addrOverride.value : (address || "");
  const [addrDraft, setAddrDraft] = useState("");
  const [editAddr, setEditAddr] = useState(false);
  const [addrErr, setAddrErr] = useState("");

  // Writes the deal's listing_address, which is what cma-phase-runner resolves
  // every phase against. Nothing is re-pulled automatically: changing the address
  // after a pull would silently invalidate comps she may have already reviewed,
  // so the copy tells her to pull again and she decides when.
  const saveAddr = async (raw: string) => {
    const next = (raw || "").trim();
    if (!next) return;
    setBusy("addr"); setAddrErr("");
    try {
      await api.updateDealFields(dealId, { listing_address: next });
      setAddrOverride({ id: dealId, value: next }); setEditAddr(false); onAddressChange?.(next);
    } catch (e) {
      setAddrErr(e instanceof Error ? e.message : "Could not save that address.");
    } finally { setBusy(""); }
  };

  const load = () => api.getCmaPhases(dealId)
    .then(async (r) => {
      setPhases(r.phases || []); setPdfUrl(r.pdfUrl || "");
      api.getCmaProspectingStatus(dealId).then((p) => setProspect({ state: p.state || "idle", message: p.message })).catch(() => {});
      setReportReady(!!r.reportReady); setReportVersion(r.reportVersion || ""); setRevision(r.revision || 0);
      setPhotosUrlSet(!!r.photosUrlSet);
      api.getCmaStagedPhotos(dealId).then((p) => { setDropped(p.count); if (p.count > 0) setPhotosSaved(true); }).catch(() => {});
      if (r.photosUrl && !photosUrl) setPhotosUrl(r.photosUrl);
      // Photo run finished (done or failed) -> stop treating it as in-flight.
      const ph = (r.phases || []).find((p: Phase) => p.id === "photos");
      if (ph && ph.status !== "running") setScoring(false);
      if ((r.phases || []).some((p: Phase) => p.id === "collect" && p.status === "done")) {
        try { setComps(await api.getCmaComps(dealId)); } catch { /* ignore */ }
      }
    })
    .catch(() => setPhases([]))
    .finally(() => setLoading(false));
  useEffect(() => { void load(); }, [dealId]);

  // Poll while a phase runs (backend runs detached) or a photo run is in flight
  // (the detached scorer may not have flipped 'photos' to running yet).
  // Poll the saved-list run. It is detached and takes minutes; without this the
  // button just goes quiet and a failure is indistinguishable from a slow pull.
  useEffect(() => {
    if (listState?.state !== "running") return;
    const t = setTimeout(() => {
      api.getCmaSavedListStatus(dealId)
        .then((r) => { setListState(r); if (r.state === "done") void load(); })
        .catch(() => { /* keep polling */ });
    }, 6000);
    return () => clearTimeout(t);
  }, [listState, dealId]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    api.getCmaSavedListStatus(dealId).then(setListState).catch(() => { /* ignore */ });
  }, [dealId]);

  useEffect(() => {
    // Refresh completed runs too: notes, captures and section choices invalidate them.
    if (!open) return;
    const t = setTimeout(() => { void load(); }, 4000);
    return () => clearTimeout(t);
  }, [phases, scoring, open]); // eslint-disable-line react-hooks/exhaustive-deps

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
  // The Comparables section used to require the WHOLE Property step, which
  // includes photo scoring. So the moment a re-score started, her comps, her
  // exclusions and the side-by-side finish table all vanished off the screen
  // mid-session -- and after a week of genuinely losing notes, work disappearing
  // is indistinguishable from work being deleted. Skyleigh 2026-08-31: "The
  // comparison section side by side isn't there."
  //
  // The comp set only depends on the PULL. Scoring changes the finish numbers
  // inside the table, not whether there are comps to show. Gate on collect.
  const curIdx = Math.min(STEPS.findIndex((s) => !stepDone(s)) === -1 ? STEPS.length - 1 : STEPS.findIndex((s) => !stepDone(s)), STEPS.length - 1);
  const shown = viewIdx ?? curIdx;
  const step = STEPS[shown];
  const done = STEPS.filter(stepDone).length;

  // next runnable (deterministic, deps-met-ish) phase in the shown step
  const nextRunnable = step.phases.map(byId).find((p) => p && p.status !== "done" && !p.manual);
  const blockingManual = step.phases.map(byId).find((p) => p && p.status !== "done" && p.manual);

  // render can't run until its upstream deps are done (cma-phase-runner: render
  // needs finish + actives + prospecting). prospecting is a manual capture the
  // wizard offers just above, so nextRunnable happily lands on render before it's
  // captured — the runner then silently no-ops (detached, output discarded) and
  // the click looks dead. Gate it here so the button never dispatches a doomed run.
  const isDone = (id: string) => byId(id)?.status === "done";
  const compsReady = isDone("collect") && comps.sold.length > 0;
  const renderBlocked = nextRunnable?.id === "render"
    && !(isDone("photos") && isDone("actives") && isDone("prospecting"));

  const run = async (id: string) => {
    setBusy(id); setRunErr("");
    try { await api.runCmaPhase(dealId, id); await load(); }
    catch (e) { setRunErr(e instanceof Error ? e.message : "Could not start that step. Try again."); }
    finally { setBusy(""); }
  };
  // Dropped-file path, the twin of the Drive link. Both stage subject-photo-NN.jpg
  // and both satisfy the same photos phase, so Continue behaves identically after.
  const [dropped, setDropped] = useState(0);
  const [dropBusy, setDropBusy] = useState("");
  const [dropErr, setDropErr] = useState("");
  const onDropFiles = async (files: FileList | null) => {
    const list = Array.from(files || []).filter((f) => /^image\//.test(f.type));
    if (!list.length) return;
    setDropBusy(`0 of ${list.length}`); setDropErr(""); setNoPhotos(false);
    try {
      // Clear first so a smaller second batch never leaves the first batch behind.
      await api.clearCmaPhotos(dealId);
      for (let i = 0; i < list.length; i++) {
        const b64 = await new Promise<string>((resolve, reject) => {
          const fr = new FileReader();
          fr.onload = () => resolve(String(fr.result || ""));
          fr.onerror = () => reject(new Error("could not read " + list[i].name));
          fr.readAsDataURL(list[i]);
        });
        await api.uploadCmaPhoto(dealId, i, b64, list[i].name);
        setDropBusy(`${i + 1} of ${list.length}`);
      }
      const staged = await api.getCmaStagedPhotos(dealId);
      setDropped(staged.count);
      setPhotosSaved(true);   // same "photos are attached" signal the Drive path sets
    } catch (e) {
      setDropErr(e instanceof Error ? e.message : "Some photos did not upload.");
    } finally { setDropBusy(""); }
  };
  const savePhotosUrl = async () => {
    if (!photosUrl.trim()) return;
    setBusy("photos-url");
    try {
      await api.setAdminDealToggle(dealId, "cmaPhotosDriveUrl", photosUrl.trim());
      setPhotosSaved(true); setPhotosUrlSet(true); setNoPhotos(false);
    } finally { setBusy(""); }
  };
  // The Photos step is "decided" once photos are attached OR the agent picks
  // "no photos" — either lights up Continue. Continue then does the work:
  // score the attached photos, or skip (neutral, price-based) if none.
  const photosAttached = photosUrlSet || photosSaved;
  const photosDecided = photosAttached || noPhotos;
  // The Comparables step's only phase, `actives`, is a data-presence check --
  // the runner's command is `test -s active-comps.json`, satisfied by the collect
  // phase. It is not work she does, so making Continue wait for someone to press
  // a separate "Active MLS competition" run button gated the step on a formality:
  // she curated the whole comp set, every checkbox was ticked, and Continue sat
  // dead with no explanation. Same shape as the Photos gate above -- the step is
  // decided once the data is there, and Continue does the mechanical part.
  const activesPresent = comps.active.length > 0;
  const advance = async () => {
    if (step.key === "property" && (!isDone("photos") || editingPhotos)) {
      setBusy("continue"); setRunErr("");
      try {
        // Order matters: `scoring` is what renders "runs in the background", so
        // it must only flip AFTER the dispatch POST resolves 2xx. The old order
        // (setScoring first, no catch) showed "running in the background" while
        // a 400 from the server was silently swallowed as an unhandled
        // rejection -- nothing had run and nothing said so (2026-08-29,
        // 426 Gleneagles). Same runErr surface as the comparables branch.
        if (photosAttached && !noPhotos) { await api.scoreCmaPhotos(dealId); setScoring(true); }
        else { await api.skipCmaPhotos(dealId); }
        await load(); setEditingPhotos(false);
      } catch (e) {
        setRunErr(e instanceof Error ? e.message : "Could not start the photo scoring.");
        return;
      } finally { setBusy(""); }
    }
    if (step.key === "comparables" && !isDone("actives") && activesPresent) {
      setBusy("continue");
      try { await api.runCmaPhase(dealId, "actives"); await load(); }
      catch (e) { setRunErr(e instanceof Error ? e.message : "Could not finish the comparables step."); return; }
      finally { setBusy(""); }
    }
    setViewIdx(Math.min(STEPS.length - 1, shown + 1));
  };
  // Comps from a list she curated in Xposure, rather than the tool's own search.
  const pullSavedList = async () => {
    if (!savedList.trim()) return;
    setBusy("savedlist");
    try {
      await api.cmaFromSavedList(dealId, savedList.trim());
      setListState({ state: "running" });
      await load();
    }
    catch (e) { setRunErr(e instanceof Error ? e.message : "Could not start that pull."); }
    finally { setBusy(""); }
  };
  const regenerate = async () => {
    setBusy("regen");
    try { await api.regenerateCmaComps(dealId, regen); setViewIdx(1); await load(); } catch (e) { setRunErr(e instanceof Error ? e.message : "Could not start the pull."); } finally { setBusy(""); }
  };
  // doReprice lived here. CmaBracket owns setting the price now.
  // The capture runs DETACHED with its output discarded, so this POST returns in
  // milliseconds while the Xposure scrape takes one to two minutes. Without
  // polling a status file the screen dropped straight back to the picker and the
  // button looked dead -- which is exactly what Skyleigh reported.
  const [prospect, setProspect] = useState<{ state: string; message?: string }>({ state: "idle" });
  // Buyer demand had NO WAY BACK once it had run. Skyleigh 2026-09-06: "Buyer
  // demand section. I want to re run this but there is no option." The done state
  // rendered a single green tick and nothing else, so a capture anchored on the
  // wrong listing, or one taken before she moved her price, was permanent for the
  // life of the run. This flag reopens the picker on demand.
  const [redoProspect, setRedoProspect] = useState(false);
  const pollProspect = useCallback(async () => {
    try {
      const r = await api.getCmaProspectingStatus(dealId);
      setProspect({ state: r?.state || "idle", message: r?.message });
      return r?.state;
    } catch { return undefined; }
  }, [dealId]);
  useEffect(() => { void pollProspect(); }, [pollProspect]);
  useEffect(() => {
    if (prospect.state !== "running") return;
    const t = setInterval(() => {
      void pollProspect().then((st) => { if (st === "ok") void load(); });
    }, 4000);
    return () => clearInterval(t);
  }, [prospect.state, pollProspect]); // eslint-disable-line react-hooks/exhaustive-deps

  const captureProspecting = async () => {
    if (!prospectMls) return;
    setRedoProspect(false);
    setBusy("prospect");
    setProspect({ state: "running", message: "Signing in to Xposure" });
    try { await api.captureCmaProspecting(dealId, prospectMls); await load(); }
    catch (e) { setRunErr(e instanceof Error ? e.message : "Could not start the capture."); setProspect({ state: "failed", message: "Capture did not start. Try again." }); }
    finally { setBusy(""); void pollProspect(); }
  };
  const reloadComps = () => api.getCmaComps(dealId).then(setComps).catch(() => { /* ignore */ });
  const toggleComp = (mls: string, kind: "sold" | "active") =>
    api.toggleCmaComp(dealId, mls, kind).then(() => { void reloadComps(); void load(); }).catch((e) => setRunErr(e instanceof Error ? e.message : "Could not save that choice."));



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

  // `body` is an ELEMENT, not a nested component. Declaring a component inside
  // the render (const Shell = () => ...) gives it a new identity every render,
  // so React unmounts and remounts the entire subtree on each keystroke: the
  // regenerate textarea and the price inputs would lose focus mid-typing.
  const body = (
        <div>
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
                      {/* Labels crowd off-screen on a phone; the panel heading already names the step. Show them on the active dot only. */}
                      {(!isMobile || n === shown) && <span style={{ fontSize: 11.5, fontWeight: n === shown ? 700 : 600, marginLeft: 7, whiteSpace: "nowrap", color: st === "done" ? GREEN : n === shown ? NAVY : "#9aa4b8" }}>{s.label}</span>}
                    </div>
                    {n < STEPS.length - 1 && <div style={{ flex: 1, height: 3, background: stepDone(s) ? GREEN : "#e7ebf2", margin: isMobile ? "0 4px" : "0 8px", borderRadius: 2 }} />}
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

              {/* Comp review. Replaces the old one-line-per-comp checkbox list: that
                  showed a single 44x33 thumbnail and five fields, so checking a comp
                  meant logging back into Xposure. This shows every photo and every
                  field we hold, plus the candidates the search saw and did NOT pick,
                  plus the listings that expired. Same toggleComp underneath. */}
              {/* THE ADDRESS. Everything downstream keys off the deal's listing
                  address (the runner resolves comps, photos and the report from
                  it), and until now the Property step showed only a Run button:
                  no way to see what address the pull would use, and no way to
                  correct it without leaving the evaluation. */}
              {step.key === "property" && (
                <div style={{ border: `1px solid ${LINE}`, borderRadius: 10, padding: "12px 13px", marginBottom: 12, background: "#fbfcfe" }}>
                  <div style={{ fontSize: 11, fontWeight: 800, color: MUTED, textTransform: "uppercase", letterSpacing: 0.4, marginBottom: 8, display: "flex", alignItems: "center", gap: 7 }}>
                    Property address
                    <CmaInfo label="About the address">
                      Every step resolves from this. {isDone("collect")
                        ? "Changing it means pulling the comps again."
                        : "Check it before the pull."}
                    </CmaInfo>
                  </div>
                  {!editAddr ? (
                    <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
                      <span style={{ flex: 1, minWidth: 0, fontSize: 14, fontWeight: 700, color: addr ? NAVY : "#b06a3a" }}>
                        {addr || "No address set yet"}
                      </span>
                      <button onClick={() => { setAddrDraft(addr); setEditAddr(true); }}
                        style={{ flex: "0 0 auto", background: "#fff", border: `1px solid ${LINE}`, borderRadius: 8, padding: "6px 12px", fontSize: 12.5, fontWeight: 700, color: MUTED, cursor: "pointer" }}>
                        {addr ? "Change" : "Add the address"}
                      </button>
                    </div>
                  ) : (
                    <CmaAddressField
                      dealId={dealId}
                      initial={addrDraft}
                      busy={busy === "addr"}
                      onSave={saveAddr}
                      onCancel={() => setEditAddr(false)}
                    />
                  )}

                  {addrErr && <div style={{ fontSize: 12, color: "#8B1A1A", marginTop: 6 }}>{addrErr}</div>}
                </div>
              )}

              {/* Confirm the property. Self-hides until the pull has produced
                  facts to confirm, so it never shows an empty form. */}
              {step.key === "property" && isDone("collect") && (
                <CmaSubjectFacts dealId={dealId} onChanged={() => { void load(); }} />
              )}

              {/* Her judgement on the finishes. With photos it adjusts the AI
                  scoring; without them it IS the comparison's other half. */}
              {step.key === "property" && isDone("collect") && (
                <CmaMyRead dealId={dealId} />
              )}

              {step.key === "comparables" && compsReady && (
                <CmaCompReview dealId={dealId} soldComps={comps.sold} activeComps={comps.active} yours={comps.subject} onToggle={toggleComp} />
              )}

              {/* WHERE THE COMPS COME FROM. She builds curated lists in Xposure
                  and asked to point the CMA at one instead of the tool's search. */}
              {step.key === "comparables" && compsReady && (
                <div style={{ marginTop: 14, border: `1px solid ${LINE}`, borderRadius: 10, padding: "12px 13px", background: "#fff" }}>
                  <div style={{ fontSize: 11, fontWeight: 800, color: MUTED, textTransform: "uppercase", letterSpacing: 0.4, marginBottom: 8, display: "flex", alignItems: "center", gap: 7 }}>
                    Comps from an Xposure saved list
                    <CmaInfo label="About saved lists">
                      Uses a list you built in Xposure instead of this tool's search.
                      Signs in and runs in the background. Checked comps are kept.
                    </CmaInfo>
                  </div>
                  <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                    <input value={savedList} onChange={(e) => setSavedList(e.target.value)}
                      placeholder="List name, exactly as in Xposure"
                      style={{ flex: 1, minWidth: isMobile ? "100%" : 240, boxSizing: "border-box", border: "1px solid #dde3ee", borderRadius: 8, padding: "10px 11px", fontSize: 14, color: NAVY, fontFamily: "inherit" }} />
                    <button onClick={pullSavedList} disabled={!savedList.trim() || !!busy}
                      style={{ minHeight: 44, background: (!savedList.trim() || busy) ? "#d7dce6" : NAVY, color: (!savedList.trim() || busy) ? "#8a93a6" : "#fff", border: "none", borderRadius: 8, padding: "10px 17px", fontSize: 14, fontWeight: 700, cursor: busy ? "wait" : "pointer" }}>
                      {busy === "savedlist" ? "Starting…" : "Pull list"}
                    </button>
                  </div>
                  {listState && listState.state !== "none" && (
                    <div style={{ marginTop: 9, fontSize: 13.5, lineHeight: 1.5,
                      color: listState.state === "failed" ? "#8B1A1A" : listState.state === "done" ? GREEN : MUTED }}>
                      {listState.state === "running" && "Signing into Xposure and reading the list…"}
                      {listState.state === "done" && `Pulled ${listState.solds ?? 0} sold and ${listState.actives ?? 0} active from that list.`}
                      {listState.state === "failed" && (listState.compsPulled
                        ? `Pulled ${listState.compsPulled} comps from that list, but the report did not render. ${listState.error || ""}`
                        : `That list did not pull. ${listState.error || ""}`)}
                    </div>
                  )}

                </div>
              )}

              {step.key === "comparables" && compsReady && (
                <div style={{ marginTop: 14, border: `1px solid ${LINE}`, borderRadius: 10, padding: "12px 13px", background: "#fbfcfe" }}>
                  <div style={{ fontSize: 11, fontWeight: 800, color: MUTED, textTransform: "uppercase", letterSpacing: 0.4, marginBottom: 8, display: "flex", alignItems: "center", gap: 7 }}>
                    Re-run the search
                    <CmaInfo label="About re-running the search">
                      Re-pulls from Xposure with your changes to areas and target
                      price, then re-runs the later steps.
                    </CmaInfo>
                  </div>
                  <textarea value={regen} onChange={(e) => setRegen(e.target.value)} rows={2}
                    placeholder="e.g. expand to Westsyde + Westmount + North Kamloops, target $635k, suite priority"
                    style={{ width: "100%", border: `1px solid #dde3ee`, borderRadius: 8, padding: "8px 10px", fontSize: 12.5, fontFamily: "inherit", color: "#1c2433", resize: "vertical" }} />
                  <div style={{ display: "flex", alignItems: "center", gap: 11, marginTop: 9 }}>
                    <button onClick={regenerate} disabled={!!busy}
                      style={{ fontSize: 12.5, fontWeight: 700, padding: "8px 16px", borderRadius: 9, border: "none", background: busy ? "#d7dce6" : TERRA, color: busy ? "#8a93a6" : "#fff", cursor: busy ? "wait" : "pointer" }}>
                      {busy === "regen" ? "Re-pulling…" : "Regenerate comps"}</button>

                  </div>
                </div>
              )}

              {step.key === "pricing" && pricing && (
                <div style={{ marginTop: 4 }}>
                  {/* The bracket her own positioning produces, and the price she
                      picks inside it. This replaced a "RECOMMENDED $X" band that
                      was derived from price per square foot, comp averaging and
                      score interpolation -- none of which she does. */}
                  <CmaBracket dealId={dealId} onRepriced={() => { void api.getCmaPricing(dealId).then(setPricing).catch(() => { /* ignore */ }); }} />
                  {!!pricing.recommendedPrice && <CmaPositioned
                    recommended={pricing.recommendedPrice}
                    range={pricing.range}
                    better={pricing.better}
                    comparable={pricing.comparable}
                    worse={pricing.worse}
                    expired={pricing.expired}
                    freshness={pricing.freshness}
                  />}
                  {!!pricing.recommendedPrice && pricing.strategy && (
                    <div style={{ border: `1px solid ${LINE}`, borderRadius: 10, padding: "11px 13px", marginBottom: 12, fontSize: 12.5, color: "#384256", lineHeight: 1.55 }}>{String(pricing.strategy)}</div>
                  )}
                  {/* Buyer demand sits beside the sandwich because it answers the
                      question the sandwich raises: what does moving the price
                      actually buy you. Self-contained and silent when the
                      prospecting capture has not run. */}
                  <div style={{ border: `1px solid ${LINE}`, borderRadius: 10, padding: "12px 14px", marginBottom: 12, background: "#fff" }}>
                    <CmaBuyerDemand dealId={dealId} />
                  </div>
{/* The old "Your take" price box lived here. It set the same number the
                      bracket above now sets, so keeping both put two price inputs on one
                      screen that could disagree. */}

                  <div style={{ marginTop: 12, border: `1px solid ${LINE}`, borderRadius: 10, padding: "12px 14px", background: "#fbfcfe" }}>
                    <div style={{ fontSize: 11, fontWeight: 800, color: MUTED, textTransform: "uppercase", letterSpacing: 0.4, marginBottom: 7 }}>Buyer-demand prospecting</div>
                    {byId("prospecting")?.status === "done" && !redoProspect ? (
                      <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
                        <span style={{ fontSize: 12.5, fontWeight: 700, color: GREEN }}>✓ Buyer demand captured. Ready to Generate.</span>
                        {/* Anchored on the wrong listing, or taken before the price
                            moved? This is the way back. It re-opens the picker; it
                            does not run anything on its own. */}
                        <button onClick={() => setRedoProspect(true)} disabled={!!busy}
                          style={{ minHeight: 44, font: "inherit", fontSize: 12.5, fontWeight: 700, color: BLUE,
                                   background: "none", border: "none", cursor: busy ? "default" : "pointer", padding: "10px 2px" }}>
                          Capture it again
                        </button>
                      </div>
                    ) : (byId("prospecting")?.status === "running" || busy === "prospect" || prospect.state === "running") ? (
                      <div style={{ fontSize: 12.5, color: TERRA, fontWeight: 700 }}>
                        Capturing from Xposure… one last login, about 1 to 2 minutes. You can keep working.
                        {prospect.message && (
                          <span style={{ display: "block", fontWeight: 400, color: MUTED, marginTop: 3 }}>{prospect.message}</span>
                        )}
                      </div>
                    ) : prospect.state === "failed" ? (
                      <div style={{ fontSize: 12.5, color: "#9B3B2E", lineHeight: 1.5 }}>
                        {prospect.message || "That capture did not finish."}
                        <button onClick={() => setProspect({ state: "idle" })}
                          style={{ marginLeft: 8, font: "inherit", fontSize: 12.5, fontWeight: 700, color: BLUE, background: "none", border: "none", cursor: "pointer", padding: 0 }}>
                          Pick another listing
                        </button>
                      </div>
                    ) : (
                      <>
                        <div style={{ fontSize: 12, color: "#384256", marginBottom: 7 }}>
                          {redoProspect
                            ? "Pick the listing to anchor the new pull. This replaces the buyer-demand numbers already in the report."
                            : "Pick the active listing to anchor the buyer-demand pull (one priced near your number reads cleanest):"}
                        </div>
                        <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
                          <select value={prospectMls} onChange={(e) => setProspectMls(e.target.value)}
                            style={{ flex: 1, minWidth: isMobile ? "100%" : 220, boxSizing: "border-box", border: "1px solid #dde3ee", borderRadius: 7, padding: isMobile ? "11px 10px" : "8px 10px", fontSize: isMobile ? 16 : 12.5, color: "#1c2433", background: "#fff" }}>
                            <option value="">Select an active comp…</option>
                            {comps.active.filter((c) => !c.excluded).map((c) => (
                              <option key={c.mls} value={c.mls}>{c.address} · {String(c.price)}</option>
                            ))}
                          </select>
                          <button onClick={captureProspecting} disabled={!!busy || !prospectMls || phases.some((p) => p.status === "running") || prospect.state === "running"}
                            style={{ fontSize: 12.5, fontWeight: 700, padding: "9px 16px", borderRadius: 9, border: "none", background: (busy || !prospectMls) ? "#d7dce6" : NAVY, color: (busy || !prospectMls) ? "#8a93a6" : "#fff", cursor: busy ? "wait" : "pointer" }}>
                            Capture buyer demand</button>
                          {/* The way back out. "Capture it again" throws away the
                              green tick on tap, and on a phone that row wraps, so
                              a stray thumb used to leave her with no way to say
                              never mind. */}
                          {redoProspect && byId("prospecting")?.status === "done" && (
                            <button onClick={() => { setRedoProspect(false); setProspectMls(""); }} disabled={!!busy}
                              style={{ minHeight: 44, font: "inherit", fontSize: 12.5, fontWeight: 700, color: MUTED,
                                       background: "none", border: "none", cursor: busy ? "default" : "pointer", padding: "10px 4px" }}>
                              Keep what I have
                            </button>
                          )}
                        </div>
                      </>
                    )}
                  </div>
                </div>
              )}
              {step.key === "pricing" && !pricing && stepDone(step) && (
                <div style={{ fontSize: 12.5, color: MUTED, marginTop: 8 }}>Loading pricing breakdown…</div>
              )}

              {/* The Report step is where she picks up the finished PDF, so it is
                  where the target design belongs: what the output is supposed to
                  look like, right next to the button that produces it. */}
              {/* GENERATE, said plainly and on the step it belongs to.
                  Rendering was only ever reachable through the generic "run the
                  next phase" button in the action row below, labelled with the
                  phase name, and it is hidden entirely while render is blocked --
                  so on the Report step there was no Generate button to find. */}
              {step.key === "report" && (() => {
                const rendered = isDone("render");
                const blocked = !(isDone("photos") && isDone("actives") && isDone("prospecting"));
                const missing = [
                  !isDone("prospecting") && "buyer demand",
                  !isDone("photos") && "the property assessment",
                  !isDone("actives") && "the comparables",
                ].filter(Boolean) as string[];
                return (
                  <div style={{ border: `1px solid ${LINE}`, borderRadius: 12, padding: "14px 16px", background: "#fff", marginBottom: 14 }}>
                    <div style={{ fontSize: 15, fontWeight: 700, color: NAVY, marginBottom: 4 }}>
                      {reportReady ? "The report passed its checks" : rendered ? "Report built; checks pending" : "Build the report"}
                    </div>
                    <p style={{ margin: "0 0 11px", fontSize: 13, color: MUTED, lineHeight: 1.5, maxWidth: "62ch" }}>
                      {rendered
                        ? "Every page below is the report as it would reach your sellers. Change anything on an earlier step and build it again."
                        : blocked
                        ? `Finish ${missing.join(" and ")} first, then this builds the PDF.`
                        : "Builds the PDF from your comps, your positioning and your notes, then runs the visual check."}
                    </p>
                    <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
                      <button onClick={() => run("render")} disabled={!!busy || blocked || phases.some((p) => p.status === "running") || prospect.state === "running"}
                        title={blocked ? `Finish ${missing.join(" and ")} first` : ""}
                        style={{ minHeight: 44, fontSize: 13.5, fontWeight: 800, padding: "11px 20px", borderRadius: 9,
                                 border: "none", font: "inherit",
                                 background: (busy || blocked) ? "#d7dce6" : TERRA,
                                 color: (busy || blocked) ? "#8a93a6" : "#fff",
                                 cursor: (busy || blocked) ? "default" : "pointer" }}>
                        {busy === "render" ? "Building…" : rendered ? "Build it again" : "Generate the report"}
                      </button>
                      {rendered && pdfUrl && (
                        <a href={pdfUrl} target="_blank" rel="noreferrer"
                           style={{ fontSize: 13, fontWeight: 700, color: BLUE, textDecoration: "none", padding: "11px 4px" }}>
                          Open the PDF ↗
                        </a>
                      )}
                      {reportReady && <CmaSendToSeller key={reportVersion} dealId={dealId} />}
                    </div>
                  </div>
                );
              })()}
              {step.key === "report" && <CmaReportBuild dealId={dealId} reportVersion={reportVersion} revision={revision} />}
              {step.key === "report" && <CmaApprovedDesign />}

              {/* failed phase error */}
              {step.phases.map(byId).filter((p) => p?.status === "failed").map((p) => (
                <div key={p!.id} style={{ fontSize: 11.5, color: "#d44", marginTop: 8 }}>{p!.label}: {(p!.error || "").slice(0, 110)}</div>
              ))}
              {runErr && <div style={{ fontSize: 11.5, color: "#d44", marginTop: 8 }}>{runErr.slice(0, 160)}</div>}

              {step.key === "property" && isDone("photos") && !editingPhotos && (
                <button type="button" onClick={() => setEditingPhotos(true)} disabled={!!busy || phases.some((p) => p.status === "running")}
                  style={{ minHeight: 44, padding: "10px 14px", border: `1px solid ${LINE}`, borderRadius: 8, background: "#fff", color: NAVY }}>
                  Update photos or assessment
                </button>
              )}

              {/* action row */}
              <div style={{ display: "flex", alignItems: "center", gap: 12, marginTop: 14 }}>
                {stepStatus(step) === "running"
                  ? <span style={{ fontSize: 12.5, fontWeight: 700, color: TERRA }}>running… {byId(step.phases.find((id) => byId(id)?.status === "running") || "")?.browser ? "(browser)" : ""}</span>
                  : stepDone(step)
                  ? <span style={{ fontSize: 13, fontWeight: 700, color: GREEN }}>✓ {step.label} complete</span>
                  : renderBlocked
                  ? <span style={{ fontSize: 12.5, color: MUTED }}>Capture <b style={{ color: NAVY }}>buyer demand</b> above first. Render CMA PDF unlocks once it lands.</span>
                  : nextRunnable
                  ? (() => {
                      // The pull resolves everything off the deal's address, so
                      // dispatching without one burns a browser run and fails.
                      const noAddr = nextRunnable.id === "collect" && !addr.trim();
                      const off = !!busy || noAddr;
                      return (
                        <>
                          <button onClick={() => run(nextRunnable.id)} disabled={off}
                            title={noAddr ? "Add the property address first" : ""}
                            style={{ fontSize: 13, fontWeight: 700, padding: "9px 18px", borderRadius: 9, border: "none", background: off ? "#d7dce6" : NAVY, color: off ? "#8a93a6" : "#fff", cursor: busy ? "wait" : off ? "default" : "pointer" }}>
                            {busy === nextRunnable.id ? "Running…"
                              : nextRunnable.id === "collect" ? "Pull the property information"
                              : `Run ${nextRunnable.label}`}</button>
                          {noAddr && <span style={{ fontSize: 12, color: MUTED }}>Add the address above first.</span>}
                        </>
                      );
                    })()
                  : blockingManual
                  ? <span style={{ fontSize: 12.5, color: MUTED }}><b style={{ color: NAVY }}>{blockingManual.label}</b>: capture via the CMA agent, then it advances</span>
                  : <span style={{ fontSize: 12.5, color: MUTED }}>Waiting on an earlier step.</span>}
                {step.key === "report" && pdfUrl && (
                  <a href={pdfUrl} target="_blank" rel="noreferrer" style={{ fontSize: 13, fontWeight: 700, color: BLUE, textDecoration: "none" }}>Open CMA PDF ↗</a>
                )}
                {step.key === "property" && isDone("collect") && (!isDone("photos") || editingPhotos) && stepStatus(step) !== "running" && !scoring && (
                  <div style={{ display: "flex", flexDirection: "column", gap: 8, marginBottom: 10, width: "100%" }}>
                    <label style={{ fontSize: 12, fontWeight: 700, color: NAVY }}>Subject photos</label>
                    <div style={{ display: "flex", gap: 8 }}>
                      <input value={photosUrl}
                        onChange={(e) => { setPhotosUrl(e.target.value); setPhotosSaved(false); setPhotosUrlSet(false); setNoPhotos(false); }}
                        placeholder="Paste the Google Drive folder link with the subject's photos…"
                        disabled={noPhotos}
                        style={{ flex: 1, fontSize: 13, padding: "8px 10px", borderRadius: 8, border: `1px solid ${photosAttached ? BLUE : LINE}`, color: NAVY, opacity: noPhotos ? 0.5 : 1 }} />
                      <button onClick={savePhotosUrl} disabled={!!busy || !photosUrl.trim() || noPhotos}
                        style={{ fontSize: 12.5, fontWeight: 700, padding: "8px 14px", borderRadius: 8, border: "none", background: photosAttached ? BLUE : (busy || !photosUrl.trim() || noPhotos) ? "#d7dce6" : NAVY, color: photosAttached ? "#fff" : (busy || !photosUrl.trim() || noPhotos) ? "#8a93a6" : "#fff", cursor: (busy || !photosUrl.trim() || noPhotos) ? "default" : "pointer", whiteSpace: "nowrap" }}>
                        {busy === "photos-url" ? "Saving…" : photosAttached ? "Attached ✓" : "Attach photos"}</button>
                    </div>
                    <div
                      onDragOver={(e) => { e.preventDefault(); }}
                      onDrop={(e) => { e.preventDefault(); void onDropFiles(e.dataTransfer?.files || null); }}
                      style={{ border: `1.5px dashed ${dropped ? BLUE : "#c2cddd"}`, borderRadius: 10, padding: "12px 14px", background: dropped ? "#f3f7ff" : "#fff", display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap", opacity: noPhotos ? 0.5 : 1 }}>
                      <label style={{ fontSize: 12.5, fontWeight: 700, color: NAVY, cursor: "pointer", border: `1px solid ${LINE}`, borderRadius: 8, padding: "6px 12px", background: "#fff" }}>
                        {isMobile ? "Take or choose photos" : "Choose photos"}
                        {/* On a phone this offers the camera, which is the
                            cheapest fix for the whole no-photos problem: she is
                            usually standing in the property when she needs it. */}
                        <input type="file" accept="image/*" multiple disabled={noPhotos || !!dropBusy}
                          onChange={(e) => { void onDropFiles(e.target.files); }}
                          style={{ display: "none" }} />
                      </label>
                      <span style={{ fontSize: 12, color: MUTED }}>
                        {dropBusy ? `Uploading ${dropBusy}…`
                          : dropped ? `${dropped} photo${dropped === 1 ? "" : "s"} ready. Continue will score these.`
                          : isMobile
                          ? "Kitchen, a bathroom, the living room and the front. Eight is plenty."
                          : "or drag them here. Use this instead of a Drive link when the photos are on your Mac."}
                      </span>
                      {dropErr && <span style={{ fontSize: 12, color: "#8B1A1A" }}>{dropErr}</span>}
                    </div>
                    <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
                      <button onClick={() => setNoPhotos((v) => !v)} disabled={!!busy}
                        title="No usable photos. Use confirmed facts and notes without unsupported finish comparisons"
                        style={{ fontSize: 12, fontWeight: 700, padding: "6px 12px", borderRadius: 8, border: `1px solid ${noPhotos ? NAVY : LINE}`, background: noPhotos ? NAVY : "#fff", color: noPhotos ? "#fff" : MUTED, cursor: busy ? "wait" : "pointer" }}>
                        {noPhotos ? "✓ No photos" : "No photos"}</button>
                      <span style={{ fontSize: 11, color: MUTED }}>
                        {noPhotos ? "Uses confirmed facts and notes. Unobserved finishes will not be compared."
                          : photosAttached ? "Continue will pull and score these photos."
                          : "Attach a photo folder, or choose No photos. Either lets you Continue."}</span>
                    </div>
                  </div>
                )}
                {step.key === "property" && scoring && stepStatus(step) !== "running" && (
                  <span style={{ fontSize: 12.5, fontWeight: 700, color: TERRA }}>scoring photos… runs in the background; Pricing unlocks when it lands.</span>
                )}
              </div>
            </div>

            {/* nav */}
            <div style={{ display: "flex", justifyContent: "space-between", marginTop: 14 }}>
              <button onClick={() => setViewIdx(Math.max(0, shown - 1))} disabled={shown === 0}
                style={{ fontSize: 13, fontWeight: 600, padding: "10px 16px", borderRadius: 9, border: `1px solid ${LINE}`, background: "#fff", color: shown === 0 ? "#c7cedb" : MUTED, cursor: shown === 0 ? "default" : "pointer" }}>← Back</button>
              {(() => {
                // Property is "decided" when the pull is done AND photos are attached or
                // explicitly declined. Continue then does the scoring/skipping.
                // A finished photos phase IS a decision. The gate used to ask only
                // whether a photo link was set in this browser session, so on any
                // property whose photos had already been scored the control was
                // hidden (correctly) and Continue was dead (incorrectly).
                const decided = step.key === "property"
                  ? (isDone("collect") && (isDone("photos") || photosDecided))
                  : step.key === "comparables"
                  ? (isDone("actives") || activesPresent)
                  : stepDone(step);
                const off = shown === STEPS.length - 1 || !decided || !!busy;
                return (
                  <button onClick={advance} disabled={off}
                    title={!decided
                      ? step.key === "property" ? "Attach photos or choose No photos"
                      : step.key === "comparables" ? "Pull the active competition first"
                      : "Finish this step first"
                      : ""}
                    style={{ fontSize: 13.5, fontWeight: 700, padding: "11px 20px", borderRadius: 9, border: "none", background: off ? "#d7dce6" : NAVY, color: off ? "#8a93a6" : "#fff", cursor: off ? "default" : "pointer" }}>
                    {busy === "continue" ? "Working…" : "Continue →"}</button>
                );
              })()}
            </div>
          </>)}
        </div>
  );

  // In `bare` mode the full-screen surface owns the header and the address, so
  // the collapsible section chrome would be a second, contradictory frame.
  if (bare) return <div style={{ padding: "4px 0 8px" }}>{body}</div>;

  return (
    <section style={{ border: `1px solid ${LINE}`, borderRadius: 12, marginTop: 14, overflow: "hidden", background: "#fff" }}>
      <header onClick={() => setOpen((o) => !o)} style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "13px 18px", background: NAVY, color: "#fff", cursor: "pointer" }}>
        <div style={{ fontWeight: 700, fontSize: 14 }}>CMA / Market Evaluation
          <span style={{ fontWeight: 400, fontSize: 12, color: "#b9c4dc", marginLeft: 8 }}>Step {Math.min(shown + 1, STEPS.length)} of {STEPS.length}</span>
        </div>
        <span style={{ fontSize: 12, color: "#b9c4dc" }}>{done}/{STEPS.length} · {open ? "▾" : "▸"}</span>
      </header>
      {open && <div style={{ padding: "16px 18px" }}>{body}</div>}
    </section>
  );
}

/* ─────────────────────────────────────────────────────────────────
   CmaSendToSeller — hands the finished report to the seller.

   It creates a Gmail DRAFT with the PDF attached and stops there. Skyleigh asked
   for a way to send from this screen; a draft is that way. This document carries
   the number a seller prices their home from, and every client-facing send in
   this system is approval-gated, so the last press belongs to her and happens in
   Gmail where she can see exactly what is going out.
   ───────────────────────────────────────────────────────────────── */
function CmaSendToSeller({ dealId }: { dealId: string }) {
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState<{ to?: string; subject?: string } | null>(null);
  const [err, setErr] = useState("");

  const go = async () => {
    setBusy(true); setErr("");
    try {
      const r = await api.draftCmaToSeller(dealId);
      if (r?.ok) setDone({ to: r.to, subject: r.subject });
      else setErr(r?.error || "Could not create the draft.");
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Could not create the draft.");
    } finally { setBusy(false); }
  };

  if (done) {
    return (
      <span style={{ fontSize: 12.5, color: GREEN, fontWeight: 700, lineHeight: 1.45 }}>
        ✓ Draft ready in Gmail for {done.to}
        <span style={{ display: "block", fontWeight: 400, color: MUTED }}>
          The report is attached. Read it over and send it from your Drafts.
        </span>
      </span>
    );
  }
  return (
    <>
      <button type="button" onClick={() => void go()} disabled={busy}
        style={{ minHeight: 44, fontSize: 13, fontWeight: 700, padding: "11px 18px", borderRadius: 9,
                 border: `1px solid #C7D6EC`, background: "transparent", color: BLUE, font: "inherit",
                 cursor: busy ? "default" : "pointer" }}>
        {busy ? "Drafting…" : "Email it to the seller"}
      </button>
      {err && <span style={{ fontSize: 12.5, color: "#9B3B2E" }}>{err}</span>}
    </>
  );
}
