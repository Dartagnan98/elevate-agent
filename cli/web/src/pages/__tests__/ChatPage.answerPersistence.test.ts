import { describe, expect, it } from "vitest";

import { __chatPageTestables } from "../ChatPage";
import source from "../ChatPage.tsx?raw";

const { completedAnswerLost } = __chatPageTestables;

type Msg = { id: string; role: "user" | "assistant"; content: string; status?: string };

const LONG_ANSWER =
  "Here is the full assistant answer that the smoke prompt produced. " +
  "It is comfortably longer than eighty non-whitespace characters so the " +
  "vanish observer treats it as a real rendered answer worth protecting.";

// Faithful re-creation of the legacy setMessages wrapper's two guards
// (empty-wipe + the new silent partial-drop guard) around the REAL
// completedAnswerLost export. `commit` returns what would actually land in
// React state given a proposed `next`.
function commit(prev: Msg[], next: Msg[], wipeAllowed: boolean): Msg[] {
  if (prev.length >= 1 && next.length === 0 && !wipeAllowed) return prev;
  if (!wipeAllowed && completedAnswerLost(prev as never, next as never)) return prev;
  return next;
}

// The blankTrace observer at ChatPage.tsx:5109, extracted verbatim in intent:
// fires when a prev assistant (>80 non-space chars) loses its content
// fingerprint AND its id is gone or its content shrank past half.
function observerWouldFire(prev: Msg[], now: Msg[]): boolean {
  const cfp = (m: Msg) =>
    `${m.role}:${(m.content ?? "").replace(/\s+/g, " ").trim().slice(0, 160)}`;
  const nowContent = new Set(now.map(cfp));
  const nowById = new Map(now.map((m) => [m.id, m] as const));
  for (const pm of prev) {
    if (pm.role !== "assistant") continue;
    const prevLen = (pm.content ?? "").replace(/\s+/g, "").length;
    if (prevLen <= 80) continue;
    if (nowContent.has(cfp(pm))) continue;
    const nowMsg = nowById.get(pm.id);
    const nowLen = nowMsg ? (nowMsg.content ?? "").replace(/\s+/g, "").length : -1;
    if (nowLen === -1 || nowLen < prevLen * 0.5) return true;
  }
  return false;
}

describe("completedAnswerLost — the silent partial-drop predicate", () => {
  it("flags evicting a completed >80-char assistant answer", () => {
    const prev: Msg[] = [
      { id: "u1", role: "user", content: "hi" },
      { id: "a1", role: "assistant", content: LONG_ANSWER, status: "complete" },
    ];
    expect(completedAnswerLost(prev as never, [prev[0]] as never)).toBe(true);
  });

  it("does not flag an id remap that preserves the content (resume re-key)", () => {
    const prev: Msg[] = [
      { id: "u1", role: "user", content: "hi" },
      { id: "stored-1", role: "assistant", content: LONG_ANSWER, status: "complete" },
    ];
    const next: Msg[] = [
      { id: "u1", role: "user", content: "hi" },
      { id: "server-1", role: "assistant", content: LONG_ANSWER, status: "complete" },
    ];
    expect(completedAnswerLost(prev as never, next as never)).toBe(false);
  });

  it("does not flag a still-growing streamed answer", () => {
    const prev: Msg[] = [
      { id: "a1", role: "assistant", content: LONG_ANSWER, status: "streaming" },
    ];
    const next: Msg[] = [
      { id: "a1", role: "assistant", content: LONG_ANSWER + " and even more text", status: "streaming" },
    ];
    expect(completedAnswerLost(prev as never, next as never)).toBe(false);
  });

  it("ignores short placeholder stubs (< 80 chars), so stub cleanup is allowed", () => {
    const prev: Msg[] = [
      { id: "u1", role: "user", content: "hi" },
      { id: "stub", role: "assistant", content: "Compacting…", status: "streaming" },
    ];
    expect(completedAnswerLost(prev as never, [prev[0]] as never)).toBe(false);
  });

  it("exempts a still-streaming placeholder even when it is long (manual-compaction cancel)", () => {
    // cancelManualCompactAssistant removes the streaming compaction row by id;
    // that row can carry a long partial. status==="streaming" keeps it exempt
    // so the legitimate removal is not silently blocked.
    const prev: Msg[] = [
      { id: "u1", role: "user", content: "compact this" },
      { id: "compact", role: "assistant", content: LONG_ANSWER, status: "streaming" },
    ];
    expect(completedAnswerLost(prev as never, [prev[0]] as never)).toBe(false);
  });
});

