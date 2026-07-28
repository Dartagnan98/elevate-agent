import { useCallback, useState } from "react";
import { api } from "@/lib/api";

/** Normalized shape a WAITING ON YOU / ACTION NEEDED card needs. Both the deal
 *  scorecard (from ctx.priorRuns) and the global ActionNeededPopup (from
 *  /api/admin/approvals-queue) map their rows into this. */
export type WaitingRunLike = {
  runId: string;
  dealId: string;
  humanPrompt: Record<string, unknown>;
  skill?: string;
  registryName?: string;
};

type ParsedField = { label: string; help: string; type: "text" | "select" | "textarea"; options: string[] };

const PHOTOS_FIELD_LABEL = "Property photos (Google Drive link)";

/** A bare requiredField that is really "approve / confirm / authorize …" with
 *  nothing to type. Rendered as a text box it becomes a dead-end (a Submit
 *  button that stays disabled until you type into an approval box) — the bug
 *  that stranded the 125 Corry price amendment. We detect these and turn the
 *  card back into a one-click Approve. Genuine decisions (a select with real
 *  options, e.g. "General vs Trust release") are NOT acks and are kept. */
function isApprovalAck(label: string): boolean {
  return (
    /^\s*(approve|confirm|authori[sz]e|ok to|okay to|proceed|sign[\s-]?off|send)\b/i.test(label) ||
    /\bdigisign send\b/i.test(label) ||
    /\bapprove\b.*\bsend\b/i.test(label)
  );
}

function parseFields(hp: Record<string, unknown>): ParsedField[] {
  const raw = Array.isArray(hp.requiredFields) ? (hp.requiredFields as unknown[]) : [];
  return raw
    .map((f): ParsedField => {
      if (f && typeof f === "object") {
        const o = f as Record<string, unknown>;
        return {
          label: String(o.label ?? o.name ?? o.key ?? ""),
          help: o.help ? String(o.help) : "",
          type: o.type === "select" ? "select" : o.type === "textarea" ? "textarea" : "text",
          options: Array.isArray(o.options) ? (o.options as unknown[]).map(String) : [],
        };
      }
      return { label: String(f), help: "", type: "text", options: [] };
    })
    .filter((f) => f.label);
}

/** Open a run's drafted PDF in the OS browser (desktop-shell windows have no PDF
 *  plugin; auth rides on ?token= which the backend whitelists for this read). */
function openRunPdf(dealId: string, runId: string) {
  const token =
    (window as unknown as { __ELEVATE_SESSION_TOKEN__?: string }).__ELEVATE_SESSION_TOKEN__ || "";
  const origin = window.location.origin;
  const externalOrigin = origin.includes("127.0.0.1")
    ? origin.replace("127.0.0.1", "localhost")
    : origin.replace("localhost", "127.0.0.1");
  const url = `${externalOrigin}/api/deals/${dealId}/run-draft-pdf/${runId}?token=${encodeURIComponent(token)}`;
  window.open(url, "_blank", "noopener,noreferrer");
}

/** One WAITING ON YOU / ACTION NEEDED item. Self-contained: renders fill-in
 *  fields + Preview / Submit / Approve / Dismiss and calls the action-run API
 *  directly, so it works identically inside the deal scorecard and inside the
 *  global popup. `onResolved` lets the caller refresh its own list. */
