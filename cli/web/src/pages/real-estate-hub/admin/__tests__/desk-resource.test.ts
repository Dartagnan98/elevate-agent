// @vitest-environment happy-dom
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { fetchJSON } from "@/lib/api";
import { useDeskResource } from "../use-desk-resource";
vi.mock("@/lib/api", () => ({fetchJSON:vi.fn()}));
afterEach(cleanup);beforeEach(()=>vi.resetAllMocks());
it("distinguishes an unavailable desk from a successfully empty queue",async()=>{
 vi.mocked(fetchJSON).mockRejectedValueOnce(new Error("offline")).mockResolvedValueOnce({ok:true,count:0});
 const {result}=renderHook(()=>useDeskResource<{ok:boolean;count:number}>("/fixture"));
 await waitFor(()=>expect(result.current.loading).toBe(false));
 expect(result.current.data).toBeNull();expect(result.current.error).toBe("offline");
 await act(()=>result.current.load());expect(result.current.data?.count).toBe(0);expect(result.current.error).toBeNull();
});
it("keeps the previous deadlines when refresh fails and flags the stale snapshot",async()=>{
 vi.mocked(fetchJSON).mockResolvedValueOnce({ok:true,count:3}).mockRejectedValueOnce(new Error("offline"));
 const {result}=renderHook(()=>useDeskResource<{ok:boolean;count:number}>("/fixture"));
 await waitFor(()=>expect(result.current.loading).toBe(false));
 await act(()=>result.current.load());expect(result.current.data?.count).toBe(3);expect(result.current.error).toBe("offline");
});
it("refetches when the board snapshot changes",async()=>{
 vi.mocked(fetchJSON).mockResolvedValue({ok:true,count:0});
 const hook=renderHook(({revision})=>useDeskResource("/fixture",revision),{initialProps:{revision:0}});
 await waitFor(()=>expect(hook.result.current.loading).toBe(false));hook.rerender({revision:1});
 await waitFor(()=>expect(fetchJSON).toHaveBeenCalledTimes(2));
});
