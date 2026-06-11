/**
 * transcriptStore invariants + race simulations.
 *
 * Each test encodes one of the failure modes that produced the vanish-bug
 * class (see plans/chat-transcript-refactor.md) — the store makes them
 * structurally impossible rather than guarded-against.
 */

import { afterEach, beforeEach, describe, expect, it } from "vitest";

import {
  _flushWritesForTests,
  _resetForTests,
  _setStorageForTests,
  appendDelta,
  appendLocal,
  beginAssistant,
  clear,
  confirmLocalId,
  finalize,
  getSnapshot,
  getTelemetry,
  patchMeta,
  rekey,
  unionHydrate,
} from "@/lib/transcriptStore";

class FakeStorage {
  private map = new Map<string, string>();
  getItem(k: string) {
    return this.map.has(k) ? this.map.get(k)! : null;
  }
  setItem(k: string, v: string) {
    this.map.set(k, v);
  }
  removeItem(k: string) {
    this.map.delete(k);
  }
  keys() {
    return Array.from(this.map.keys());
  }
}

let store: FakeStorage;

beforeEach(() => {
  store = new FakeStorage();
  _setStorageForTests(store);
  _resetForTests();
});

afterEach(() => {
  _setStorageForTests(null);
  _resetForTests();
});

const KEY = "lineage-root-1";

function user(id: string, content: string) {
  appendLocal(KEY, {
    id,
    role: "user",
    content,
    createdAt: Date.now(),
    status: "complete",
  });
}

function streamTurn(mid: string, chunks: string[], finalText?: string) {
  beginAssistant(KEY, mid);
  for (const c of chunks) appendDelta(KEY, mid, c);
  finalize(KEY, mid, {
    content: finalText ?? chunks.join(""),
    status: "complete",
    completedAt: Date.now(),
  });
}

describe("streaming basics", () => {
  it("streams a turn: begin -> deltas -> finalize", () => {
    user("u1", "question");
    streamTurn("a1", ["Hel", "lo ", "world"]);
    const snap = getSnapshot(KEY);
    expect(snap.map((m) => m.id)).toEqual(["u1", "a1"]);
    expect(snap[1].content).toBe("Hello world");
    expect(snap[1].status).toBe("complete");
  });

  it("late delta after finalize is dropped", () => {
    streamTurn("a1", ["final"]);
    appendDelta(KEY, "a1", "ZOMBIE");
    expect(getSnapshot(KEY)[0].content).toBe("final");
  });

  it("delta for unknown id implies begin (reconnect tolerance)", () => {
    appendDelta(KEY, "a9", "orphan delta");
    const snap = getSnapshot(KEY);
    expect(snap).toHaveLength(1);
    expect(snap[0].status).toBe("streaming");
  });
});

describe("the headline bug: hydrate can never remove or shrink", () => {
  it("populated -> empty hydrate is a no-op (the old wipe is impossible)", () => {
    user("u1", "q");
    streamTurn("a1", ["answer"]);
    const report = unionHydrate(KEY, [], "rest");
    expect(report).toMatchObject({ added: 0, updated: 0 });
    expect(getSnapshot(KEY)).toHaveLength(2);
  });

  it("stale server partial never replaces the rendered answer (945->417)", () => {
    streamTurn("a1", ["the full nine-hundred-forty-five char answer rendered live"]);
    const before = getSnapshot(KEY)[0].content;
    const report = unionHydrate(
      KEY,
      [{ message_id: "a1", role: "assistant", content: "the full nine-hundred" }],
      "rest",
    );
    expect(report.shrinksDropped).toBe(1);
    expect(getSnapshot(KEY)[0].content).toBe(before);
    expect(getTelemetry().shrinksDropped).toBe(1);
  });

  it("hydrate-during-stream backfills history without touching the live turn", () => {
    // History exists server-side; a turn is mid-stream when REST lands.
    user("u3", "current question");
    beginAssistant(KEY, "a3");
    appendDelta(KEY, "a3", "streaming so far");
    unionHydrate(
      KEY,
      [
        { message_id: "u1", role: "user", content: "old q" },
        { message_id: "a1", role: "assistant", content: "old a" },
        { message_id: "u3", role: "user", content: "current question" },
      ],
      "rest",
    );
    const snap = getSnapshot(KEY);
    // History sorts BEFORE the live turn; the streaming message is untouched.
    expect(snap.map((m) => m.id)).toEqual(["u1", "a1", "u3", "a3"]);
    expect(snap[3].content).toBe("streaming so far");
    expect(snap[3].status).toBe("streaming");
  });

  it("hydrate never demotes complete -> streaming and never clobbers metadata", () => {
    streamTurn("a1", ["done"]);
    patchMeta(KEY, "a1", { tokenCount: 42, tools: [{ name: "x" } as never] });
    unionHydrate(
      KEY,
      [{ message_id: "a1", role: "assistant", content: "done", status: "streaming" as never }],
      "resume",
    );
    const m = getSnapshot(KEY)[0];
    expect(m.status).toBe("complete");
    expect(m.tokenCount).toBe(42);
    expect(m.tools).toHaveLength(1);
  });

  it("union is idempotent (duplicate replay)", () => {
    const wire = [
      { message_id: "u1", role: "user" as const, content: "q" },
      { message_id: "a1", role: "assistant" as const, content: "a" },
    ];
    const first = unionHydrate(KEY, wire, "resume");
    const second = unionHydrate(KEY, wire, "replay");
    expect(first.added).toBe(2);
    expect(second.added).toBe(0);
    expect(second.updated).toBe(0);
    expect(getSnapshot(KEY)).toHaveLength(2);
  });
});

