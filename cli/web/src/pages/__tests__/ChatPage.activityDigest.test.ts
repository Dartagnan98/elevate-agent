import { describe, expect, it } from "vitest";

import { __chatPageTestables } from "../ChatPage";

type TestTool = Parameters<typeof __chatPageTestables.describeToolGroup>[0][number];

function tool(overrides: Partial<TestTool>): TestTool {
  return {
    type: "tool",
    id: "tool-1",
    at: 1,
    name: "terminal",
    context: "",
    status: "done",
    count: 1,
    ...overrides,
  };
}

describe("ChatActivityDigest tool labels", () => {
  it("keeps shell commands out of the visible timeline", () => {
    const terminalTool = tool({
      context: "set -e STAMP=$(date +%Y%m%d-%H%M%S) mkdir -p /tmp/elevate",
      name: "terminal",
    });

    expect(__chatPageTestables.toolTarget(terminalTool)).toBe("");
    expect(__chatPageTestables.describeToolGroup([terminalTool])).toBe(
      "Checked workspace",
    );
  });

  it("uses friendly labels for mixed task and read activity", () => {
    expect(
      __chatPageTestables.describeToolGroup([
        tool({ id: "todo", name: "Todo" }),
        tool({
          count: 5,
          context: '{"path":"/Users/example/elevate/cli/web/src/pages/ChatPage.tsx"}',
          id: "read",
          name: "read_file",
        }),
      ]),
    ).toBe("Updated task list, read 5 files");
  });
});
