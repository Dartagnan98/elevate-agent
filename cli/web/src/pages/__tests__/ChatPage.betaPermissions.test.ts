import source from "../ChatPage.tsx?raw";
import { describe, expect, it } from "vitest";

describe("ChatPage Realtor Beta permissions", () => {
  it("persists bypass mode before enabling the composer for a session", () => {
    expect(source).toContain('setPermissionModeId("bypassPermissions")');
    expect(source).toContain('key: "permission_mode"');
    expect(source).toContain('value: "bypassPermissions"');
    expect(source).toContain("setPermissionModeReadySessionId(sessionId)");
    expect(source).toContain(
      "permissionModeReadySessionId === sessionId",
    );
  });
});
