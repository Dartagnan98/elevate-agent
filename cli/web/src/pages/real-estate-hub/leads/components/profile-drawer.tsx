import { useEffect, useState } from "react";

import { ListSkeleton } from "@/components/ui/skeleton";
import { api } from "@/lib/api";
import type { ThreadContextResponse } from "@/lib/api-types";
import type { LeadsProfile } from "../leads-data";
import { StatusPill } from "./profiles-list";

export function ProfileDrawer({
  profile, onClose, onStatusChange,
}: {
  profile: LeadsProfile;
  onClose: () => void;
  onStatusChange?: (profile: LeadsProfile, value: string) => void;
}) {
  const handleStatusChange = (v: string) => {
    onStatusChange?.(profile, v);
  };
  useEffect(() => {
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => { document.body.style.overflow = prev; };
  }, []);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const [context, setContext] = useState<ThreadContextResponse | null>(null);
  const [loadingCtx, setLoadingCtx] = useState(false);
  const [ctxError, setCtxError] = useState<string | null>(null);
  const sourceId = profile.sourceId || "";
  const threadId = profile.threadId || "";
  useEffect(() => {
    if (!sourceId || !threadId) {
      setContext(null);
      return;
    }
    let cancelled = false;
    setLoadingCtx(true);
    setCtxError(null);
    api
      .getThreadContext(sourceId, threadId)
      .then((res: ThreadContextResponse) => {
        if (!cancelled) setContext(res);
      })
      .catch((err: { message?: string }) => {
        if (!cancelled) setCtxError(err?.message || "Failed to load thread");
      })
      .finally(() => {
        if (!cancelled) setLoadingCtx(false);
      });
    return () => {
      cancelled = true;
    };
  }, [sourceId, threadId]);

  if (!profile) return null;

  const heatTone = profile.heat >= 80 ? "hot" : profile.heat >= 50 ? "warm" : "cool";

  const fmtTime = (iso?: string | null) => {
    if (!iso) return "";
    const t = new Date(iso);
    if (!isFinite(t.getTime())) return "";
    return t.toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
  };

  const activity = (context?.activity || []).map((a) => ({
    id: a.id,
    kind: (a.type || "activity").replace(/_/g, " "),
    time: fmtTime(a.timestamp),
    title: a.title,
    summary: a.summary,
  }));

  const messages = (context?.messages || []).map((m) => ({
    id: m.id,
    direction: m.direction === "outbound" ? "out" : "in",
    from: m.direction === "outbound" ? "You" : (m.sender || profile.name),
    text: m.text || "",
    time: fmtTime(m.timestamp),
  }));

  const notes = context?.notes || [];
  const tasks = context?.tasks || [];

  const sendHistory = (context?.sends || []).map((h, idx) => ({
    id: h.id || String(idx),
    transport: (h.channel || "EMAIL").toUpperCase(),
    status: h.status || "sent",
    time: fmtTime(h.createdAt),
    text: (h.payload && (h.payload.text || h.payload.body)) || "",
  }));

  return (
    <div className="lb-drawer-backdrop" onClick={onClose}>
      <aside className="lb-drawer" role="dialog" aria-modal="true" aria-label={"Profile: " + profile.name} onClick={(e) => e.stopPropagation()}>
        <header className="lb-drawer-head">
          <div className="lb-drawer-head-title">
            <h2 className="lb-drawer-name">{profile.name}</h2>
            <div className="lb-drawer-tags">
              <span className="lb-drawer-source mono">{profile.source.toLowerCase().replace(" crm", "")}</span>
              <span className="lb-drawer-tag mono">Outreach</span>
              <span className="lb-drawer-msg-count mono">{messages.length} messages</span>
            </div>
          </div>
          <div className="lb-drawer-head-actions">
            <StatusPill status={profile.status} onChange={handleStatusChange} />
            <button type="button" className="lb-drawer-close" onClick={onClose} aria-label="Close">×</button>
          </div>
        </header>

        <div className="lb-drawer-body">
          <div className="lb-drawer-thread">
            {loadingCtx ? (
              <ListSkeleton rows={4} />
            ) : ctxError ? (
              <div className="lb-drawer-empty">{ctxError}</div>
            ) : messages.length === 0 ? (
              <div className="lb-drawer-empty">No messages on file yet.</div>
            ) : (
              messages.map(m => (
                <div key={m.id} className={"lb-drawer-msg " + m.direction}>
                  <div className="lb-drawer-msg-head mono">{m.from} · {m.time}</div>
                  <div className="lb-drawer-msg-text">{m.text}</div>
                </div>
              ))
            )}
          </div>

          <aside className="lb-drawer-side">
            <section className="lb-drawer-section">
              <div className="lb-drawer-section-label mono">Lead score</div>
              <div className={"lb-drawer-score " + heatTone}>
                <span className="lb-drawer-score-num">{profile.heat}</span>
                <span className="lb-drawer-score-label">{heatTone}</span>
              </div>
              <div className="lb-drawer-kv">
                <span className="lb-drawer-kv-label mono">Source</span>
                <span className="lb-drawer-kv-val">{profile.source}</span>
              </div>
              <div className="lb-drawer-kv">
                <span className="lb-drawer-kv-label mono">Owner</span>
                <span className="lb-drawer-kv-val">Demo Agent</span>
              </div>
              <div className="lb-drawer-pills">
                {profile.tags.map(t => (
                  <span key={t} className="lb-drawer-pill mono">{t.toLowerCase()}</span>
                ))}
              </div>
            </section>

            <section className="lb-drawer-section">
              <div className="lb-drawer-section-label mono">Contact</div>
              <div className="lb-drawer-contact">{profile.email}</div>
            </section>

            <section className="lb-drawer-section">
              <div className="lb-drawer-section-label mono">▤ Notes <span className="lb-drawer-section-count">{notes.length}</span></div>
              {notes.length === 0 ? (
                <div className="lb-drawer-empty-small">No notes yet.</div>
              ) : (
                <div className="lb-drawer-activity">
                  {notes.map(n => (
                    <div key={n.id} className="lb-drawer-activity-row" title={n.summary || n.title || ""}>
                      <span className="lb-drawer-activity-kind">{n.title || n.summary || "Note"}</span>
                      <span className="lb-drawer-activity-time mono">{fmtTime(n.timestamp)}</span>
                    </div>
                  ))}
                </div>
              )}
            </section>

            <section className="lb-drawer-section">
              <div className="lb-drawer-section-label mono">▦ Tasks <span className="lb-drawer-section-count">{tasks.length}</span></div>
              {tasks.length === 0 ? (
                <div className="lb-drawer-empty-small">No tasks.</div>
              ) : (
                <div className="lb-drawer-activity">
                  {tasks.map(t => (
                    <div key={t.id} className="lb-drawer-activity-row" title={t.summary || t.title || ""}>
                      <span className="lb-drawer-activity-kind">{t.title || "Task"}</span>
                      <span className="lb-drawer-activity-time mono">{fmtTime(t.dueAt || t.timestamp)}</span>
                    </div>
                  ))}
                </div>
              )}
            </section>

            <section className="lb-drawer-section">
              <div className="lb-drawer-section-label mono">∿ Property activity <span className="lb-drawer-section-count">{activity.length}</span></div>
              {activity.length === 0 ? (
                <div className="lb-drawer-empty-small">No activity recorded.</div>
              ) : (
                <div className="lb-drawer-activity">
                  {activity.map(a => (
                    <div key={a.id} className="lb-drawer-activity-row" title={a.summary || a.title || ""}>
                      <span className="lb-drawer-activity-kind mono">{a.kind}</span>
                      <span className="lb-drawer-activity-time mono">{a.time}</span>
                    </div>
                  ))}
                </div>
              )}
            </section>

            <section className="lb-drawer-section">
              <div className="lb-drawer-section-label mono">Send history <span className="lb-drawer-section-count">{sendHistory.length}</span></div>
              {sendHistory.length === 0 ? (
                <div className="lb-drawer-empty-small">No outbound sends yet.</div>
              ) : (
                sendHistory.map(h => (
                  <div key={h.id} className="lb-drawer-send">
                    <div className="lb-drawer-send-head">
                      <span className="lb-drawer-send-transport mono">{h.transport}</span>
                      <span className="lb-drawer-send-status mono">{h.status}</span>
                    </div>
                    <div className="lb-drawer-send-text">{h.text}</div>
                    <div className="lb-drawer-send-time mono">{h.time}</div>
                  </div>
                ))
              )}
            </section>
          </aside>
        </div>
      </aside>
    </div>
  );
}
