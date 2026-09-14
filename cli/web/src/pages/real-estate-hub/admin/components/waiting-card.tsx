import { useCallback, useState } from "react";
import { Link } from "react-router-dom";
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

type ParsedField = { label: string; help: string; type: "text" | "select" | "textarea" | "date"; options: string[]; optional: boolean; defaultValue: string };

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

function parseFields(hp: Record<string, unknown>, optional = false): ParsedField[] {
  const fields = optional ? hp.optionalFields : hp.requiredFields;
  const raw = Array.isArray(fields) ? fields : [];
  return raw
    .map((f): ParsedField => {
      if (f && typeof f === "object") {
        const o = f as Record<string, unknown>;
        return {
          label: String(o.label ?? o.name ?? o.key ?? ""),
          help: o.help ? String(o.help) : "",
          type: o.type === "select" ? "select" : o.type === "textarea" ? "textarea" : o.type === "date" ? "date" : "text",
          options: Array.isArray(o.options) ? (o.options as unknown[]).map(String) : [],
          optional: optional || o.required === false,
          defaultValue: typeof o.defaultValue === "string" ? o.defaultValue : "",
        };
      }
      return { label: String(f), help: "", type: "text", options: [], optional, defaultValue: "" };
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

export function openListingKitPdf(dealId: string, docId: string) {
  const token = (window as unknown as { __ELEVATE_SESSION_TOKEN__?: string }).__ELEVATE_SESSION_TOKEN__ || "";
  const origin = window.location.origin.replace("127.0.0.1", "localhost");
  window.open(`${origin}/api/admin/deals/${encodeURIComponent(dealId)}/listing-kit-doc/${encodeURIComponent(docId)}?token=${encodeURIComponent(token)}`, "_blank", "noopener,noreferrer");
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
  const review = hp.reviewPackage as { mode?: string; artifacts?: { path: string; name: string }[]; actions?: { id: string; label: string; details: string; schedule?: string[]; destinations?: string[] }[]; notes?: string[] } | undefined;
  const publishReview = review?.mode === "publish";
  const titleOrder = hp.titleOrder as { versionHash?: string } | undefined;
  const documentReview = hp.documentReview as { kit?: string; documents?: { id: string; name: string }[] } | undefined;
  const listingDocuments = documentReview?.kit === "listing" && Array.isArray(documentReview.documents)
    ? documentReview.documents.filter(d => typeof d.id === "string" && typeof d.name === "string") : [];


  const parsed = [...parseFields(hp), ...parseFields(hp, true)];
  // Strip plain-text approval acknowledgements so they never render as a
  // dead-end form. What's left are fields that actually need data typed in.
  const formFields = parsed.filter(
    (f) => !(f.type === "text" && f.options.length === 0 && isApprovalAck(f.label)),
  );

  // The workflow owns its inputs. Never infer extra questions from its name.

  const hasDraftPdf =
    (typeof hp.previewPdf === "string" && (hp.previewPdf as string).trim() !== "") ||
    (typeof hp.preview_pdf === "string" && String(hp.preview_pdf).trim() !== "");

  const [edits, setAnswers] = useState<Record<string, string>>({});
  const provided = hp.providedAnswers && typeof hp.providedAnswers === "object"
    ? hp.providedAnswers as Record<string, unknown> : {};
  const answers = Object.fromEntries(formFields.map((f) => [
    f.label, edits[f.label] ?? (typeof provided[f.label] === "string" ? provided[f.label] as string : f.defaultValue),
  ]));
  const [busy, setBusy] = useState<"" | "submit" | "approve" | "dismiss">("");
  const [err, setErr] = useState<string | null>(null);

  const finish = useCallback(() => {
    window.dispatchEvent(new CustomEvent("elevate:action-resolved"));
    onResolved?.();
  }, [onResolved]);

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
      await api.answerAdminActionRun(run.runId, {
        answers: entered,
        runNow: true,
        ...(titleOrder?.versionHash ? { expectedTitleOrderHash: titleOrder.versionHash } : {}),
      });
      finish();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy("");
    }
  }, [answers, formFields, run.runId, finish, titleOrder]);

  const decide = useCallback(
    async (approved: boolean) => {
      setBusy(approved ? "approve" : "dismiss");
      setErr(null);
      try {
        await api.approveAdminActionRun(run.runId, { approved, runNow: approved,
          ...(titleOrder ? {expectedTitleOrderHash: titleOrder.versionHash} : {}) });
        finish();
      } catch (e) {
        setErr(e instanceof Error ? e.message : String(e));
      } finally {
        setBusy("");
      }
    },
    [run.runId, finish, titleOrder?.versionHash],
  );

  return (
    <div className={"abm-waiting-item" + (compact ? " abm-waiting-item-compact" : "")}>
      <div className="abm-waiting-title">{title}</div>
      {message && <div className="abm-waiting-msg">{message}</div>}
      {typeof hp.approvalBlockedReason === "string" && <p role="status" className="abm-waiting-msg">{hp.approvalBlockedReason}</p>}
      {listingDocuments.length > 0 && (
        <div className="abm-waiting-actions" aria-label="Listing documents to review">
          {listingDocuments.map(doc => (
            <button type="button" className="abm-waiting-btn preview" key={doc.id}
              onClick={() => openListingKitPdf(run.dealId, doc.id)}>Open {doc.name} ↗</button>
          ))}
        </div>
      )}
      {review && (
        <div className="my-3 space-y-3">
          <div className="flex flex-wrap gap-2">
            {(review.artifacts || []).map(asset => (
              <Link className="abm-waiting-btn preview" key={asset.path}
                onClick={() => window.dispatchEvent(new CustomEvent("elevate:review-open"))}
                to={`/chat?resume=${encodeURIComponent(String(hp.sessionId || ""))}&artifact=${encodeURIComponent(asset.path)}`}>
                Preview {asset.name}
              </Link>
            ))}
          </div>
          {(review.actions || []).map(action => (
            <div key={action.id}><strong>{action.label}</strong><div>{action.details}</div>
              {action.schedule?.map(time => <div key={time}>{time}</div>)}
              {action.destinations?.map(destination => <div key={destination}>{destination}</div>)}
            </div>
          ))}
          {(review.notes || []).map(note => <p key={note}>{note}</p>)}
          {publishReview && <p>Approval applies to this version and only the actions listed above.</p>}
        </div>
      )}
      {formFields.length > 0 && (
        <div className="abm-waiting-form">
          <div className="abm-waiting-needs mono">ADD MISSING DETAILS</div>
          {formFields.map((f, i) => {
            const setVal = (v: string) => setAnswers((prev) => ({ ...prev, [f.label]: v }));
            return (
              <label className="abm-waiting-field" key={i}>
                <span className="abm-waiting-field-label">{f.label}{f.optional ? " (optional)" : ""}</span>
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
                    rows={f.defaultValue.length > 100 ? 6 : 3}
                    value={answers[f.label] ?? ""}
                    placeholder={`Type ${f.label}…`}
                    disabled={busy === "submit"}
                    onChange={(e) => setVal(e.target.value)}
                  />
                ) : (
                  <input
                    type={f.type === "date" ? "date" : "text"}
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
            disabled={!!busy || !Object.values(answers).some((v) => v.trim())}
            onClick={submit}
            title="Send your answers and continue the skill"
          >
            {busy === "submit" ? "Sending…" : review ? "Prepare final approval" : "Submit & run"}
          </button>
        ) : (
          <button
            type="button"
            className="abm-waiting-btn approve"
            disabled={!!busy || !!hp.approvalBlockedReason || (publishReview && !review?.actions?.length)}
            onClick={() => decide(true)}
          >
            {busy === "approve" ? "Working…" : publishReview ? "Approve listed actions" : review ? "Continue review" : typeof hp.actionLabel === "string" ? hp.actionLabel : "Approve & re-run"}
          </button>
        )}
        <button
          type="button"
          className="abm-waiting-btn dismiss"
          disabled={!!busy}
          onClick={() => decide(false)}
        >
          {busy === "dismiss" ? "…" : String(hp.dismissLabel || "Dismiss")}
        </button>
      </div>
    </div>
  );
}
