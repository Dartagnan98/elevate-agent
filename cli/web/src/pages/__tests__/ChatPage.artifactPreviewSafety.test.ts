import { describe, expect, it } from "vitest";
import source from "../ChatPage.tsx?raw";

describe("artifact preview safety", () => {
  it("renders HTML previews in a no-capability iframe sandbox", () => {
    expect(source).toContain('sandbox=""');
    expect(source).not.toContain('sandbox="allow-scripts allow-same-origin"');
  });

  it("keeps visible errors for preview and microphone permission failures", () => {
    expect(source).toContain("Could not preview this file");
    expect(source).toContain("Microphone access was denied. Allow mic access to use voice input.");
  });
});
