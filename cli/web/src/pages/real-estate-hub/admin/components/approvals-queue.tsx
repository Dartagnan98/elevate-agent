import { useConfirmation } from "@/hooks/useConfirmation";
import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useDeskResource } from "../use-desk-resource";
import { ListChecks, FileText, CheckCheck, Eye } from "../icons";
import { DeskBar } from "./desk-bar";
import WaitingCard from "./waiting-card";

type AItem = {
  runId: string;
  dealId: string;
  address: string;
  side: string;
  title: string;
  message: string;
  hasPreview: boolean;
  outbound: boolean;
  createdAt: string;
  humanPrompt?: Record<string, unknown>;
};
type AResp = { ok: boolean; documents: AItem[]; gates: AItem[]; count: number };
const individualReview = (item: AItem) => !!(item.humanPrompt?.documentReview || item.humanPrompt?.titleOrder || item.humanPrompt?.titleVerification);

/** Approvals queue — collapsible bar below Critical dates. Reuses the existing
 *  /api/admin/action-runs/{id}/approve handler; never a new approval path.
 *  Stays neutral with a blue count pill (sign-off pressure), never red. */
export default function ApprovalsQueue({ onOpenDeal, refreshKey, onChanged }: { onOpenDeal: (dealId: string) => void; refreshKey?: unknown; onChanged?: () => void | Promise<void> }) {
  const { confirm: confirmAction, dialog: confirmationDialog } = useConfirmation();
  const { data, loading, error, load } = useDeskResource<AResp>("/api/admin/approvals-queue", refreshKey);
  const [open, setOpen] = useState(false);
  const [sel, setSel] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    if (!data) return;
    const available = new Set([...data.documents, ...data.gates].filter(item => !individualReview(item)).map(item => item.runId));
    setSel(previous => new Set([...previous].filter(id => available.has(id))));
  }, [data]);

  const docs = data?.documents ?? [];
  const gates = data?.gates ?? [];
  const all = [...docs, ...gates];
  const selectable = all.filter(item => !individualReview(item));
  const count = data?.count ?? 0;

  const toggle = (id: string) =>
    setSel((s) => { const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n; });

  const approve = useCallback(async (ids: string[]) => {
    if (!ids.length || busy || loading || error) return;
    ids = ids.filter(id => all.some(item => item.runId === id && !individualReview(item)));
    if (!ids.length) return;
    const outbound = all.filter((x) => ids.includes(x.runId) && x.outbound);
    const msg = outbound.length
      ? `Approve ${ids.length} item${ids.length > 1 ? "s" : ""}? ${outbound.length} of these will SEND to a client. Continue?`
      : `Approve ${ids.length} item${ids.length > 1 ? "s" : ""}?`;
    if (!(await confirmAction(msg))) return;
    setBusy(true); setErr(null);
    let failed = 0;
    for (const id of ids) {
      try {
        await api.approveAdminActionRun(id, { approved: true, runNow: true });
      } catch {
        failed += 1;
      }
    }
    setBusy(false);
    setSel(new Set());
    if (failed) setErr(`${failed} item${failed > 1 ? "s" : ""} failed — left in the queue.`);
    void load();
    void onChanged?.();
  }, [all, busy, loading, error, load, onChanged]);

  const pill = <span className="dsk-pill-count">{count} waiting</span>;
  const summary = error ? "Could not refresh approvals — retry below" : !data ? "Loading approvals…" :
    count === 0 ? "Nothing waiting on you" : `${docs.length} documents · ${gates.length} stage gates`;

  const renderRow = (i: AItem) => individualReview(i) ? (
    <div key={i.runId} className="dsk-group">
      <div className="dsk-row-addr">{i.address}</div>
      <WaitingCard run={{ runId: i.runId, dealId: i.dealId, humanPrompt: i.humanPrompt || {} }} onResolved={() => { void load(); void onChanged?.(); }} />
      <button type="button" className="dsk-row-btn ghost" onClick={() => onOpenDeal(i.dealId)}><Eye /> Open listing scorecard</button>
    </div>
  ) : (
    <div key={i.runId} className="dsk-row dsk-row-approve">
      <input
        type="checkbox"
        className="dsk-check"
        aria-label={`Select ${i.title}`}
        checked={sel.has(i.runId)}
        onChange={() => toggle(i.runId)}
      />
      <span className="dsk-row-main">
        <span className="dsk-row-addr" title={`${i.title} — ${i.address}`}>
          {i.title}<span className="dsk-row-dim"> — {i.address}</span>
        </span>
        <span className="dsk-row-sub">
          {i.side}{i.message ? ` · ${i.message}` : ""}
        </span>
      </span>
      <button type="button" className="dsk-row-btn ghost" onClick={() => onOpenDeal(i.dealId)}>
        <Eye /> {i.hasPreview ? "Preview" : "Review"}
      </button>
      <button
        type="button"
        className="dsk-row-btn"
        disabled={busy || loading || !!error}
        onClick={() => approve([i.runId])}
      >
        {i.outbound ? "Approve & send" : "Approve"}
      </button>
    </div>
  );

  return <>{confirmationDialog}{(
    <DeskBar
      tone="info"
      leftIcon={<ListChecks />}
      label="Approvals"
      summary={summary}
      pill={count > 0 ? pill : undefined}
      expanded={open}
      onToggle={() => setOpen((o) => !o)}
    >
      {error && <div className="dsk-err" role="alert">Approvals could not refresh. {data ? "Showing the last available queue; refresh before approving." : "Your approval queue has not been checked."} <button type="button" className="dsk-row-btn" disabled={loading} onClick={() => void load()}>{loading ? "Retrying…" : "Retry"}</button></div>}
      {err && <div className="dsk-err" role="alert">{err}</div>}
      {!data ? <div className="dsk-empty" role="status">{loading ? "Loading approvals…" : "Approval information is unavailable."}</div> : count === 0 ? (
        <div className="dsk-empty">Nothing waiting on you.</div>
      ) : (
        <>
          {selectable.length > 0 && <div className="dsk-bulkbar">
            <label className="dsk-bulk-all">
              <input
                type="checkbox"
                className="dsk-check"
                checked={sel.size === selectable.length && selectable.length > 0}
                onChange={() =>
                  setSel((s) => (s.size === selectable.length ? new Set() : new Set(selectable.map((x) => x.runId))))
                }
              />
              Select all
            </label>
            {sel.size > 0 && (
              <div className="dsk-bulk-actions">
                <span className="dsk-bulk-n">{sel.size} selected</span>
                <button type="button" className="dsk-row-btn" disabled={busy || loading || !!error} onClick={() => approve([...sel])}>
                  Approve {sel.size} selected
                </button>
              </div>
            )}
          </div>}
          {docs.length > 0 && (
            <div className="dsk-group">
              <div className="dsk-group-head"><FileText /> Document approvals <span className="dsk-group-n">{docs.length}</span></div>
              {docs.map(renderRow)}
            </div>
          )}
          {gates.length > 0 && (
            <div className="dsk-group">
              <div className="dsk-group-head"><CheckCheck /> Stage gates <span className="dsk-group-n">{gates.length}</span></div>
              {gates.map(renderRow)}
            </div>
          )}

        </>
      )}
    </DeskBar>
  )}</>;
}
