import { useState } from "react";

import type { LeadsSentMessage } from "../leads-data";
import { SentMessageRow } from "./sent-message-row";

export function SentView({
  messages,
  onRefresh,
  loading = false,
  error = null,
  partial = false,
  limit = 100,
}: {
  messages: LeadsSentMessage[];
  // Refetch sent messages. includePending=true asks the gateway for queued /
  // retrying / failed rows too. Returns once the parent has the new list.
  onRefresh?: (includePending: boolean) => Promise<void>;
  loading?: boolean;
  error?: string | null;
  partial?: boolean;
  limit?: number;
}) {
  const [includeQueued, setIncludeQueued] = useState(false);
  const [busy, setBusy] = useState(false);
  const [refreshError, setRefreshError] = useState<string | null>(null);

  const refresh = async (includePending: boolean): Promise<boolean> => {
    if (!onRefresh) return false;
    setBusy(true);
    setRefreshError(null);
    try {
      await onRefresh(includePending);
      return true;
    } catch (nextError) {
      setRefreshError(nextError instanceof Error ? nextError.message : "Outbound history did not load.");
      return false;
    } finally {
      setBusy(false);
    }
  };

  const toggleQueued = (next: boolean) => {
    setIncludeQueued(next);
    void refresh(next);
  };

  const visible = onRefresh || includeQueued
    ? messages
    : messages.filter(m => m.status === "dispatch accepted" || m.status === "simulated — not sent");
  const visibleError = error || refreshError;
  const unavailable = Boolean(visibleError);

  return (
    <section className="ab-card lb-sent">
      <header className="lb-sent-head">
        <div>
          <h2 className="lb-profiles-title">Outbound history</h2>
          <p className="lb-profiles-desc">
            Recent outbound queue history, read from the latest {limit.toLocaleString()} records.
          </p>
        </div>
        <div className="lb-sent-controls">
          <span className="lb-sent-count mono">{partial ? `${visible.length}+` : visible.length} messages loaded</span>
          <label className="lb-sent-toggle">
            <input
              className="sr-only"
              type="checkbox"
              checked={includeQueued}
              disabled={busy || loading || !onRefresh}
              onChange={(event) => toggleQueued(event.target.checked)}
            />
            <span className={"lb-checkbox" + (includeQueued ? " checked" : "")} aria-hidden="true">
              {includeQueued && <span className="lb-check">✓</span>}
            </span>
            <span>Include queued / retrying / failed</span>
          </label>
          <button type="button" className="lb-btn ghost sm" disabled={busy || loading || !onRefresh} onClick={() => void refresh(includeQueued)}>
            {busy || loading ? "Refreshing…" : "Refresh"}
          </button>
        </div>
      </header>

      {loading && <div className="lb-replies-empty" role="status">Loading outbound history…</div>}
      {!loading && unavailable && (
        <div className="lb-replies-empty lb-crm-error" role="alert">
          Outbound history is unavailable. {visibleError}
        </div>
      )}
      {!loading && !unavailable && partial && (
        <div className="lb-history-coverage" role="note">
          Showing at least the latest {limit.toLocaleString()} queue records. Older messages may not be included.
        </div>
      )}
      {!loading && !unavailable && visible.length === 0 && (
        <div className="lb-replies-empty" role="status">
          No {includeQueued ? "outbound queue" : "dispatch-accepted"} records were returned in this recent window.
        </div>
      )}

      {!loading && !unavailable && visible.length > 0 && <div className="lb-sent-table">
        <div className="lb-sent-row lb-sent-header-row">
          <span className="lb-sent-h mono">When</span>
          <span className="lb-sent-h mono">Recipient</span>
          <span className="lb-sent-h mono">Source · Transport</span>
          <span className="lb-sent-h mono">Message</span>
          <span className="lb-sent-h mono">Status</span>
        </div>
        {visible.map(m => <SentMessageRow key={m.id} message={m} />)}
      </div>}
    </section>
  );
}