describe("remount mid-turn (cache restore + replay)", () => {
  it("replayed start/delta/complete after restore is idempotent by id", () => {
    streamTurn("a1", ["part one ", "part two"]);
    const before = getSnapshot(KEY)[0];
    // Reconnect replays the whole turn.
    beginAssistant(KEY, "a1");
    appendDelta(KEY, "a1", "part one ");
    finalize(KEY, "a1", {
      content: "part one part two",
      status: "complete",
      completedAt: Date.now(),
    });
    const after = getSnapshot(KEY)[0];
    expect(after.content).toBe(before.content);
    expect(getSnapshot(KEY)).toHaveLength(1);
  });

  it("localStorage round-trip restores transcripts on a cold bucket", () => {
    user("u1", "persisted question");
    streamTurn("a1", ["persisted answer"]);
    _flushWritesForTests();
    _resetForTests(); // simulate full remount: in-memory store gone
    const snap = getSnapshot(KEY); // lazy-restores from v2 cache
    expect(snap.map((m) => m.content)).toEqual([
      "persisted question",
      "persisted answer",
    ]);
  });

  it("zombie streaming message older than 12h restores as interrupted", () => {
    beginAssistant(KEY, "a1");
    appendDelta(KEY, "a1", "never finished");
    _flushWritesForTests();
    // Age the cache entry.
    const raw = JSON.parse(store.getItem("elevate.chat.messageCache.v2")!);
    raw[KEY].updatedAt = Date.now() - 13 * 60 * 60 * 1000;
    store.setItem("elevate.chat.messageCache.v2", JSON.stringify(raw));
    _resetForTests();
    const snap = getSnapshot(KEY);
    expect(snap[0].status).toBe("interrupted");
    expect(snap[0].content).toBe("never finished");
  });

  it("v1 cache keys are purged on first store access", () => {
    store.setItem("elevate.chat.messageCache.v1", "{}");
    store.setItem("elevate.chat.activeTurnCache.v1", "{}");
    getSnapshot(KEY);
    expect(store.getItem("elevate.chat.messageCache.v1")).toBeNull();
    expect(store.getItem("elevate.chat.activeTurnCache.v1")).toBeNull();
  });
});

describe("mint mid-stream (draft -> lineage rekey)", () => {
  it("rekey preserves messages and live streaming continues", () => {
    const draft = "draft:abc";
    appendLocal(draft, {
      id: "u1",
      role: "user",
      content: "first message",
      createdAt: Date.now(),
      status: "complete",
    });
    beginAssistant(draft, "a1");
    appendDelta(draft, "a1", "strea");
    rekey(draft, KEY);
    appendDelta(KEY, "a1", "ming");
    const snap = getSnapshot(KEY);
    expect(snap.map((m) => m.id)).toEqual(["u1", "a1"]);
    expect(snap[1].content).toBe("streaming");
  });
});

describe("compaction rotation", () => {
  it("pre- and post-rotation hydrates union under one chatKey", () => {
    unionHydrate(
      KEY,
      [
        { message_id: "u1", role: "user", content: "before rotation" },
        { message_id: "a1", role: "assistant", content: "answer one" },
      ],
      "resume",
    );
    // After rotation the active session id changed, but lineage root (chatKey)
    // didn't — the next hydrate brings overlapping + new messages.
    unionHydrate(
      KEY,
      [
        { message_id: "a1", role: "assistant", content: "answer one" },
        { message_id: "u2", role: "user", content: "after rotation" },
        { message_id: "a2", role: "assistant", content: "answer two" },
      ],
      "resume",
    );
    expect(getSnapshot(KEY)).toHaveLength(4);
  });
});

describe("legacy weak-id semantics", () => {
  it("weak ids dedupe by fingerprint (weak<->weak only)", () => {
    unionHydrate(
      KEY,
      [{ message_id: "legacy.s1.0", role: "user", content: "  same   text " }],
      "rest",
    );
    const report = unionHydrate(
      KEY,
      [{ message_id: "legacy.s1.0", role: "user", content: "same text" }],
      "resume",
    );
    // Direct id match would also catch this; force a different legacy id to
    // prove fingerprint matching:
    const report2 = unionHydrate(
      KEY,
      [{ message_id: "legacy.OTHER.5", role: "user", content: "same text" }],
      "resume",
    );
    expect(getSnapshot(KEY)).toHaveLength(1);
    expect(report.added + report2.added).toBe(0);
    expect(getTelemetry().weakMatches).toBeGreaterThanOrEqual(1);
  });

  it("strong ids never fingerprint-match (distinct messages, same text)", () => {
    unionHydrate(
      KEY,
      [
        { message_id: "uuid-1", role: "user", content: "ok" },
        { message_id: "uuid-2", role: "user", content: "ok" },
      ],
      "rest",
    );
    expect(getSnapshot(KEY)).toHaveLength(2);
  });
});

describe("explicit operations", () => {
  it("clear is the only remover", () => {
    user("u1", "q");
    streamTurn("a1", ["a"]);
    clear(KEY);
    expect(getSnapshot(KEY)).toHaveLength(0);
    expect(getTelemetry().clears).toBe(1);
  });

  it("confirmLocalId renames an optimistic bubble", () => {
    user("local-temp", "optimistic");
    confirmLocalId(KEY, "local-temp", "server-uuid");
    const snap = getSnapshot(KEY);
    expect(snap[0].id).toBe("server-uuid");
    expect(snap).toHaveLength(1);
  });

  it("appendLocal is idempotent by id", () => {
    user("u1", "once");
    user("u1", "twice");
    expect(getSnapshot(KEY)).toHaveLength(1);
    expect(getSnapshot(KEY)[0].content).toBe("once");
  });
});
