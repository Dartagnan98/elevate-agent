import { describe, expect, it } from "vitest";
import { KitSaveQueue } from "../kit-save-queue";

describe("wizard saves", () => {
  it("serializes writes and waits for them before drafting", async () => {
    const calls: string[] = [];
    let release!: () => void;
    const held = new Promise<void>((resolve) => { release = resolve; });
    const queue = new KitSaveQueue(() => {});
    const first = queue.save("price", async () => { calls.push("price-start"); await held; calls.push("price-end"); });
    const second = queue.save("date", async () => { calls.push("date"); });
    const flushed = queue.flush().then(() => calls.push("draft"));
    await Promise.resolve();
    expect(calls).toEqual(["price-start"]);
    release(); await Promise.all([first, second, flushed]);
    expect(calls).toEqual(["price-start", "price-end", "date", "draft"]);
  });
  it("blocks drafting on persistent failure and retries the failed save", async () => {
    let failing = true;
    let saved = "";
    const errors: string[] = [];
    const queue = new KitSaveQueue((message) => errors.push(message));
    await expect(queue.save("price", async () => { if (failing) throw new Error("offline"); saved = "550000"; })).rejects.toThrow("offline");
    await expect(queue.flush()).rejects.toThrow("offline");
    expect(saved).toBe("");
    failing = false; await queue.flush();
    expect(saved).toBe("550000"); expect(errors.at(-1)).toBe("");
  });
  it("does not retry an older failed value over a newer successful edit", async () => {
    let saved = "";
    const queue = new KitSaveQueue(() => {});
    await queue.save("price", async () => { throw new Error("offline"); }).catch(() => {});
    await queue.save("price", async () => { saved = "new"; });
    await queue.flush(); expect(saved).toBe("new");
  });
});
