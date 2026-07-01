import { useCallback, useEffect, useRef, useState } from "react";
import { fetchJSON } from "@/lib/api";
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

type ChatMessage = { role: string; content: string };

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
        const res = await fetchJSON<{ ok: boolean; reply: string }>(
          `/api/admin/deals/${dealId}/chat`,
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ message: text }),
          },
        );
        setMessages((prev) => [
          ...prev,
          { role: "assistant", content: res?.reply || "I couldn't pull that up just now. Try again." },
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
              Ask me anything about {address || "this property"} — what's
              pending, the numbers, dates, or what's on file.
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
              <div className="ozc-bubble ozc-bubble-ozzie">{m.content}</div>
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
