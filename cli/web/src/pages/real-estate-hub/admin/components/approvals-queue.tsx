import { useCallback, useEffect, useState } from "react";
import { fetchJSON, api } from "@/lib/api";
import { ListChecks, FileText, CheckCheck, Eye } from "../icons";
import { DeskBar } from "./desk-bar";

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
};
type AResp = { ok: boolean; documents: AItem[]; gates: AItem[]; count: number };

/** Approvals queue — collapsible bar below Critical dates. Reuses the existing
 *  /api/admin/action-runs/{id}/approve handler; never a new approval path.
 *  Stays neutral with a blue count pill (sign-off pressure), never red. */
export default function ApprovalsQueue({ onOpenDeal }: { onOpenDeal: (dealId: string) => void }) {
  const [data, setData] = useState<AResp | null>(null);
  const [open, setOpen] = useState(false);
  const [sel, setSel] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [confirmKey, setConfirmKey] = useState<string | null>(null);

  const load = useCallback(() => {
    fetchJSON<AResp>("/api/admin/approvals-queue")
      .then((r) => setData(r))
      .catch(() => setData(null));
  }, []);
  useEffect(() => { load(); }, [load]);

  const docs = data?.documents ?? [];
  const gates = data?.gates ?? [];
  const all = [...docs, ...gates];
  const count = data?.count ?? 0;

  const toggle = (id: string) =>
    setSel((s) => { const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n; });

  const approve = useCallback(async (ids: string[]) => {
    if (!ids.length || busy) return;
    const outbound = all.filter((x) => ids.includes(x.runId) && x.outbound);
    const key = ids.join("|");
    if (outbound.length && confirmKey !== key) {
      setConfirmKey(key);
      setErr(`Click approve again to send ${outbound.length} client-facing item${outbound.length > 1 ? "s" : ""}.`);
      return;
    }
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
    setConfirmKey(null);
    if (failed) setErr(`${failed} item${failed > 1 ? "s" : ""} failed — left in the queue.`);
    load();
  }, [all, busy, confirmKey, load]);

  const pill = <span className="dsk-pill-count">{count} waiting</span>;
  const summary =
    count === 0 ? "Nothing waiting on you" : `${docs.length} documents · ${gates.length} stage gates`;

  const renderRow = (i: AItem) => (
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
        disabled={busy}
        onClick={() => approve([i.runId])}
      >
        {i.outbound ? "Approve & send" : "Approve"}
      </button>
    </div>
  );

  return (
    <DeskBar
      tone="info"
      leftIcon={<ListChecks />}
      label="Approvals"
      summary={summary}
      pill={count > 0 ? pill : undefined}
      expanded={open}
      onToggle={() => setOpen((o) => !o)}
    >
      {count === 0 ? (
        <div className="dsk-empty">Nothing waiting on you.</div>
      ) : (
        <>
          <div className="dsk-bulkbar">
            <label className="dsk-bulk-all">
              <input
                type="checkbox"
                className="dsk-check"
                checked={sel.size === all.length && all.length > 0}
                onChange={() =>
                  setSel((s) => (s.size === all.length ? new Set() : new Set(all.map((x) => x.runId))))
                }
              />
              Select all
            </label>
            {sel.size > 0 && (
              <div className="dsk-bulk-actions">
                <span className="dsk-bulk-n">{sel.size} selected</span>
                <button type="button" className="dsk-row-btn" disabled={busy} onClick={() => approve([...sel])}>
                  Approve {sel.size} selected
                </button>
              </div>
            )}
          </div>
          {err && <div className="dsk-err">{err}</div>}
          {docs.length > 0 && (
            <div className="dsk-group">
              <div className="dsk-group-head"><FileText /> Documents to send <span className="dsk-group-n">{docs.length}</span></div>
              {docs.map(renderRow)}
            </div>
          )}
          {gates.length > 0 && (
            <div className="dsk-group">
              <div className="dsk-group-head"><CheckCheck /> Stage gates <span className="dsk-group-n">{gates.length}</span></div>
              {gates.map(renderRow)}
            </div>
          )}
          <a className="dsk-footlink" href="#approvals" onClick={(e) => e.preventDefault()}>Open all approvals →</a>
        </>
      )}
    </DeskBar>
  );
}