export default function WaitingCard({
  run,
  compact,
  onResolved,
}: {
  run: WaitingRunLike;
  compact?: boolean;
  onResolved?: () => void;
}) {
  const hp = run.humanPrompt || {};
  const title = String(hp.title ?? run.registryName ?? "Needs your input");
  const message = hp.message ? String(hp.message) : "";

  const parsed = parseFields(hp);
  // Strip plain-text approval acknowledgements so they never render as a
  // dead-end form. What's left are fields that actually need data typed in.
  const realFields = parsed.filter(
    (f) => !(f.type === "text" && f.options.length === 0 && isApprovalAck(f.label)),
  );

  // Photos-link guarantee for CMA / listing / marketing cards only (never on
  // pre-cma / seller-package / offers / closing). Based on the real fields so an
  // approval-only card never grows a photo box.
  const photoCtxId = (String(run.skill ?? "") + " " + String(run.registryName ?? "")).toLowerCase();
  const photoRelevant =
    !/pre-cma|seller-package/.test(photoCtxId) && /cma|listing|marketing|photo/.test(photoCtxId);
  const formFields =
    realFields.length > 0 &&
    photoRelevant &&
    !realFields.some((f) => /photo/i.test(f.label) || /drive/i.test(f.label))
      ? [
          ...realFields,
          {
            label: PHOTOS_FIELD_LABEL,
            help: "Paste a Google Drive or Dropbox link to the property photos so the CMA can pull from them. Optional.",
            type: "text" as const,
            options: [] as string[],
          },
        ]
      : realFields;

  const hasDraftPdf =
    (typeof hp.previewPdf === "string" && (hp.previewPdf as string).trim() !== "") ||
    (typeof hp.preview_pdf === "string" && String(hp.preview_pdf).trim() !== "");

  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState<"" | "submit" | "approve" | "dismiss">("");
  const [err, setErr] = useState<string | null>(null);

  const finish = useCallback(() => {
    // Best-effort: clear any matching surface-approval so it stops nagging.
    (async () => {
      try {
        const { approvals } = await api.getSurfaceApprovals("pending");
        const matches = (approvals || []).filter((a) => (a.description || "").includes(run.dealId));
        for (const a of matches) await api.resolveSurfaceApproval(a.id, "approve", "Cleared via action popup");
      } catch {
        /* surface-approvals absent — ignore */
      }
    })();
    window.dispatchEvent(new CustomEvent("elevate:action-resolved"));
    onResolved?.();
  }, [run.dealId, onResolved]);

  const submit = useCallback(async () => {
    const entered: Record<string, string> = {};
    for (const f of formFields) {
      const v = (answers[f.label] || "").trim();
      if (v) entered[f.label] = v;
    }
    if (Object.keys(entered).length === 0) return;
    setBusy("submit");
    setErr(null);
    try {
      await api.answerAdminActionRun(run.runId, { answers: entered, runNow: true });
      finish();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy("");
    }
  }, [answers, formFields, run.runId, finish]);

  const decide = useCallback(
    async (approved: boolean) => {
      setBusy(approved ? "approve" : "dismiss");
      setErr(null);
      try {
        await api.approveAdminActionRun(run.runId, { approved, runNow: approved });
        finish();
      } catch (e) {
        setErr(e instanceof Error ? e.message : String(e));
      } finally {
        setBusy("");
      }
    },
    [run.runId, finish],
  );

  return (
    <div className={"abm-waiting-item" + (compact ? " abm-waiting-item-compact" : "")}>
      <div className="abm-waiting-title">{title}</div>
      {message && <div className="abm-waiting-msg">{message}</div>}
      {formFields.length > 0 && (
        <div className="abm-waiting-form">
          <div className="abm-waiting-needs mono">FILL IN TO CONTINUE</div>
          {formFields.map((f, i) => {
            const setVal = (v: string) => setAnswers((prev) => ({ ...prev, [f.label]: v }));
            return (
              <label className="abm-waiting-field" key={i}>
                <span className="abm-waiting-field-label">{f.label}</span>
                {f.help && <span className="abm-waiting-field-help">{f.help}</span>}
                {f.type === "select" && f.options.length > 0 ? (
                  <select
                    className="abm-waiting-input"
                    value={answers[f.label] ?? ""}
                    disabled={busy === "submit"}
                    onChange={(e) => setVal(e.target.value)}
                  >
                    <option value="" disabled>
                      Choose…
                    </option>
                    {f.options.map((opt, j) => (
                      <option key={j} value={opt}>
                        {opt}
                      </option>
                    ))}
                  </select>
                ) : f.type === "textarea" ? (
                  <textarea
                    className="abm-waiting-input abm-waiting-textarea"
                    rows={3}
                    value={answers[f.label] ?? ""}
                    placeholder={`Type ${f.label}…`}
                    disabled={busy === "submit"}
                    onChange={(e) => setVal(e.target.value)}
                  />
                ) : (
                  <input
                    type="text"
                    className="abm-waiting-input"
                    value={answers[f.label] ?? ""}
                    placeholder={`Type ${f.label}…`}
                    disabled={busy === "submit"}
                    onChange={(e) => setVal(e.target.value)}
                  />
                )}
              </label>
            );
          })}
        </div>
      )}
      {err && <div className="abm-waiting-err">{err}</div>}
      <div className="abm-waiting-actions">
        {hasDraftPdf && (
          <button
            type="button"
            className="abm-waiting-btn preview"
            onClick={() => openRunPdf(run.dealId, run.runId)}
            title="Open the drafted PDF before you approve"
          >
            Preview PDF ↗
          </button>
        )}
        {formFields.length > 0 ? (
          <button
            type="button"
            className="abm-waiting-btn submit"
            disabled={busy === "submit" || !Object.values(answers).some((v) => v.trim())}
            onClick={submit}
            title="Send your answers and continue the skill"
          >
            {busy === "submit" ? "Sending…" : "Submit & run"}
          </button>
        ) : (
          <button
            type="button"
            className="abm-waiting-btn approve"
            disabled={busy === "approve"}
            onClick={() => decide(true)}
          >
            {busy === "approve" ? "Working…" : "Approve & re-run"}
          </button>
        )}
        <button
          type="button"
          className="abm-waiting-btn dismiss"
          disabled={busy === "dismiss"}
          onClick={() => decide(false)}
        >
          {busy === "dismiss" ? "…" : "Dismiss"}
        </button>
      </div>
    </div>
  );
}
