import { useCallback, useEffect, useRef, useState } from "react";
import { api, fetchJSON } from "@/lib/api";
import { OzzieLoader } from "./ozzie-loader";
import "./ozzie-chat-panel.css";

/**
 * "Ask Ozzie" — per-property chat panel that lives on a deal card.
 *
 * Phase 1: answers questions scoped to ONE deal via /api/admin/deals/{id}/chat
 * (which builds the property's context server-side). Collapsed it sits in the
 * card corner as Ozzie + a "Need to chat?" bubble; open it's a chat panel with
 * an Ozzie avatar beside every reply and his thinking loader while answering.
 * Skill-dispatch-by-voice is Phase 2 — this only answers.
 */

type OzzieAction = { key: string; skill: string; label: string };
type ChatMessage = {
  role: string;
  content: string;
  // When Ozzie proposes running a real workflow for this property, it rides on
  // the assistant message. It NEVER runs until the user taps Run (below), which
  // dispatches through the same task-run path the card buttons use.
  action?: OzzieAction;
  actionState?: "proposed" | "running" | "done" | "error" | "dismissed";
};

const QUICK_ACTIONS = [
  "What's pending?",
  "Price & deposit",
  "Key dates",
  "What's on file?",
];

const OZZIE_AVATAR = "/ozzie/ozzie-head.png";
const OZZIE_MASCOT = "/ozzie/ozzie-nobubble.png";

