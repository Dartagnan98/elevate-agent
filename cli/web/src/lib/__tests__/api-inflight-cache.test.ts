import { afterEach, expect, it, vi } from "vitest";
import { api } from "../api";

afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

it("shares slow requests beyond the cache TTL and starts freshness on completion", async () => {
  vi.stubGlobal("window", { __ELEVATE_SESSION_TOKEN__: "test", dispatchEvent: () => {} });
  let now = 100_000;
  vi.spyOn(Date, "now").mockImplementation(() => now);
  let finish!: (value: Response) => void;
  const fetch = vi.fn(() => new Promise<Response>(resolve => { finish = resolve; }));
  vi.stubGlobal("fetch", fetch);
  const first = api.getSessions(37, 54321, { includeTotal: false });
  now += 10_000;
  const second = api.getSessions(37, 54321, { includeTotal: false });
  expect(fetch).toHaveBeenCalledTimes(1);
  finish(new Response(JSON.stringify({ sessions: [], total: 0, limit: 37, offset: 54321 })));
  await Promise.all([first, second]);
  now += 1000;
  await api.getSessions(37, 54321, { includeTotal: false });
  expect(fetch).toHaveBeenCalledTimes(1);
});
