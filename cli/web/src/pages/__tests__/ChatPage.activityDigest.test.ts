import { describe, expect, it } from "vitest";

import { __chatPageTestables } from "../ChatPage";

type TestTool = Parameters<typeof __chatPageTestables.describeToolGroup>[0][number];
type TestTrace = Parameters<typeof __chatPageTestables.buildBreakdownSteps>[1][number];
type TestMessage = Parameters<typeof __chatPageTestables.repairOutOfOrderUserTurns>[0][number];
type TestActiveSnapshot = Parameters<typeof __chatPageTestables.mergeActiveTurnSnapshot>[1];

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

function message(overrides: Partial<TestMessage>): TestMessage {
  return {
    content: "",
    createdAt: 1,
    id: "message-1",
    role: "assistant",
    status: "complete",
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

  it("keeps the step body visible across the live-to-completed transition", () => {
    const live = __chatPageTestables.resolveActivityDigestVisibility({
      busy: true,
      hasErroredStep: false,
      hasSteps: true,
      userOpen: null,
    });
    const completed = __chatPageTestables.resolveActivityDigestVisibility({
      busy: false,
      hasErroredStep: false,
      hasSteps: true,
      userOpen: null,
    });

    expect(live).toMatchObject({ expanded: true, showSteps: true });
    expect(completed).toMatchObject({ expanded: true, showSteps: true });
  });

  it("keeps the live header active before the first step arrives without a placeholder row", () => {
    expect(
      __chatPageTestables.defaultActivityDigestOpen({
        busy: true,
        hasErroredStep: false,
        hasSteps: false,
      }),
    ).toBe(true);
    expect(
      __chatPageTestables.resolveActivityDigestVisibility({
        busy: true,
        hasErroredStep: false,
        hasSteps: false,
        userOpen: null,
      }),
    ).toEqual({ expanded: true, showSteps: false });
  });

  it("respects an explicit user close across completion", () => {
    expect(
      __chatPageTestables.resolveActivityDigestVisibility({
        busy: false,
        hasErroredStep: false,
        hasSteps: true,
        userOpen: false,
      }),
    ).toEqual({
      expanded: false,
      showSteps: false,
    });
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

describe("manual /compact activity", () => {
  it("starts the automatic-style activity row for idle manual compact commands", () => {
    expect(__chatPageTestables.isCompactSlashCommand("/compact")).toBe(true);
    expect(__chatPageTestables.isCompactSlashCommand("/compact summarize old lead work")).toBe(true);
    expect(__chatPageTestables.isCompactSlashCommand("/compactview")).toBe(false);

    expect(__chatPageTestables.shouldStartManualCompactActivity("/compact", false)).toBe(true);
    expect(__chatPageTestables.shouldStartManualCompactActivity("/compact", true)).toBe(false);
  });
});

describe("chat transcript ordering repair", () => {
  it("moves an orphan assistant answer below its prompting user bubble", () => {
    const repaired = __chatPageTestables.repairOutOfOrderUserTurns([
      message({
        content: "Here is the detailed checklist.",
        createdAt: 1_001,
        id: "assistant-answer",
        role: "assistant",
      }),
      message({
        content: "Create a detailed checklist.",
        createdAt: 1_000,
        id: "user-prompt",
        role: "user",
      }),
    ]);

    expect(repaired.map((item) => item.id)).toEqual([
      "user-prompt",
      "assistant-answer",
    ]);
  });

  it("leaves normal follow-up order alone", () => {
    const ordered = [
      message({ content: "First prompt", createdAt: 1_000, id: "u1", role: "user" }),
      message({ content: "First answer", createdAt: 1_010, id: "a1", role: "assistant" }),
      message({ content: "Follow up", createdAt: 2_000, id: "u2", role: "user" }),
    ];

    expect(__chatPageTestables.repairOutOfOrderUserTurns(ordered)).toBe(ordered);
  });
});

describe("message row memoization", () => {
  it("does not re-render a completed answer only because empty collection props were recreated", () => {
    const answer = message({
      content: "A long completed answer that should stay memoized.",
      id: "assistant-answer",
      role: "assistant",
    });
    const openArtifact = () => {};

    expect(
      __chatPageTestables.messageRowPropsEqual(
        {
          artifacts: [],
          message: answer,
          onOpenArtifact: openArtifact,
        },
        {
          activityTrace: [],
          artifacts: [],
          message: answer,
          onOpenArtifact: openArtifact,
          subagents: [],
          tools: [],
          turnArtifacts: [],
        },
      ),
    ).toBe(true);
  });
});

describe("active turn resume cache", () => {
  it("does not turn a completed server answer back into a streaming active snapshot", () => {
    const completed = message({
      content: "Finished answer",
      id: "assistant-server",
      status: "complete",
    });
    const staleSnapshot: TestActiveSnapshot = {
      message: message({
        content: "Partial answer",
        id: "assistant-server",
        status: "streaming",
      }),
      tools: [],
      traces: [],
      updatedAt: Date.now(),
    };

    const merged = __chatPageTestables.mergeActiveTurnSnapshot(
      [completed],
      staleSnapshot,
    );

    expect(merged).toEqual([completed]);
    expect(merged[0].status).toBe("complete");
  });

  it("does not append a duplicate completed answer when only the reasoning trace matches", () => {
    const reasoning = [
      "I need to create the requested checklist and keep the response structured.",
      "The server has already persisted this assistant turn as complete.",
    ].join(" ");
    const completed = message({
      content: "Here is the 60 item checklist.",
      id: "assistant-server",
      role: "assistant",
      status: "complete",
      traces: [trace({ id: "server-reasoning", messageId: "assistant-server", text: reasoning })],
    });
    const staleSnapshot: TestActiveSnapshot = {
      message: message({
        content: "",
        id: "assistant-local-active",
        role: "assistant",
        status: "streaming",
        traces: [trace({ id: "local-reasoning", messageId: "assistant-local-active", text: reasoning })],
      }),
      tools: [],
      traces: [trace({ id: "snapshot-reasoning", messageId: "assistant-local-active", text: reasoning })],
      updatedAt: Date.now(),
    };

    const merged = __chatPageTestables.mergeActiveTurnSnapshot(
      [completed],
      staleSnapshot,
    );

    expect(merged).toEqual([completed]);
  });
});

describe("server/cache transcript merge", () => {
  it("preserves repeated identical user prompts as separate turns", () => {
    const prompt = "Use subagents if helpful. Compare three ways to improve listing conversion.";
    const server = [
      message({ content: prompt, createdAt: 1_000, id: "u1", role: "user" }),
      message({ content: "First dispatch started.", createdAt: 1_010, id: "a1", role: "assistant" }),
      message({ content: prompt, createdAt: 2_000, id: "u2", role: "user" }),
      message({ content: "Second dispatch restarted.", createdAt: 2_010, id: "a2", role: "assistant" }),
    ];
    const cached = [
      message({ content: prompt, createdAt: 1_000, id: "cached-u1", role: "user" }),
      message({ content: "First dispatch started.", createdAt: 1_010, id: "cached-a1", role: "assistant" }),
    ];

    const merged = __chatPageTestables.mergeServerWithCache(server, cached, false);

    expect(merged.map((item) => item.id)).toEqual(["u1", "a1", "u2", "a2"]);
    expect(merged.filter((item) => item.role === "user" && item.content === prompt)).toHaveLength(2);
  });
});
