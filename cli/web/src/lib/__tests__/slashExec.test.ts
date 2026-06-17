import { describe, expect, it, vi } from "vitest";

import { executeSlash } from "../slashExec";
import type { GatewayClient } from "../gatewayClient";

function callbacks() {
  return {
    compactDone: vi.fn(),
    compactFailed: vi.fn(),
    send: vi.fn(),
    sendSkill: vi.fn(),
    sys: vi.fn(),
  };
}

describe("executeSlash /compact rendering", () => {
  it("routes typed compact completion to the compact activity callback", async () => {
    const cb = callbacks();
    const gw = {
      request: vi.fn().mockResolvedValue({
        display: "Finished compacting",
        kind: "compact",
        output: "No changes from compression: 24 messages",
      }),
    } as unknown as GatewayClient;

    await expect(
      executeSlash({ callbacks: cb, command: "/compact", gw, sessionId: "sid" }),
    ).resolves.toBe("done");

    expect(cb.compactDone).toHaveBeenCalledWith(
      "Finished compacting",
      "No changes from compression: 24 messages",
    );
    expect(cb.sys).not.toHaveBeenCalled();
    expect(cb.compactFailed).not.toHaveBeenCalled();
  });

  it("treats legacy raw compact summaries as successful compact completions", async () => {
    const cb = callbacks();
    const gw = {
      request: vi.fn().mockResolvedValue({
        output: "Compressed: 30 -> 12 messages\nApprox request size: ~4,000 -> ~1,200 tokens",
      }),
    } as unknown as GatewayClient;

    await executeSlash({ callbacks: cb, command: "/compact", gw, sessionId: "sid" });

    expect(cb.compactDone).toHaveBeenCalledWith(
      "Finished compacting",
      expect.stringContaining("Compressed:"),
    );
    expect(cb.sys).not.toHaveBeenCalled();
  });

  it("routes compact preflight failures back through the compact failure callback", async () => {
    const cb = callbacks();
    const gw = {
      request: vi.fn().mockResolvedValue({
        output: "(._.) Not enough conversation to compact (need at least 4 messages).",
      }),
    } as unknown as GatewayClient;

    await executeSlash({ callbacks: cb, command: "/compact", gw, sessionId: "sid" });

    expect(cb.compactFailed).toHaveBeenCalledWith(
      "(._.) Not enough conversation to compact (need at least 4 messages).",
    );
    expect(cb.compactDone).not.toHaveBeenCalled();
    expect(cb.sys).not.toHaveBeenCalled();
  });

  it("does not render disconnected gateway errors into the transcript", async () => {
    const cb = callbacks();
    const gw = {
      request: vi.fn().mockRejectedValue(new Error("gateway not connected (state=closed)")),
    } as unknown as GatewayClient;

    await expect(
      executeSlash({ callbacks: cb, command: "/compact", gw, sessionId: "sid" }),
    ).resolves.toBe("transport-error");

    expect(gw.request).toHaveBeenCalledTimes(1);
    expect(cb.compactDone).not.toHaveBeenCalled();
    expect(cb.compactFailed).not.toHaveBeenCalled();
    expect(cb.sys).not.toHaveBeenCalled();
  });
});
