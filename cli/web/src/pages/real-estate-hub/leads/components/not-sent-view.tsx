// "Didn't Send" tab — surfaces send_queue rows that did NOT get delivered
// (failed / skipped / stuck), so an approved or queued message that silently
// dropped (e.g. a contact with no phone) doesn't just vanish off the board.
// Each row shows who, the message, the reason, and a Retry that re-resolves
// the contact's current phone and re-queues it.
import { useEffect, useState } from "react";
import { api } from "../../../../lib/api";
import type { SourceInboxSentItem } from "../../../../lib/api-types";

type Row = SourceInboxSentItem & { payload?: AnyObj };
type AnyObj = Record<string, unknown>;

const NAVY = "#182848", MUTED = "#7b869c", LINE = "#e3e7ef", RED = "#c0392b", AMBER = "#b0894d", GREEN = "#2f7a4d";

const rcpt = (r: Row): string => {
  const rec = (r.payload?.recipient as AnyObj) || {};
  return (rec.person_name as string) || (rec.name as string) || (r.payload?.person_name as string) || "Unknown lead";
};
const body = (r: Row): string =>
  ((r.payload?.draft_text as string) || (r.payload?.body as string) || (r.payload?.text as string) || "").toString();
const why = (r: Row): string => {
  if (r.lastError) return String(r.lastError);
  const st = (r.status || "").toLowerCase();
  if (st === "skipped") return "Skipped — no phone on the contact, or held for review / safety hold";
  if (st === "failed") return "Failed to send";
  if (st === "retrying") return "Still retrying";
  return "Did not send";
};

export function NotSentView() {
  const [rows, setRows] = useState<Row[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string>("");
  const [done, setDone] = useState<Record<string, string>>({});

  const load = () =>
    api.getSourceInboxNotSent(100)
      .then((r) => setRows((((r as unknown as { items?: Row[] }).items) || [])))
      .catch(() => setRows([]))
      .finally(() => setLoading(false));
  useEffect(() => { void load(); }, []);

  const retry = async (id: string) => {
    setBusy(id);
    try {
      const r = await api.retrySourceInboxSend(id);
      setDone((d) => ({ ...d, [id]: r.phone ? `Re-queued → ${r.phone}` : "Re-queued" }));
    } catch {
      setDone((d) => ({ ...d, [id]: "Retry failed" }));
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
            Approved or queued messages that didn't actually go out — so nothing drops silently.
            Most are a missing phone on the contact; Retry re-resolves the number and re-queues it.
          </p>
        </div>
        <button className="lb-btn" onClick={() => { setLoading(true); void load(); }} disabled={loading}>
          {loading ? "Refreshing…" : "Refresh"}
        </button>
      </header>

      {loading && <div style={{ padding: 18, color: MUTED, fontSize: 13 }}>Loading…</div>}
      {!loading && rows.length === 0 && (
        <div style={{ padding: "22px 18px", color: GREEN, fontSize: 13.5, fontWeight: 600 }}>
          ✓ Nothing stuck — every recent message went out.
        </div>
      )}

      <div>
        {rows.map((r) => {
          const st = (r.status || "").toLowerCase();
          const color = st === "failed" ? RED : AMBER;
          return (
            <div key={r.id} style={{ display: "flex", alignItems: "flex-start", gap: 14, padding: "13px 16px", borderTop: `1px solid ${LINE}` }}>
              <span style={{ fontSize: 10.5, fontWeight: 800, color: "#fff", background: color, borderRadius: 6, padding: "3px 8px", marginTop: 2, whiteSpace: "nowrap" }}>
                {(r.status || "?").toUpperCase()}
              </span>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ display: "flex", gap: 10, alignItems: "baseline" }}>
                  <span style={{ fontWeight: 700, fontSize: 13.5, color: NAVY }}>{rcpt(r)}</span>
                  <span style={{ fontSize: 11, color: MUTED }}>{(r.channel || "").toUpperCase()}{r.attempts ? ` · ${r.attempts} tries` : ""}</span>
                </div>
                <div style={{ fontSize: 12.5, color: "#384256", marginTop: 3, maxHeight: 36, overflow: "hidden" }}>
                  {body(r) || <em style={{ color: MUTED }}>(no message body saved)</em>}
                </div>
                <div style={{ fontSize: 11.5, color, marginTop: 4, fontWeight: 600 }}>⚠ {why(r)}</div>
              </div>
              <div style={{ flexShrink: 0 }}>
                {done[r.id]
                  ? <span style={{ fontSize: 12, fontWeight: 700, color: done[r.id].includes("failed") ? RED : GREEN }}>{done[r.id]}</span>
                  : <button className="lb-btn" onClick={() => retry(r.id)} disabled={!!busy}>{busy === r.id ? "Retrying…" : "Retry"}</button>}
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}
