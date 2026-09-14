// @vitest-environment happy-dom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { api } from "@/lib/api";
import { useAdminDeals } from "../use-admin-deals";
import type { AdminDeal } from "@/lib/api-types";
vi.mock("@/lib/api", () => ({ api: { getAdminDeals: vi.fn(), moveAdminDeal: vi.fn() } }));
const row = (stage = 1) => ({ id: "sample", currentStage: stage } as AdminDeal);
function deferred<T>() { let resolve!: (value: T) => void; const promise = new Promise<T>(r => { resolve = r; }); return { promise, resolve }; }
beforeEach(() => { vi.resetAllMocks(); vi.mocked(api.getAdminDeals).mockResolvedValue({ items: [row()], count: 1 }); });
afterEach(cleanup);
async function setup() { const hook = renderHook(() => useAdminDeals()); await waitFor(() => expect(hook.result.current.loading).toBe(false)); return hook; }
describe("admin recovery behavior", () => {
  it("preserves visible deals when either a manual or silent refresh fails", async () => {
    const hook = await setup();
    vi.mocked(api.getAdminDeals).mockRejectedValue(new Error("offline"));
    for (const silent of [false, true]) {
      await act(() => hook.result.current.refresh({ silent }));
      expect(hook.result.current.deals).toEqual([row()]);
      expect(hook.result.current.error).toBe("offline");
      expect(hook.result.current.loading).toBe(false);
    }
  });
  it("keeps the newest refresh when an older request resolves last", async () => {
    const hook = await setup(); const old = deferred<{items: AdminDeal[]; count: number}>();
    vi.mocked(api.getAdminDeals).mockReturnValueOnce(old.promise).mockResolvedValueOnce({items: [row(3)], count: 1});
    let first!: Promise<void>;
    await act(async () => { first = hook.result.current.refresh({silent:true}); await Promise.resolve(); });
    await act(() => hook.result.current.refresh({silent:true}));
    await act(async () => { old.resolve({items:[row(2)],count:1}); await first; });
    expect(hook.result.current.deals[0].currentStage).toBe(3);
  });
  it("rolls a failed move back and keeps its error visible through background refresh", async () => {
    const hook = await setup(); vi.mocked(api.moveAdminDeal).mockRejectedValue(new Error("Stage is blocked"));
    await act(() => hook.result.current.moveDeal("sample",2));
    expect(hook.result.current.deals[0].currentStage).toBe(1);
    await act(() => hook.result.current.refresh({silent:true}));
    expect(hook.result.current.error).toBe("Stage is blocked");
  });
  it("serializes same-deal moves so the second starts from the persisted first stage", async () => {
    const hook = await setup(); const held = deferred<AdminDeal>();
    vi.mocked(api.moveAdminDeal).mockReturnValueOnce(held.promise).mockResolvedValueOnce(row(3));
    let first!:Promise<void>,second!:Promise<void>;
    await act(async () => { first=hook.result.current.moveDeal("sample",2); second=hook.result.current.moveDeal("sample",3); await Promise.resolve(); });
    expect(api.moveAdminDeal).toHaveBeenCalledTimes(1);
    expect(hook.result.current.deals[0].currentStage).toBe(2);
    await act(async () => { held.resolve(row(2)); await Promise.all([first,second]); });
    expect(api.moveAdminDeal).toHaveBeenNthCalledWith(2,"sample",3);
    expect(hook.result.current.deals[0].currentStage).toBe(3);
  });
  it("does not let a refresh begun before a move replace the moved card", async () => {
    const hook = await setup();const held=deferred<{items:AdminDeal[];count:number}>();
    vi.mocked(api.getAdminDeals).mockReturnValueOnce(held.promise);
    vi.mocked(api.moveAdminDeal).mockResolvedValue(row(2));
    let refresh!:Promise<void>;
    await act(async()=>{refresh=hook.result.current.refresh({silent:true});await Promise.resolve();});
    await act(()=>hook.result.current.moveDeal("sample",2));
    await act(async()=>{held.resolve({items:[row()],count:1});await refresh;});
    expect(hook.result.current.deals[0].currentStage).toBe(2);
  });
});
