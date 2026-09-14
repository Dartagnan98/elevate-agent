import { describe, expect, it, vi } from "vitest";
import { loadAllAdminDeals } from "../load-admin-deals";
import type { AdminDeal } from "@/lib/api-types";
const deal = (id: number) => ({ id: String(id) } as AdminDeal);
describe("complete admin board snapshots", () => {
  it("loads beyond 200 records even though count is only the current page length", async () => {
    const rows = Array.from({ length: 405 }, (_, id) => deal(id));
    const fetch = vi.fn(async ({ offset, limit }) => ({ items: rows.slice(offset, offset + limit), count: Math.min(limit, rows.length - offset) }));
    expect(await loadAllAdminDeals(fetch)).toEqual(rows);
    expect(fetch.mock.calls.map(([p]) => p.offset)).toEqual([0, 200, 400]);
  });
  it("fails instead of accepting a partial snapshot if a later page fails", async () => {
    const fetch = vi.fn(async ({ offset }) => { if (offset) throw new Error("offline"); return { items: Array.from({length: 200}, (_, id) => deal(id)), count: 200 }; });
    await expect(loadAllAdminDeals(fetch)).rejects.toThrow("offline");
  });
  it("does not loop forever when a server ignores the offset", async () => {
    const fetch = vi.fn(async () => ({ items: Array.from({length: 200}, (_, id) => deal(id)), count: 200 }));
    await expect(loadAllAdminDeals(fetch)).rejects.toThrow("could not finish");
    expect(fetch).toHaveBeenCalledTimes(2);
  });
});
