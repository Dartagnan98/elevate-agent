import { useEffect, useRef, useState } from "react";
import type { LeadsDraft } from "../leads-data";
import { sameReviewedDraft, submitReviewedDrafts } from "../draft-selection";

export function BulkReplyReview({ drafts, currentDrafts, onApprove, onAccepted, onComplete, onClose }: {
  drafts: LeadsDraft[]; currentDrafts: LeadsDraft[];
  onApprove: (draft: LeadsDraft) => Promise<void>;
  onAccepted: (draft: LeadsDraft) => void;
  onComplete: () => Promise<void>;
  onClose: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const running = useRef(false);
  const latest = useRef(currentDrafts);
  latest.current = currentDrafts;
  const [busy, setBusy] = useState(false);
  const [accepted, setAccepted] = useState<string[]>([]);
  const [finished, setFinished] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const changed = drafts.some((d) => !accepted.includes(d.id) &&
    !currentDrafts.some((current) => sameReviewedDraft(d, current)));

  useEffect(() => {
    const el = dialog.current;
    const previous = document.activeElement as HTMLElement | null;
    const overflow = document.body.style.overflow;
    el?.showModal();
    document.body.style.overflow = "hidden";
    return () => { el?.close(); document.body.style.overflow = overflow; previous?.focus(); };
  }, []);

  async function approve() {
    if (running.current || finished || changed) return;
    running.current = true;
    setBusy(true);
    const result = await submitReviewedDrafts(drafts, async (d) => {
      if (!latest.current.some((current) => sameReviewedDraft(d, current))) {
        throw new Error(`${d.name}'s reply changed or is no longer awaiting approval. Close this review and refresh the list.`);
      }
      await onApprove(d);
    }, (d) => { setAccepted((ids) => [...ids, d.id]); onAccepted(d); });
    setError(result.error);
    setFinished(true);
    try { await onComplete(); }
    catch { setError((e) => e || "Approvals were submitted, but delivery status could not refresh. Check Sent and Didn't Send."); }
    setBusy(false);
    // This review can only submit once, including after an uncertain response.
  }

  return <dialog ref={dialog} className="leadsx-reply-review" aria-labelledby="reply-review-title"
    aria-describedby="reply-review-description" onCancel={(e) => { e.preventDefault(); if (!busy) onClose(); }}>
    <header>
      <h2 id="reply-review-title">{finished ? "Approval results" : `Review ${drafts.length} ${drafts.length === 1 ? "reply" : "replies"}`}</h2>
      <p id="reply-review-description">{finished
        ? `${accepted.length} of ${drafts.length} approved for sending. Check Sent for delivery confirmation.`
        : "Each person receives their own message below. Approve and send starts sending these replies now."}</p>
    </header>
    <div className="leadsx-review-messages">
      {drafts.map((d) => <section key={d.id} className="leadsx-review-message">
        <div className="leadsx-review-recipient"><h3>{d.name}</h3><span>{d.channel}</span>
          {accepted.includes(d.id) && <strong>✓ Approved for sending</strong>}</div>
        <p>{d.body}</p>
      </section>)}
    </div>
    <footer>
      <div role="status" aria-live="polite">
        {busy && <p>Approving replies… {accepted.length} of {drafts.length}</p>}
        {!busy && error && <p className="leadsx-review-error" role="alert">Stopped: {error} Remaining replies were not submitted. Check Sent and Didn't Send before retrying.</p>}
        {!finished && !busy && changed && <p role="alert">A reply changed or left approvals. Close this review and refresh before sending.</p>}
      </div>
      <div className="leadsx-review-actions">
        <button type="button" className="leadsx-review-cancel" autoFocus disabled={busy} onClick={onClose}>{finished ? "Done" : "Back to leads"}</button>
        {!finished && <button type="button" className="leadsx-review-send" disabled={busy || changed || !drafts.length} onClick={() => void approve()}>
          {busy ? "Approving…" : `Approve and send ${drafts.length} ${drafts.length === 1 ? "reply" : "replies"}`}
        </button>}
      </div>
    </footer>
  </dialog>;
}
