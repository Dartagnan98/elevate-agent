import { useState } from "react";
import { api } from "@/lib/api";
import "./deposit-card.css";

/**
 * Deposit as a first-class tracked object on a deal.
 *
 * BC workflow rule: a deal is accepted WITHOUT a deposit; the deposit becomes
 * due at/after subject removal, on a date set by the CPS (entered manually).
 * So "not_due" is the normal, calm state for a freshly accepted deal — never a
 * warning. Status: not_due (no due date) -> outstanding (due date set, awaiting
 * funds) -> received.
 *
 * Storage: sub-fields persist as deal toggles (extra_toggles_json) via the
 * existing toggle endpoint — depositAmount, depositDueDate, depositTerms,
 * depositHeldIn, depositMethod, depositStatus, depositReceivedDate — with a
 * read precedence of toggle override -> named deal column. The Critical dates
 * feed reads the same source, so this card is the single source of truth.
 */

export type DepositStatus = "not_due" | "outstanding" | "received";
export interface DepositInfo {
  amount: number | null;
  dueDate: string | null;
  terms: string;
  heldIn: string;
  method: string;
  receivedDate: string | null;
  status: DepositStatus;
}

type AnyObj = Record<string, unknown>;

function num(v: unknown): number | null {
  if (v == null || v === "") return null;
  const n = typeof v === "number" ? v : Number(String(v).replace(/[^\d.]/g, ""));
  return Number.isFinite(n) ? n : null;
}
function str(v: unknown): string {
  return v == null ? "" : String(v);
}

/** Single source of truth: toggle override first, then the named deal column. */
export function deriveDeposit(deal: AnyObj | null | undefined, toggles: AnyObj | null | undefined): DepositInfo {
  const d = deal ?? {};
  const t = toggles ?? {};
  const amount = num(t.depositAmount) ?? num(d.depositAmount);
  const dueDate = (str(t.depositDueDate) || str(d.depositDueDate)) || null;
  const receivedDate = str(t.depositReceivedDate) || null;
  const explicit = str(t.depositStatus).toLowerCase();
  let status: DepositStatus;
  if (receivedDate || explicit === "received" || str(d.depositInTrustAt)) status = "received";
  else if (dueDate) status = "outstanding";
  else status = "not_due";
  return {
    amount,
    dueDate,
    terms: str(t.depositTerms),
    heldIn: str(t.depositHeldIn),
    method: str(t.depositMethod),
    receivedDate,
    status,
  };
}

