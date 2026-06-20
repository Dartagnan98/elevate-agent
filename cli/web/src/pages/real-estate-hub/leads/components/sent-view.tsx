import { useState } from "react";

import type { LeadsSentMessage } from "../leads-data";

export function SentView({
  messages, onRefresh,
}: {
  messages: LeadsSentMessage[];
  // Refetch sent messages. includePending=true asks the gateway for queued /
  // retrying / failed rows too. Returns once the parent has the new list.
  onRefresh?: (includePending: boolean) => Promise<void>;
}) {
  const [includeQueued, setIncludeQueued] = useState(false);
  const [busy, setBusy] = useState(false);

  const refresh = async (includePending: boolean) => {
    if (!onRefresh) return;
    setBusy(true);
    try {
      await onRefresh(includePending);
    } finally {
      setBusy(false);
    }
  };

  const toggleQueued = () => {
    const next = !includeQueued;
    setIncludeQueued(next);
    // Refetch with the new flag so the list reflects the toggle. If the parent
    // didn't pass onRefresh (static demo data) we fall back to client-side
    // filtering below.
    void refresh(next);
  };

  // Client-side fallback filter for when no refetch is wired: hide non-sent rows
  // unless "include queued" is on.
  const visible = onRefresh || includeQueued ? messages : messages.filter(m => m.status === "sent");

  return (
    <section className="ab-card lb-sent">
      <header className="lb-sent-head">
        <div>
          <h2 className="lb-profiles-title">Sent messages</h2>
          <p className="lb-profiles-desc">
            Outbound history. Every message you approved on the Action Board lands here.
          </p>
        </div>
        <div className="lb-sent-controls">
          <span className="lb-sent-count mono">{visible.length} messages</span>
          <label className="lb-sent-toggle">
            <span className={"lb-checkbox" + (includeQueued ? " checked" : "")} onClick={toggleQueued}>
              {includeQueued && <span className="lb-check">✓</span>}
            </span>
            <span>Include queued / retrying / failed</span>
          </label>
          <button type="button" className="lb-btn ghost sm" disabled={busy || !onRefresh} onClick={() => void refresh(includeQueued)}>
            {busy ? "…" : "Refresh"}
          </button>
        </div>
      </header>

      <div className="lb-sent-table">
        <div className="lb-sent-row lb-sent-header-row">
          <span className="lb-sent-h mono">When</span>
          <span className="lb-sent-h mono">Recipient</span>
          <span className="lb-sent-h mono">Source · Transport</span>
          <span className="lb-sent-h mono">Message</span>
          <span className="lb-sent-h mono">Status</span>
        </div>
        {visible.map(m => (
          <div key={m.id} className="lb-sent-row">
            <span className="lb-sent-when mono">{m.when}</span>
            <span className="lb-sent-recipient">{m.recipient}</span>
            <span className="lb-sent-source">
              <div>{m.source}</div>
              <div className="lb-sent-transport mono">{m.transport}</div>
            </span>
            <span className="lb-sent-msg">
              <div>{m.message}</div>
              <div className="lb-sent-msg-id mono">id: {m.msgId}</div>
            </span>
            <span className={"lb-sent-status " + (m.status === "sent" ? "sent" : m.status === "failed" ? "failed" : "queued")}>{(m.status || "sent").toUpperCase()}</span>
          </div>
        ))}
      </div>
    </section>
  );
}
