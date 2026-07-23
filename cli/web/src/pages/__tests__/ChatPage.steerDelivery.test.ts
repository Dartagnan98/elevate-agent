import { describe, expect, it } from "vitest";

import { __chatPageTestables } from "../ChatPage";
import source from "../ChatPage.tsx?raw";

type QueuedInput = Parameters<
  typeof __chatPageTestables.requeueUndeliveredSteer
>[0][number];

function queued(id: string, text: string, status: QueuedInput["status"] = "queued"): QueuedInput {
  return {
    agentId: "executive-assistant",
    createdAt: 1,
    id,
    routedText: text,
    status,
    text,
  };
}

const { reconcileSteerAccepted, requeueUndeliveredSteer, steerClientMessageId } =
  __chatPageTestables;

describe("steer client message id", () => {
  it("prefixes queue ids with the durable steer marker exactly once", () => {
    expect(steerClientMessageId("queued-abc")).toBe("steer.queued-abc");
    expect(steerClientMessageId("steer.queued-abc")).toBe("steer.queued-abc");
  });
});

describe("rejected steer returns to the ordinary queue (live 'not sent' bug)", () => {
  // Operator repro: second busy-send ("go") hit the gateway's rejected
  // status and the item was parked as status "error" — which the !busy
  // drain (find status === "queued") NEVER dispatches. Permanent dead row.
  it("re-queues the item in place instead of parking it as error", () => {
    const items = [queued("queued-go", "go")];
    const out = requeueUndeliveredSteer(items, "queued-go", "sends when the turn ends");
    expect(out).toHaveLength(1);
    expect(out[0].status).toBe("queued");
    expect(out[0].hint).toBe("sends when the turn ends");
  });

  it("also matches an item already flipped to the durable steer id", () => {
    const items = [queued("steer.queued-go", "go", "steering")];
    const out = requeueUndeliveredSteer(items, "queued-go", "sends when the turn ends");
    expect(out[0].status).toBe("queued");
  });

  it("keeps queue order so a re-queued steer sends before later messages", () => {
    const items = [
      queued("queued-go", "go", "error"),
      queued("queued-later", "typed afterwards"),
    ];
    const out = requeueUndeliveredSteer(items, "queued-go", "sends when the turn ends");
    // The drain effect dispatches the FIRST status === "queued" item.
    const next = out.find((item) => item.status === "queued");
    expect(next?.id).toBe("queued-go");
  });

  it("the rejected branch wires requeue, not a dead error state", () => {
    expect(source).toMatch(
      /if \(status === "rejected"\) \{[\s\S]*?requeueUndeliveredSteer\(prev, queuedId, "sends when the turn ends"\)/,
    );
    // The drain still dispatches plain queued items only — the ordering and
    // delivery guarantee both hang on this exact predicate.
    expect(source).toMatch(
      /queuedInputs\.find\(\(item\) => item\.status === "queued"\)/,
    );
  });

  it("a failed steer transport retries once and then falls back to the queue", () => {
    expect(source).toMatch(
      /if \(attempt === 0\) \{[\s\S]*?window\.setTimeout\(\(\) => attemptSteer\(1\), 800\);/,
    );
    expect(source).toMatch(
      /Steer failed \(\$\{message\}\) — the message stays queued and will be sent as the next turn\./,
    );
  });
});

describe("accepted steer reconciliation (exactly-once)", () => {
  it("adopts the sender's local queued copy under the durable id", () => {
    const items = [queued("queued-go", "go")];
    const out = reconcileSteerAccepted(items, "steer.queued-go", "go", 5);
    expect(out).toHaveLength(1);
    expect(out[0].id).toBe("steer.queued-go");
    expect(out[0].status).toBe("steering");
  });

  it("is idempotent for the RPC-response + steer.queued event pair", () => {
    const once = reconcileSteerAccepted([queued("queued-go", "go")], "steer.queued-go", "go", 5);
    const twice = reconcileSteerAccepted(once, "steer.queued-go", "go", 6);
    expect(twice).toBe(once);
  });

  it("adopts by text for legacy events without a client id", () => {
    const items = [queued("queued-go", "go")];
    const out = reconcileSteerAccepted(items, "steering-rand1", "go", 5);
    expect(out).toHaveLength(1);
    expect(out[0].status).toBe("steering");
  });

  it("appends a steering row for other viewers with no local copy", () => {
    const out = reconcileSteerAccepted([], "steer.queued-go", "go", 5);
    expect(out).toHaveLength(1);
    expect(out[0].status).toBe("steering");
    expect(out[0].id).toBe("steer.queued-go");
  });

  it("never leaves a duplicate queued copy that would re-send next turn", () => {
    const items = [queued("queued-go", "go")];
    const out = reconcileSteerAccepted(items, "steer.queued-go", "go", 5);
    expect(out.filter((q) => q.text === "go")).toHaveLength(1);
  });

  it("an applied steer also removes a same-id copy in any status", () => {
    // consumeAppliedSteers must drop the scoped ids regardless of status —
    // a retry race can have flipped the item back to "queued", and leaving
    // it behind re-sends an already-applied steer as a fresh turn.
    expect(source).toMatch(
      /if \(applyAll\) return q\.status !== "steering";\s*if \(appliedIds\.has\(q\.id\)\) return false;/,
    );
  });
});

describe("stop press reconciles a wedged-busy view", () => {
  it("probes the authoritative running latch right after a waiting stop", () => {
    expect(source).toMatch(
      /setStatusText\(result\.status === "finishing" \? "Finishing\.\.\." : "Stopping\.\.\."\);[\s\S]*?session\.running/,
    );
  });

  it("treats session-not-found on stop as authoritative idle", () => {
    expect(source).toMatch(
      /session not found/i,
    );
    expect(source).toMatch(
      /if \(\/session not found\/i\.test\(stopMessage\)\) \{[\s\S]*?setBusy\(false\);/,
    );
  });
});

describe("steer strip acknowledgment", () => {
  it("shows the requeue hint on the strip row", () => {
    expect(source).toMatch(/item\.hint \|\|\s*\(busy \? "waits for current turn"/);
  });

  it("sends the durable client id on the steer RPC", () => {
    expect(source).toMatch(
      /gw\s*\.request\("session\.steer", \{\s*session_id: sessionId,\s*text,\s*client_message_id: steerClientId,/,
    );
  });
});