describe("release-smoke repro: session -> prompt -> complete -> close -> resume", () => {
  // Mirrors installed_runtime_smoke.py --live-candidate: the exact sequence
  // whose blankTrace("rendered assistant answer vanished from list") the
  // release live-smoke flagged. The terminal assistant must stay in the
  // rendered list THROUGHOUT and the observer must NEVER fire.
  it("keeps the terminal assistant across a buggy resume merge, silently", () => {
    const fires: string[] = [];
    let rendered: Msg[] = [];

    const step = (next: Msg[], wipeAllowed = false) => {
      const committed = commit(rendered, next, wipeAllowed);
      if (observerWouldFire(rendered, committed)) fires.push("vanished");
      rendered = committed;
    };

    // 1. prompt: user row appears
    step([{ id: "u1", role: "user", content: "run the smoke prompt" }]);
    // 2. stream: assistant grows
    step([
      { id: "u1", role: "user", content: "run the smoke prompt" },
      { id: "a1", role: "assistant", content: LONG_ANSWER.slice(0, 90), status: "streaming" },
    ]);
    // 3. message.complete: final answer
    step([
      { id: "u1", role: "user", content: "run the smoke prompt" },
      { id: "a1", role: "assistant", content: LONG_ANSWER, status: "complete" },
    ]);
    expect(rendered).toHaveLength(2);

    // 4. CLOSE the sidecar → 5. session.resume. The resume merge transiently
    // proposes a SHORTER list (cache lag drops the just-completed answer) —
    // exactly the transition that tripped the smoke. It must be blocked
    // silently so the terminal answer never leaves the screen.
    step([{ id: "u1", role: "user", content: "run the smoke prompt" }]);
    // 6. correct hydrate re-commits the full transcript (server ids)
    step([
      { id: "u1", role: "user", content: "run the smoke prompt" },
      { id: "srv-a1", role: "assistant", content: LONG_ANSWER, status: "complete" },
    ]);

    // The observer NEVER fired, and the completed answer is still on screen.
    expect(fires).toEqual([]);
    expect(rendered.some((m) => m.role === "assistant" && m.content === LONG_ANSWER)).toBe(true);
  });

  it("CONTROL: without the guard the same resume drop DOES trip the observer", () => {
    const withComplete: Msg[] = [
      { id: "u1", role: "user", content: "run the smoke prompt" },
      { id: "a1", role: "assistant", content: LONG_ANSWER, status: "complete" },
    ];
    const buggyResume: Msg[] = [{ id: "u1", role: "user", content: "run the smoke prompt" }];
    // Committing the buggy shorter list RAW (pre-fix behavior) trips it.
    expect(observerWouldFire(withComplete, buggyResume)).toBe(true);
  });

  it("still allows a deliberate new-chat clear (wipeAllowed) to empty the list", () => {
    const prev: Msg[] = [
      { id: "u1", role: "user", content: "hi" },
      { id: "a1", role: "assistant", content: LONG_ANSWER, status: "complete" },
    ];
    expect(commit(prev, [], true)).toEqual([]);
  });
});

describe("wrapper wiring", () => {
  it("guards the legacy setMessages path silently (no blankTrace on the drop block)", () => {
    expect(source).toMatch(
      /if \(\s*!wipeAllowed &&\s*Array\.isArray\(next\) &&\s*completedAnswerLost\(prev, next\)\s*\) \{\s*return prev;\s*\}/,
    );
  });
});