function fmtMoney(n: number | null): string {
  return n == null ? "" : "$" + Math.round(n).toLocaleString();
}
function fmtDate(s: string | null): string {
  if (!s) return "";
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(s);
  if (m) return new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]))
    .toLocaleDateString("en-CA", { month: "short", day: "numeric" });
  return s;
}
function daysUntil(s: string | null): number | null {
  if (!s) return null;
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(s);
  if (!m) return null;
  const due = new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]));
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  return Math.round((due.getTime() - today.getTime()) / 86400000);
}
function todayIso(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

export default function DepositCard({
  dealId,
  deal,
  toggles,
  currentStage = 0,
  subjectRemovalStage = 6,
  onUpdate,
}: {
  dealId: string;
  deal: AnyObj;
  toggles: AnyObj;
  currentStage?: number;
  subjectRemovalStage?: number;
  onUpdate?: () => void;
}) {
  const dep = deriveDeposit(deal, toggles);
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [confirmUndo, setConfirmUndo] = useState(false);
  const [form, setForm] = useState({
    amount: dep.amount != null ? String(dep.amount) : "",
    dueDate: dep.dueDate ?? "",
    terms: dep.terms,
    heldIn: dep.heldIn || "Brokerage trust",
    method: dep.method,
  });

  const save = async (extra?: Record<string, unknown>) => {
    setBusy(true);
    const writes: Record<string, unknown> = {
      depositAmount: form.amount.trim() || null,
      depositDueDate: form.dueDate.trim() || null,
      depositTerms: form.terms.trim() || null,
      depositHeldIn: form.heldIn.trim() || null,
      depositMethod: form.method.trim() || null,
      ...(extra ?? {}),
    };
    try {
      for (const [field, value] of Object.entries(writes)) {
        await api.setAdminDealToggle(dealId, field, value as never);
      }
    } catch { /* surfaced by reload */ }
    setBusy(false);
    setEditing(false);
    onUpdate?.();
  };

  const markReceived = async () => {
    if (dep.amount == null && !form.amount.trim()) {
      setNotice("Enter the deposit amount before marking it received.");
      setEditing(true);
      return;
    }
    setNotice(null);
    await save({ depositStatus: "received", depositReceivedDate: todayIso() });
  };

  const undoReceived = async () => {
    if (!confirmUndo) {
      setConfirmUndo(true);
      setNotice("Click Not received again to confirm.");
      return;
    }
    setBusy(true);
    try {
      await api.setAdminDealToggle(dealId, "depositStatus", "outstanding" as never);
      await api.setAdminDealToggle(dealId, "depositReceivedDate", null as never);
      setConfirmUndo(false);
      setNotice(null);
    } catch { /* */ }
    setBusy(false);
    onUpdate?.();
  };

  const days = daysUntil(dep.dueDate);
  const promptTerms = dep.status === "not_due" && currentStage >= subjectRemovalStage;

  const pill =
    dep.status === "received"
      ? <span className="dep-pill received">Received</span>
      : dep.status === "outstanding"
        ? <span className="dep-pill outstanding">Outstanding</span>
        : <span className="dep-pill notdue">Not due yet</span>;

  return (
    <section className="dep-card">
      <header className="dep-head">
        <span className="dep-title">Deposit</span>
        {pill}
        <div className="dep-head-actions">
          {dep.status !== "received" && !editing && (
            <button type="button" className="dep-btn" disabled={busy} onClick={markReceived}>Mark received</button>
          )}
          {!editing && (
            <button type="button" className="dep-btn ghost" onClick={() => setEditing(true)}>Edit</button>
          )}
        </div>
      </header>
      {notice && <p className="dep-prompt" role="alert">{notice}</p>}

      {editing ? (
        <div className="dep-form">
          <label className="dep-field"><span>Amount</span>
            <input value={form.amount} placeholder="$10,000"
              onChange={(e) => setForm({ ...form, amount: e.target.value })} /></label>
          <label className="dep-field"><span>Due date (from CPS)</span>
            <input value={form.dueDate} placeholder="YYYY-MM-DD"
              onChange={(e) => setForm({ ...form, dueDate: e.target.value })} /></label>
          <label className="dep-field"><span>Held in</span>
            <input value={form.heldIn} placeholder="Brokerage trust"
              onChange={(e) => setForm({ ...form, heldIn: e.target.value })} /></label>
          <label className="dep-field"><span>Method</span>
            <input value={form.method} placeholder="Bank draft / wire"
              onChange={(e) => setForm({ ...form, method: e.target.value })} /></label>
          <label className="dep-field full"><span>Deposit clause (from CPS)</span>
            <textarea value={form.terms} rows={2} placeholder="Paste the deposit clause from the Contract of Purchase and Sale…"
              onChange={(e) => setForm({ ...form, terms: e.target.value })} /></label>
          <div className="dep-form-actions">
            <button type="button" className="dep-btn ghost" disabled={busy} onClick={() => setEditing(false)}>Cancel</button>
            <button type="button" className="dep-btn" disabled={busy} onClick={() => save()}>Save</button>
          </div>
        </div>
      ) : dep.status === "not_due" ? (
        <div className="dep-body">
          <p className="dep-calm">Deposit due at subject removal. No date set yet — enter the CPS terms when subjects are being removed.</p>
          {promptTerms && <p className="dep-prompt">Subjects are at/near removal — add the deposit terms.</p>}
          <button type="button" className="dep-btn ghost" onClick={() => setEditing(true)}>Add deposit terms</button>
        </div>
      ) : (
        <div className="dep-body">
          <div className="dep-grid">
            <div><span className="dep-k">Amount</span><span className="dep-v">{dep.amount != null ? fmtMoney(dep.amount) : "Not set"}</span></div>
            {dep.status === "received"
              ? <div><span className="dep-k">Received</span><span className="dep-v">{fmtDate(dep.receivedDate)}</span></div>
              : <div><span className="dep-k">Due</span><span className="dep-v">{fmtDate(dep.dueDate)}
                  {days != null && (
                    <span className={"dep-count" + (days < 0 ? " late" : "")}>
                      {days < 0 ? ` ${-days} day${-days !== 1 ? "s" : ""} overdue` : days === 0 ? " due today" : ` in ${days} day${days !== 1 ? "s" : ""}`}
                    </span>
                  )}</span></div>}
            {dep.heldIn && <div><span className="dep-k">Held in</span><span className="dep-v">{dep.heldIn}</span></div>}
            {dep.method && <div><span className="dep-k">Method</span><span className="dep-v">{dep.method}</span></div>}
          </div>
          {dep.terms && <p className="dep-terms">{dep.terms}</p>}
          {dep.status === "received" && (
            <button type="button" className="dep-btn ghost dep-undo" disabled={busy} onClick={undoReceived}>Not received (undo)</button>
          )}
        </div>
      )}
    </section>
  );
}
