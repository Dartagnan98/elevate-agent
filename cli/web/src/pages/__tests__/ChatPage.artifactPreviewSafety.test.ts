import { describe, expect, it } from "vitest";
import source from "../ChatPage.tsx?raw";

describe("artifact preview safety", () => {
  it("renders HTML previews in a no-capability iframe sandbox", () => {
    expect(source).toContain('sandbox=""');
    expect(source).not.toContain('sandbox="allow-scripts allow-same-origin"');
  });
});
