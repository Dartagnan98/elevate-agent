import { describe, expect, it } from "vitest";

import source from "../ChatPage.tsx?raw";

describe("agent browser workspace", () => {
  it("opens the visible pane on the workspace emitted by the agent action", () => {
    expect(source).toMatch(
      /event\.type === "agent-action" && event\.workspaceId[\s\S]*setAgentBrowserWorkspace\(\{[\s\S]*workspaceId: event\.workspaceId[\s\S]*setSidePanel\("browser"\)/,
    );
    expect(source).toContain(
      "agentBrowserWorkspaceId ?? sessionId ?? dataSessionId ?? \"default\"",
    );
    expect(source).not.toContain(
      "event.workspaceId === activeBrowserWorkspace",
    );
  });

  it("returns manual browser opens to the current chat workspace", () => {
    expect(source).toMatch(
      /if \(mode === "browser"\) \{[\s\S]*setAgentBrowserWorkspace\(null\)/,
    );
  });

  it("does not leak an agent browser workspace into another chat", () => {
    expect(source).toMatch(
      /agentBrowserWorkspace\?\.chatKey === chatKey[\s\S]*agentBrowserWorkspace\.workspaceId/,
    );
  });
});
