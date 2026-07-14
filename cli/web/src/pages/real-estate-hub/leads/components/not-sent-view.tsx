// "Didn't Send" tab — surfaces send_queue rows that did NOT get delivered
// (failed / stuck retry), so an approved or queued message that silently
// dropped (e.g. a contact with no phone) doesn't just vanish off the board.
// Each row shows who, the message, the reason, and a Retry that re-resolves
// the contact's current phone and re-queues it.
import { useCallback, useEffect, useState } from "react";
import { api } from "../../../../lib/api";
import type { SourceInboxSentItem, SourceInboxSentResponse } from "../../../../lib/api-types";
import { retrySendOutcomeLabel } from "../draft-send-lifecycle";

type Row = SourceInboxSentItem & { payload?: AnyObj };
type AnyObj = Record<string, unknown>;

const rcpt = (r: Row): string => {
  const rec = (r.payload?.recipient as AnyObj) || {};
  return (rec.person_name as string) || (rec.name as string) || (r.payload?.person_name as string) || "Unknown lead";
};
const body = (r: Row): string =>
  ((r.payload?.draft_text as string) || (r.payload?.body as string) || (r.payload?.text as string) || "").toString();
const why = (r: Row): string => {
  if (r.lastError) return String(r.lastError);
  const st = (r.status || "").toLowerCase();
  if (st === "failed") return "Failed to send";
  if (st === "retrying") return "Automatic retry pending";
  return "Did not send";
};

export function NotSentView() {
  const [rows, setRows] = useState<Row[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [partial, setPartial] = useState(false);
  const [busy, setBusy] = useState<string>("");
  const [done, setDone] = useState<Record<string, string>>({});

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    setDone({});
    try {
      const response = await api.getSourceInboxNotSent(100) as SourceInboxSentResponse;
      const items = (response.items ?? []) as Row[];
      const effectiveLimit = Math.max(1, Math.min(Number(response.limit) || 100, 100));
      setRows(items);
      setPartial(items.length >= effectiveLimit);
    } catch (nextError) {
      setRows(null);
      setPartial(false);
      setError(nextError instanceof Error ? nextError.message : "Didn't-send history did not load.");
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => {
    const initialLoad = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(initialLoad);
  }, [load]);

  const retry = async (id: string) => {
    setBusy(id);
    setDone((current) => {
      const next = { ...current };
      delete next[id];
      return next;
    });
    try {
      const r = await api.retrySourceInboxSend(id);
      const outcome = retrySendOutcomeLabel(r);
      setDone((d) => ({ ...d, [id]: outcome }));
    } catch (nextError) {
      setDone((d) => ({
        ...d,
        [id]: nextError instanceof Error ? `Retry failed — ${nextError.message}` : "Retry failed",
      }));
    } finally {
      setBusy("");
    }
  };

  return (
    <section className="ab-card lb-sent">
      <header className="lb-sent-head">
        <div>
          <h2 className="lb-profiles-title">Didn't send</h2>
          <p className="lb-profiles-desc">
            Failed or automatically retrying messages returned from the latest 100 queue records.
            Retry is available only after a send reaches a failed state; it re-resolves the current number and dispatches only that selected record.
          </p>
        </div>
        <button className="lb-btn" onClick={() => { setLoading(true); void load(); }} disabled={loading}>
          {loading ? "Refreshing…" : "Refresh"}
        </button>
      </header>

      {loading && <div className="lb-replies-empty" role="status">Loading didn't-send history…</div>}
      {!loading && error && (
        <div className="lb-replies-empty lb-crm-error" role="alert">
          Didn't-send history is unavailable. {error}
        </div>
      )}
      {!loading && !error && partial && (
        <div className="lb-history-coverage" role="note">
          Showing at least 100 affected queue records. Older failures may not be included.
        </div>
      )}
      {!loading && !error && rows?.length === 0 && (
        <div className="lb-replies-empty" role="status">
          No failed or retrying messages were returned in this recent queue window.
        </div>
      )}

      {!loading && !error && rows && rows.length > 0 && <div className="lb-not-sent-list">
        {rows.map((r) => {
          const st = (r.status || "").toLowerCase();
          return (
            <div key={r.id} className="lb-not-sent-row">
              <span className={`lb-not-sent-status ${st === "failed" ? "failed" : "pending"}`}>
                {(r.status || "?").toUpperCase()}
              </span>
              <div className="lb-not-sent-copy">
                <div className="lb-not-sent-meta">
                  <strong>{rcpt(r)}</strong>
                  <span>{(r.channel || "").toUpperCase()}{r.attempts ? ` · ${r.attempts} tries` : ""}</span>
                </div>
                <div className="lb-not-sent-body">
                  {body(r) || <em>(no message body saved)</em>}
                </div>
                <div className={`lb-not-sent-reason ${st === "failed" ? "failed" : "pending"}`}>⚠ {why(r)}</div>
              </div>
              <div className="lb-not-sent-action">
                {done[r.id] && (
                  <span className={done[r.id].toLowerCase().includes("failed") ? "is-error" : done[r.id] === "Dispatch accepted" ? "is-success" : ""}>
                    {done[r.id]}
                  </span>
                )}
                {st === "retrying"
                  ? <span>Automatic retry pending</span>
                  : (!done[r.id] || done[r.id].toLowerCase().includes("failed")) && (
                    <button type="button" className="lb-btn" onClick={() => void retry(r.id)} disabled={!!busy}>
                      {busy === r.id ? "Retrying…" : "Retry"}
                    </button>
                  )}
              </div>
            </div>
          );
        })}
      </div>}
    </section>
  );
}