export default function OzzieChatPanel({
  dealId,
  address,
}: {
  dealId: string;
  address?: string;
}) {
  const [open, setOpen] = useState(false);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [loadedHistory, setLoadedHistory] = useState(false);
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const inputRef = useRef<HTMLTextAreaElement | null>(null);

  // Rehydrate the transcript the first time the panel is opened.
  useEffect(() => {
    if (!open || loadedHistory || !dealId) return;
    let cancelled = false;
    fetchJSON<{ ok: boolean; messages: ChatMessage[] }>(
      `/api/admin/deals/${dealId}/chat`,
    )
      .then((res) => {
        if (cancelled) return;
        setMessages(Array.isArray(res?.messages) ? res.messages : []);
      })
      .catch(() => {
        /* fresh transcript if history read fails */
      })
      .finally(() => {
        if (!cancelled) setLoadedHistory(true);
      });
    return () => {
      cancelled = true;
    };
  }, [open, loadedHistory, dealId]);

  // Keep the latest message in view.
  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages, sending, open]);

  useEffect(() => {
    if (open) inputRef.current?.focus();
  }, [open]);

  const send = useCallback(
    async (raw: string) => {
      const text = raw.trim();
      if (!text || sending || !dealId) return;
      setInput("");
      setMessages((prev) => [...prev, { role: "user", content: text }]);
      setSending(true);
      try {
        const res = await fetchJSON<{ ok: boolean; reply: string; proposedAction?: OzzieAction | null }>(
          `/api/admin/deals/${dealId}/chat`,
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ message: text }),
          },
        );
        const proposed = res?.proposedAction || undefined;
        setMessages((prev) => [
          ...prev,
          {
            role: "assistant",
            content: res?.reply || "I couldn't pull that up just now. Try again.",
            ...(proposed ? { action: proposed, actionState: "proposed" as const } : {}),
          },
        ]);
      } catch {
        setMessages((prev) => [
          ...prev,
          { role: "assistant", content: "Something glitched on my end. Give it another go." },
        ]);
      } finally {
        setSending(false);
      }
    },
    [dealId, sending],
  );

  // Dispatch a proposed action through the SAME path the card buttons use
  // (POST /api/admin/tasks/run). Nothing runs until the user taps Run here.
  const setActionState = (idx: number, state: NonNullable<ChatMessage["actionState"]>) =>
    setMessages((prev) => prev.map((m, j) => (j === idx ? { ...m, actionState: state } : m)));

  const runAction = useCallback(
    async (idx: number, action: OzzieAction) => {
      setActionState(idx, "running");
      try {
        await api.runAdminDealTask({ dealId, skill: action.skill, title: action.label, runNow: true });
        setActionState(idx, "done");
      } catch {
        setActionState(idx, "error");
      }
    },
    [dealId],
  );

  const actionCard = (m: ChatMessage, idx: number) => {
    if (!m.action || m.actionState === "dismissed") return null;
    const label = m.action.label;
    const wrap: React.CSSProperties = {
      marginTop: 6, border: "1px solid #dbe2ee", borderRadius: 10,
      background: "#f6f9fd", padding: "9px 11px", fontSize: 12.5, fontWeight: 600,
    };
    if (m.actionState === "running")
      return <div style={{ ...wrap, color: "#5a6478" }}>Starting {label}…</div>;
    if (m.actionState === "done")
      return <div style={{ ...wrap, color: "#2f7a4d", borderColor: "#bfe3ce", background: "#eef7f1" }}>✓ Started {label}. It'll show as a run on the card.</div>;
    if (m.actionState === "error")
      return <div style={{ ...wrap, color: "#C46340", borderColor: "#f0cdb6", background: "#fdf1e9" }}>Couldn't start {label}. Try the card button.</div>;
    // proposed
    return (
      <div style={{ ...wrap, display: "flex", alignItems: "center", gap: 8 }}>
        <button type="button" onClick={() => runAction(idx, m.action!)}
          style={{ background: "#182848", color: "#fff", border: "none", borderRadius: 7, padding: "7px 14px", fontSize: 12.5, fontWeight: 700, cursor: "pointer" }}>
          Run {label}
        </button>
        <button type="button" onClick={() => setActionState(idx, "dismissed")}
          style={{ background: "transparent", color: "#7b869c", border: "none", fontSize: 12.5, fontWeight: 600, cursor: "pointer" }}>
          Not now
        </button>
      </div>
    );
  };

  const onKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      send(input);
    }
  };

  if (!open) {
    return (
      <button
        type="button"
        className="ozc-trigger"
        aria-label="Ask Ozzie about this property"
        onClick={() => setOpen(true)}
      >
        <img className="ozc-trigger-avatar" src={OZZIE_AVATAR} alt="" />
        <span className="ozc-trigger-label">Ask Ozzie</span>
      </button>
    );
  }

  const showEmpty = loadedHistory && messages.length === 0;

  return (
    <div className="ozc-panel" role="dialog" aria-modal="false" aria-label="Ask Ozzie">
      <header className="ozc-head">
        <img className="ozc-head-avatar" src={OZZIE_AVATAR} alt="Ozzie" />
        <div className="ozc-head-text">
          <span className="ozc-head-title">Ask Ozzie</span>
          {address ? <span className="ozc-head-sub">{address}</span> : null}
        </div>
        <button
          type="button"
          className="ozc-head-close"
          aria-label="Minimize chat"
          onClick={() => setOpen(false)}
        >
          &times;
        </button>
      </header>

      <div className="ozc-body" ref={scrollRef}>
        {showEmpty && (
          <div className="ozc-empty">
            <img className="ozc-empty-mascot" src={OZZIE_MASCOT} alt="" />
            <p className="ozc-empty-text">
              Ask me anything about {address || "this property"}: what's
              pending, the numbers, dates, or what's on file. I can also run
              work on this property: a CMA, assessment and zoning, the listing
              kit, marketing, seller updates, offers, contracts, signing, subject
              removal, SkySlope, and closing. I'll show a Confirm button before
              anything runs.
            </p>
          </div>
        )}

        {messages.map((m, i) =>
          m.role === "user" ? (
            <div key={i} className="ozc-row ozc-row-user">
              <div className="ozc-bubble ozc-bubble-user">{m.content}</div>
            </div>
          ) : (
            <div key={i} className="ozc-row ozc-row-ozzie">
              <img className="ozc-reply-avatar" src={OZZIE_AVATAR} alt="Ozzie" />
              <div style={{ display: "flex", flexDirection: "column", minWidth: 0, maxWidth: "100%" }}>
                <div className="ozc-bubble ozc-bubble-ozzie">{m.content}</div>
                {actionCard(m, i)}
              </div>
            </div>
          ),
        )}

        {sending && (
          <div className="ozc-row ozc-row-ozzie">
            <div className="ozc-thinking">
              <OzzieLoader sequence="thinking" size={64} label="Ozzie is thinking" />
            </div>
          </div>
        )}
      </div>

      {(showEmpty || messages.length > 0) && (
        <div className="ozc-chips">
          {QUICK_ACTIONS.map((q) => (
            <button
              key={q}
              type="button"
              className="ozc-chip"
              disabled={sending}
              onClick={() => send(q)}
            >
              {q}
            </button>
          ))}
        </div>
      )}

      <div className="ozc-compose">
        <textarea
          ref={inputRef}
          className="ozc-input"
          rows={1}
          placeholder="Ask about this property…"
          value={input}
          disabled={sending}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={onKeyDown}
        />
        <button
          type="button"
          className="ozc-send"
          aria-label="Send"
          disabled={sending || !input.trim()}
          onClick={() => send(input)}
        >
          ↑
        </button>
      </div>
    </div>
  );
}
