import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { __apiTestables, fetchJSON } from "../api";

describe("API error formatting", () => {
  it("summarizes admin deal gate blocks without dumping JSON", () => {
    const body = JSON.stringify({
      detail: {
        message: "deal phase gate is blocked",
        gate: {
          stage: 2,
          stageName: "Listing Intake",
          nextStage: 3,
          nextStageName: "SkySlope & Matrix Prep",
          canAdvance: false,
          missingChecklist: [
            { id: "mlc_intake_started", label: "MLC intake triggered", required: true },
            { id: "listing_missing_fields", label: "Missing listing fields surfaced", required: true },
            { id: "listing_docs_approval", label: "Listing docs/signature placements ready for approval", required: true },
          ],
          missingFields: [
            { field: "listingAddress", label: "Property address" },
            { field: "signingAuthority", label: "Signing authority" },
            { field: "commissionPct", label: "Commission rate" },
            { field: "listingDate", label: "Planned go-live date" },
            { field: "listingType", label: "Listing type" },
          ],
          missingDocs: [
            { kind: "title_search", label: "Title search" },
            { kind: "signed_envelope", label: "Signed listing envelope" },
          ],
          blockingRuns: [
            { id: "run-1", label: "Listing Intake: Match inbound docs", status: "running" },
            { id: "run-2", label: "Listing Intake: Sync MLC signing", status: "running" },
            { id: "run-3", label: "Listing Intake: Prepare MLC documents", status: "running" },
            { id: "run-4", label: "Listing Intake: Collect MLC info", status: "waiting_human" },
          ],
        },
      },
    });

    expect(__apiTestables.extractErrorDetail(body)).toBe(
      "Listing Intake is blocked. Need: MLC intake triggered, Missing listing fields surfaced, Listing docs/signature placements ready for approval, Property address, +6 more. Waiting on you: Listing Intake: Collect MLC info. Running: 3 tasks.",
    );
  });

  it("summarizes clear-gate stage skips", () => {
    const body = JSON.stringify({
      detail: {
        message: "deal must move through the next phase gate",
        gate: {
          stageName: "CMA / Evaluation",
          nextStageName: "Listing Intake",
          targetStage: 3,
        },
      },
    });

    expect(__apiTestables.extractErrorDetail(body)).toBe("Move through Listing Intake first.");
  });
});

describe("API auth header", () => {
  const originalFetch = globalThis.fetch;
  const originalWindow = globalThis.window;

  beforeEach(() => {
    Object.defineProperty(globalThis, "window", {
      configurable: true,
      value: { __ELEVATE_SESSION_TOKEN__: "session-token" },
    });
  });

  afterEach(() => {
    Object.defineProperty(globalThis, "fetch", {
      configurable: true,
      value: originalFetch,
    });
    Object.defineProperty(globalThis, "window", {
      configurable: true,
      value: originalWindow,
    });
  });

  it("sends the injected local session token on API requests", async () => {
    const fetchMock = vi.fn(async (_input: string, _init?: RequestInit) =>
      new Response(JSON.stringify({ ok: true }), {
        headers: { "Content-Type": "application/json" },
        status: 200,
      }),
    );
    Object.defineProperty(globalThis, "fetch", {
      configurable: true,
      value: fetchMock,
    });

    await expect(fetchJSON<{ ok: boolean }>("/api/status", { cache: "no-store" })).resolves.toEqual({
      ok: true,
    });

    const headers = fetchMock.mock.calls[0]?.[1]?.headers as Headers;
    expect(headers.get("X-Elevate-Session-Token")).toBe("session-token");
  });
});
