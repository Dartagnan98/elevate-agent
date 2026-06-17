import { describe, expect, it } from "vitest";

import { __chatPageTestables } from "../ChatPage";

type TestTool = Parameters<typeof __chatPageTestables.describeToolGroup>[0][number];
type TestTrace = Parameters<typeof __chatPageTestables.buildBreakdownSteps>[1][number];

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

function trace(overrides: Partial<TestTrace>): TestTrace {
  return {
    createdAt: 1,
    id: "trace-1",
    kind: "reasoning",
    text: "",
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

describe("ChatActivityDigest reasoning persistence", () => {
  it("keeps completed work expanded by default", () => {
    expect(
      __chatPageTestables.defaultActivityDigestOpen({
        busy: false,
        hasErroredStep: false,
        hasSteps: true,
      }),
    ).toBe(true);
  });

  it("keeps live work expanded before the first step arrives", () => {
    expect(
      __chatPageTestables.defaultActivityDigestOpen({
        busy: true,
        hasErroredStep: false,
        hasSteps: false,
      }),
    ).toBe(true);
  });

  it("preserves full multiline reasoning in the finished breakdown", () => {
    const fullReasoning = [
      "**Checking the admin deal** I need to inspect the source record.",
      "",
      "Then I should keep the exact evidence visible after the answer lands.",
    ].join("\n");

    const steps = __chatPageTestables.buildBreakdownSteps([], [
      trace({ text: fullReasoning }),
    ]);

    expect(steps).toHaveLength(1);
    expect(steps[0]).toMatchObject({
      type: "trace",
      text: fullReasoning,
    });
  });
});
