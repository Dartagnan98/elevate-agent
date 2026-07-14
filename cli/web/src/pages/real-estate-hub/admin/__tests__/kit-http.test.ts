import { describe, expect, it, vi } from "vitest";
import {
  kitErrorMessage,
  requireKitResponse,
  runKitRequests,
} from "../components/kit-http";

describe("Admin kit HTTP truth", () => {
  it("surfaces a backend setup message for a 409 response", async () => {
    const response = new Response(
      JSON.stringify({ detail: { message: "Install the selected province document pack." } }),
      { status: 409, headers: { "content-type": "application/json" } },
    );

    await expect(requireKitResponse(response, "Could not build the kit"))
      .rejects.toThrow("Install the selected province document pack");
  });

  it("uses a durable realtor-friendly fallback for an empty 404", async () => {
    const response = new Response("", { status: 404 });
    let error: unknown;
    try {
      await requireKitResponse(response, "Listing package generation is not available yet");
    } catch (caught) {
      error = caught;
    }

    expect(kitErrorMessage(error, "Try again.")).toContain(
      "Listing package generation is not available yet (404)",
    );
  });

  it("does not expose raw server exception details", async () => {
    const response = new Response(
      JSON.stringify({ detail: "Generate failed: FileNotFoundError /Users/agent/private/pack.pdf" }),
      { status: 500, headers: { "content-type": "application/json" } },
    );

    await expect(requireKitResponse(response, "The PDF could not be generated"))
      .rejects.toThrow(/^The PDF could not be generated \(500\)\.$/);
  });

  it("stops a kit sequence at the first failed response", async () => {
    const neverCalled = vi.fn(async () => new Response(null, { status: 200 }));
    await expect(runKitRequests([
      {
        request: async () => new Response(null, { status: 409 }),
        fallback: "Could not build the offer kit",
      },
      { request: neverCalled, fallback: "Could not generate the PDF" },
    ])).rejects.toThrow("Could not build the offer kit (409)");
    expect(neverCalled).not.toHaveBeenCalled();
  });
});
