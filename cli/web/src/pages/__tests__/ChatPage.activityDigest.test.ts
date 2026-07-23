import { describe, expect, it } from "vitest";

import { __chatPageTestables } from "../ChatPage";

type TestTool = Parameters<typeof __chatPageTestables.describeToolGroup>[0][number];
type TestToolEntry = Parameters<typeof __chatPageTestables.buildBreakdownSteps>[0][number];
type TestTrace = Parameters<typeof __chatPageTestables.buildBreakdownSteps>[1][number];
type TestMessage = Parameters<typeof __chatPageTestables.mergeActiveTurnSnapshot>[0][number];
type TestActiveSnapshot = Parameters<typeof __chatPageTestables.mergeActiveTurnSnapshot>[1];
type TestBackgroundTask = Parameters<typeof __chatPageTestables.sortBackgroundTasksForDisplay>[0][number];

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

function toolEntry(overrides: Partial<TestToolEntry>): TestToolEntry {
  return {
    kind: "tool",
    id: "tool-entry-1",
    tool_id: "tool-entry-1",
    name: "terminal",
    status: "done",
    startedAt: 1,
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

function backgroundTask(overrides: Partial<TestBackgroundTask>): TestBackgroundTask {
  return {
    id: "task-1",
    kind: "subagent",
    label: "Subagent",
    status: "done",
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

  it("does not misclassify realtor overview tools as file views", () => {
    expect(
      __chatPageTestables.describeToolGroup([
        tool({ name: "leads_overview", context: '{"recent_limit":1}' }),
      ]),
    ).toBe("Checked leads");
    expect(
      __chatPageTestables.describeToolGroup([
        tool({ name: "deals_overview", context: '{"status":"active"}' }),
      ]),
    ).toBe("Checked deals");
  });

  it("preserves command and skill categories for plural or compound tool names", () => {
    expect(
      __chatPageTestables.describeToolGroup([
        tool({ name: "execute_code", context: '{"code":"print(1)"}' }),
      ]),
    ).toBe("Checked workspace");
    expect(
      __chatPageTestables.describeToolGroup([
        tool({ name: "skills_list", context: "" }),
      ]),
    ).toBe("Loaded a skill");
  });
});

describe("terminal failure truth", () => {
  it("reuses the failed assistant row when its terminal completion arrives", () => {
    expect(
      __chatPageTestables.terminalErrorCompletionTarget(
        null,
        "assistant-live",
        "assistant-live",
      ),
    ).toBe("assistant-live");
    expect(
      __chatPageTestables.terminalErrorCompletionTarget(
        null,
        "assistant-other",
        "assistant-live",
      ),
    ).toBeNull();
  });

  it("settles a live assistant and marks unfinished tools errored on gateway failure", () => {
    const failed = __chatPageTestables.failActiveTurnMessage(
      message({ content: "", id: "assistant-live", status: "streaming" }),
      [
        toolEntry({ messageId: "assistant-live", status: "running" }),
        toolEntry({ id: "done", messageId: "assistant-live", status: "done" }),
        toolEntry({ id: "other", messageId: "assistant-other", status: "running" }),
      ],
      "agent crashed",
      2_000,
    );

    expect(failed).toMatchObject({
      completedAt: 2_000,
      content: "agent crashed",
      status: "error",
    });
    expect(failed.tools).toMatchObject([
      { completedAt: 2_000, error: "agent crashed", status: "error" },
      { id: "done", status: "done" },
    ]);
  });

  it.each(["timeout", "interrupted", "cancelled", "error", "failed", "", undefined])(
    "does not present subagent status %s as success",
    (status) => {
      expect(__chatPageTestables.subagentCompletionStatus(status)).toBe("error");
    },
  );

  it("presents only explicit completed subagent status as success", () => {
    expect(__chatPageTestables.subagentCompletionStatus("completed")).toBe("done");
    expect(__chatPageTestables.subagentCompletionStatus("Completed")).toBe("done");
  });

  it.each([
    "delegation_failed",
    "delegation_timeout",
    "delegation_interrupted",
    "delegation_start_failed",
    "unknown_terminal_reason",
    "",
    undefined,
  ])("keeps durable terminal reason %s out of the done state", (endReason) => {
    expect(
      __chatPageTestables.durableSubagentCompletionStatus({
        ended_at: 2_000,
        end_reason: endReason,
      }),
    ).toBe("error");
  });

  it("treats only delegation_complete as durable success", () => {
    expect(
      __chatPageTestables.durableSubagentCompletionStatus({
        ended_at: 2_000,
        end_reason: "delegation_complete",
      }),
    ).toBe("done");
    expect(
      __chatPageTestables.durableSubagentCompletionStatus({
        ended_at: null,
        end_reason: "delegation_complete",
      }),
    ).toBe("running");
  });

  it("preserves interrupted durable truth during poll and reload reconciliation", () => {
    const running = {
      goal: "Prepare documents",
      id: "subagent-1",
      startedAt: 1_000,
      status: "running" as const,
      subagent_id: "subagent-1",
    };
    const reconciled = __chatPageTestables.reconcileSubagentFromDurableChild(
      running,
      {
        id: "child-1",
        ended_at: 2_000,
        end_reason: "delegation_interrupted",
      },
    );

    expect(reconciled).toMatchObject({
      status: "error",
      completedAt: 2_000_000,
      finalSummary: "delegation_interrupted",
    });
    expect(
      __chatPageTestables.reconcileSubagentFromDurableChild(reconciled, {
        id: "child-1",
        ended_at: 2_000,
        end_reason: "delegation_interrupted",
      }),
    ).toEqual(reconciled);
  });
});

describe("session Stop quiescence", () => {
  it("keeps the composer waiting while the fenced worker is still running", () => {
    expect(
      __chatPageTestables.sessionStopDisposition(
        { quiesced: false, running: true, status: "stopping" },
        true,
      ),
    ).toBe("waiting");
  });

  it("settles only from explicit quiescence", () => {
    expect(
      __chatPageTestables.sessionStopDisposition(
        { quiesced: true, running: false, status: "stopped" },
        true,
      ),
    ).toBe("settled");
  });

  it("trusts authoritative running state even when the UI lost assistant identity", () => {
    expect(
      __chatPageTestables.sessionStopDisposition(
        { quiesced: false, running: true, status: "stopping" },
        false,
      ),
    ).toBe("waiting");
  });

  it("does not restore stopping state after authoritative quiescence", () => {
    expect(
      __chatPageTestables.sessionStopDisposition(
        { quiesced: true, running: false, status: "stopped" },
        false,
      ),
    ).toBe("settled");
  });
});

describe("delegate completion truth", () => {
  it("accepts only an explicit verified completion", () => {
    expect(
      __chatPageTestables.delegateCompletionIsVerified({
        status: "complete",
        task_id: "dt-1",
      }),
    ).toBe(true);
  });

  it.each([
    undefined,
    {},
    { status: "complete" },
    { status: "error", task_id: "dt-1" },
    { error: "malformed result", status: "complete", task_id: "dt-1" },
    { status: "pending", task_id: "dt-1" },
  ])("rejects malformed or unresolved completion payload %#", (payload) => {
    expect(__chatPageTestables.delegateCompletionIsVerified(payload)).toBe(false);
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

  it("hides reasoning prose when show reasoning is off but keeps tool activity", () => {
    const steps = __chatPageTestables.buildBreakdownSteps(
      [toolEntry({ id: "read", name: "read_file", tool_id: "read" })],
      [
        trace({
          id: "private-reasoning",
          text: "I am thinking through private intermediate details.",
        }),
      ],
      { showReasoning: false },
    );

    expect(steps).toHaveLength(1);
    expect(steps[0]).toMatchObject({
      type: "group",
      label: "Read a file",
    });
    expect(JSON.stringify(steps)).not.toContain("private intermediate details");
  });
});

describe("manual /compact activity", () => {
  it("recognizes manual compact commands without starting activity locally", () => {
    expect(__chatPageTestables.isCompactSlashCommand("/compact")).toBe(true);
    expect(__chatPageTestables.isCompactSlashCommand("/compact summarize old lead work")).toBe(true);
    expect(__chatPageTestables.isCompactSlashCommand("/compactview")).toBe(false);
  });

  it("clears stale context usage only when compaction starts", () => {
    expect(__chatPageTestables.shouldClearUsageForStatus("Compacting context")).toBe(true);
    expect(__chatPageTestables.shouldClearUsageForStatus("Working through earlier context")).toBe(true);
    expect(__chatPageTestables.shouldClearUsageForStatus("Session compacted")).toBe(false);
  });

  it("uses structured compact status before text fallback", () => {
    expect(
      __chatPageTestables.shouldClearUsageForStatusUpdate("compacting_context", "Preparing"),
    ).toBe(true);
    expect(
      __chatPageTestables.shouldClearUsageForStatusUpdate(undefined, "Compacting context"),
    ).toBe(true);
    expect(
      __chatPageTestables.shouldClearUsageForStatusUpdate("session_compacted", "Session compacted"),
    ).toBe(false);
  });

  it("describes context ring pending and left-versus-used values", () => {
    expect(__chatPageTestables.contextRingTitle(null)).toBe(
      "Context usage pending until the next model response.",
    );
    expect(
      __chatPageTestables.contextRingTitle({
        context_max: 272000,
        context_percent: 11,
        context_used: 29310,
      }),
    ).toBe("Context left: 89%. 11% used. 29,310 / 272,000 tokens until auto-compact");
  });
});

describe("preview shortcuts", () => {
  it("does not swallow preview-open prompts when the artifact is already visible", () => {
    expect(__chatPageTestables.isOpenPreviewIntent("open it")).toBe(true);
    expect(
      __chatPageTestables.shouldHandlePreviewShortcut({
        currentKey: "pdf:listing-plan",
        sidePanel: "preview",
        targetKey: "pdf:listing-plan",
        text: "open it",
      }),
    ).toBe(false);
    expect(
      __chatPageTestables.routePromptForAgent("open it", { previewAlreadyOpen: true }),
    ).toContain("do not answer by saying the preview is open again");
  });

  it("still handles preview-open prompts when the artifact is not already visible", () => {
    expect(
      __chatPageTestables.shouldHandlePreviewShortcut({
        currentKey: "pdf:old-report",
        sidePanel: "preview",
        targetKey: "pdf:new-report",
        text: "open the pdf",
      }),
    ).toBe(true);
    expect(
      __chatPageTestables.shouldHandlePreviewShortcut({
        currentKey: null,
        sidePanel: "none",
        targetKey: "pdf:new-report",
        text: "open the pdf",
      }),
    ).toBe(true);
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
  it("drops a stale streaming placeholder once the server has the completed answer", () => {
    const prompt = "Check the timeline race.";
    const server = [
      message({ content: prompt, createdAt: 1_000, id: "u1", role: "user" }),
      message({ content: "The completed answer with reasoning restored.", createdAt: 2_000, id: "a1", role: "assistant" }),
    ];
    const cached = [
      message({ content: prompt, createdAt: 1_000, id: "cached-u1", role: "user" }),
      message({ content: "", createdAt: 1_010, id: "assistant-live", role: "assistant", status: "streaming" }),
    ];

    const merged = __chatPageTestables.mergeServerWithCache(server, cached, false);

    expect(merged.map((item) => item.id)).toEqual(["u1", "a1"]);
  });

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

describe("turn usage reconciliation", () => {
  it("does not shift an unmatched identified usage row onto a completed answer", () => {
    const completed = {
      content: "Completed answer",
      createdAt: 1_700_000_000_000,
      id: "assistant-complete",
      role: "assistant",
      status: "complete",
    } as TestMessage;

    const joined = __chatPageTestables.joinTurnUsageToMessages([completed], [
      { message_id: "assistant-pre-agent", total_tokens: 19 },
    ]);

    expect(joined.size).toBe(0);
    expect(joined.get(completed.id)).toBeUndefined();
  });

  it("matches exact ids first and reserves positional fallback for id-less rows", () => {
    const messages = [
      {
        content: "First answer",
        createdAt: 1_700_000_000_000,
        id: "assistant-first",
        role: "assistant",
        status: "complete",
      },
      {
        content: "Second answer",
        createdAt: 1_700_000_001_000,
        id: "assistant-second",
        role: "assistant",
        status: "complete",
      },
    ] as TestMessage[];
    const exact = { message_id: "assistant-first", total_tokens: 11 };
    const legacy = { message_id: null, total_tokens: 22 };

    const joined = __chatPageTestables.joinTurnUsageToMessages(messages, [
      exact,
      { message_id: "blocked-before-agent", total_tokens: 99 },
      legacy,
    ]);

    expect(joined.get("assistant-first")).toBe(exact);
    expect(joined.get("assistant-second")).toBe(legacy);
  });
});

describe("terminal truth containment", () => {
  it("folds narrated tool execution into the final logical assistant card", () => {
    const hydrated = __chatPageTestables.normalizeStoredTranscript([
      {
        content: "Check the lead board.",
        message_id: "user-narrated-tool",
        role: "user",
        timestamp: 1_700_000_000,
      },
      {
        content: "I’ll check the lead board now.",
        message_id: "assistant-tool-narration",
        reasoning: "Use the overview tool first.",
        role: "assistant",
        timestamp: 1_700_000_001,
        token_count: 12,
        tool_calls: [
          {
            function: { arguments: "{}", name: "leads_overview" },
            id: "call-narrated-leads",
          },
        ],
      },
      {
        content: '{"success":true,"total":3}',
        role: "tool",
        timestamp: 1_700_000_002,
        tool_call_id: "call-narrated-leads",
        tool_name: "leads_overview",
      },
      {
        content: "There are 3 leads.",
        finish_reason: "stop",
        message_id: "assistant-final-leads",
        reasoning: "Summarize the result.",
        role: "assistant",
        timestamp: 1_700_000_003,
        token_count: 8,
      },
    ]);

    expect(hydrated).toHaveLength(2);
    expect(hydrated[1]).toMatchObject({
      completedAt: 1_700_000_003_000,
      content: "There are 3 leads.",
      createdAt: 1_700_000_000_000,
      status: "complete",
      tokenCount: 20,
    });
    expect(hydrated[1].tools).toMatchObject([
      { name: "leads_overview", status: "done" },
    ]);
    expect(hydrated[1].traces?.map(({ kind, text }) => ({ kind, text }))).toEqual([
      { kind: "reasoning", text: "Use the overview tool first." },
      { kind: "interim", text: "I’ll check the lead board now." },
      { kind: "reasoning", text: "Summarize the result." },
    ]);
    expect(hydrated[1].traces?.every((trace) => trace.messageId === hydrated[1].id))
      .toBe(true);
  });

  it("reports a narrated tool turn with no final answer as unresolved", () => {
    const hydrated = __chatPageTestables.normalizeStoredTranscript([
      { content: "Check the board.", role: "user", timestamp: 1_700_000_000 },
      {
        content: "I’ll check that now.",
        message_id: "assistant-orphaned-narration",
        role: "assistant",
        timestamp: 1_700_000_001,
        token_count: 9,
        tool_calls: [
          {
            function: { arguments: "{}", name: "leads_overview" },
            id: "call-orphaned-leads",
          },
        ],
      },
      {
        content: '{"success":true,"total":3}',
        role: "tool",
        timestamp: 1_700_000_002,
        tool_call_id: "call-orphaned-leads",
        tool_name: "leads_overview",
      },
    ]);

    expect(hydrated).toHaveLength(2);
    expect(hydrated[1]).toMatchObject({
      completedAt: 1_700_000_002_000,
      content: "",
      createdAt: 1_700_000_000_000,
      status: "error",
      tokenCount: 9,
      warning: "Saved turn ended after tool execution without a final assistant response.",
    });
    expect(hydrated[1].tools).toMatchObject([
      { name: "leads_overview", status: "done" },
    ]);
    expect(hydrated[1].traces).toMatchObject([
      { kind: "interim", text: "I’ll check that now." },
    ]);
  });

  it("keeps a partially saved active tool turn streaming without a false error", () => {
    const hydrated = __chatPageTestables.normalizeStoredTranscript(
      [
        { content: "Check the board.", role: "user", timestamp: 1_700_000_000 },
        {
          content: "",
          role: "assistant",
          timestamp: 1_700_000_001,
          tool_calls: [
            {
              function: { arguments: "{}", name: "leads_overview" },
              id: "call-active-leads",
            },
          ],
        },
        {
          content: '{"success":true,"total":3}',
          role: "tool",
          timestamp: 1_700_000_002,
          tool_call_id: "call-active-leads",
          tool_name: "leads_overview",
        },
      ],
      {
        activeAssistantId: "live-assistant",
        turnIsActive: true,
      },
    );

    expect(hydrated).toHaveLength(2);
    expect(hydrated[1]).toMatchObject({
      content: "",
      id: "live-assistant",
      status: "streaming",
    });
    expect(hydrated[1].warning).toBeUndefined();
    expect(hydrated[1].completedAt).toBeUndefined();
    expect(hydrated[1].tools).toMatchObject([
      {
        messageId: "live-assistant",
        name: "leads_overview",
        status: "done",
      },
    ]);
  });

  it("rehydrates one tool turn with the same logical timing and output tokens as live", () => {
    const hydrated = __chatPageTestables.normalizeStoredTranscript([
      {
        content: "Use leads_overview once.",
        message_id: "user-physical",
        role: "user",
        timestamp: 1_700_000_000,
      },
      {
        content: "",
        role: "assistant",
        timestamp: 1_700_000_002.9,
        token_count: 17,
        tool_calls: [
          {
            function: { arguments: '{"recent_limit":1}', name: "leads_overview" },
            id: "call-leads",
          },
        ],
      },
      {
        content: '{"success":true,"overview":{"pendingApproval":0}}',
        role: "tool",
        timestamp: 1_700_000_002.95,
        tool_call_id: "call-leads",
        tool_name: "leads_overview",
      },
      {
        content: "Pending Approval: 0",
        finish_reason: "stop",
        message_id: "assistant-physical",
        role: "assistant",
        timestamp: 1_700_000_003,
        token_count: 30,
      },
    ]);

    expect(hydrated).toHaveLength(2);
    expect(hydrated[1]).toMatchObject({
      completedAt: 1_700_000_003_000,
      createdAt: 1_700_000_000_000,
      status: "complete",
      tokenCount: 47,
    });
    expect(hydrated[1].tools).toMatchObject([
      { name: "leads_overview", status: "done" },
    ]);
  });

  it("does not bleed an unfinished turn's tools or tokens into the next user turn", () => {
    const hydrated = __chatPageTestables.normalizeStoredTranscript([
      { content: "First request", role: "user", timestamp: 1_700_000_000 },
      {
        content: "",
        role: "assistant",
        timestamp: 1_700_000_001,
        token_count: 11,
        tool_calls: [
          {
            function: { arguments: "{}", name: "read_file" },
            id: "orphaned-call",
          },
        ],
      },
      { content: "Second request", role: "user", timestamp: 1_700_000_010 },
      {
        content: "Second answer",
        role: "assistant",
        timestamp: 1_700_000_012,
        token_count: 7,
      },
    ]);

    expect(hydrated.at(-1)).toMatchObject({
      completedAt: 1_700_000_012_000,
      createdAt: 1_700_000_010_000,
      content: "Second answer",
      tokenCount: 7,
    });
    expect(hydrated.at(-1)?.tools).toBeUndefined();
  });

  it("composes timing and token totals across a persisted steer continuation", () => {
    const hydrated = __chatPageTestables.normalizeStoredTranscript([
      { content: "Original request", role: "user", timestamp: 1_700_000_000 },
      {
        content: "First response",
        role: "assistant",
        timestamp: 1_700_000_002,
        token_count: 10,
      },
      {
        content: "Also include retries",
        message_id: "steer.follow-up",
        role: "user",
        timestamp: 1_700_000_003,
      },
      {
        content: "Final response with retries",
        role: "assistant",
        timestamp: 1_700_000_005,
        token_count: 20,
      },
    ]);

    expect(hydrated).toHaveLength(2);
    expect(hydrated[1]).toMatchObject({
      completedAt: 1_700_000_005_000,
      createdAt: 1_700_000_000_000,
      content: "Final response with retries",
      tokenCount: 30,
    });
    expect(hydrated[1].traces?.map((trace) => trace.kind)).toEqual([
      "interim",
      "steer",
      "marker",
    ]);
  });

  it.each([
    ["error", "error"],
    ["interrupted", "interrupted"],
  ] as const)("keeps %s turn timing while preserving terminal status", (finishReason, status) => {
    const hydrated = __chatPageTestables.normalizeStoredTranscript([
      { content: "Run this", role: "user", timestamp: 1_700_000_000 },
      {
        content: "The turn stopped.",
        finish_reason: finishReason,
        role: "assistant",
        timestamp: 1_700_000_004,
        token_count: 3,
      },
    ]);

    expect(hydrated[1]).toMatchObject({
      completedAt: 1_700_000_004_000,
      createdAt: 1_700_000_000_000,
      status,
      tokenCount: 3,
    });
  });

  it.each([
    "Tool execution failed: RuntimeError: worker crashed",
    "[TOOL EXECUTION SKIPPED — read_file was not started]",
  ])("rehydrates anchored plain-text tool failure %s as errored", (toolResult) => {
    const hydrated = __chatPageTestables.normalizeStoredTranscript([
      {
        content: "",
        role: "assistant",
        tool_calls: [
          {
            function: { arguments: "{}", name: "read_file" },
            id: "call-plain-failure",
          },
        ],
      },
      {
        content: toolResult,
        role: "tool",
        tool_call_id: "call-plain-failure",
        tool_name: "read_file",
      },
      { content: "The tool did not complete.", role: "assistant" },
    ]);

    expect(hydrated).toHaveLength(1);
    expect(hydrated[0].status).toBe("error");
    expect(hydrated[0].tools?.[0]).toMatchObject({
      error: toolResult,
      status: "error",
    });
  });

  it("rehydrates failed tools and keeps their assistant turn errored", () => {
    const hydrated = __chatPageTestables.normalizeStoredTranscript([
      {
        content: "",
        role: "assistant",
        tool_calls: [
          {
            function: { arguments: '{"cmd":"false"}', name: "terminal" },
            id: "call-1",
          },
        ],
      },
      {
        content: '{"exit_code":1,"output":"command failed"}',
        role: "tool",
        tool_call_id: "call-1",
        tool_name: "terminal",
      },
      {
        content: "The command did not finish successfully.",
        finish_reason: "stop",
        role: "assistant",
      },
    ]);

    expect(hydrated).toHaveLength(1);
    expect(hydrated[0].status).toBe("error");
    expect(hydrated[0].tools?.[0]).toMatchObject({
      error: "terminal failed [exit 1]",
      status: "error",
    });
  });

  it("never rehydrates a tool call with no stored result as done", () => {
    const hydrated = __chatPageTestables.normalizeStoredTranscript([
      {
        content: "",
        role: "assistant",
        tool_calls: [
          {
            function: { arguments: '{"path":"missing.pdf"}', name: "read_file" },
            id: "call-missing",
          },
        ],
      },
      { content: "The tool result was lost.", role: "assistant" },
    ]);

    expect(hydrated[0].status).toBe("error");
    expect(hydrated[0].tools?.[0]).toMatchObject({
      error: "read_file result missing",
      status: "error",
    });
  });

  it("keeps persisted and live terminal states distinct from clean completion", () => {
    const [failed, interrupted] = __chatPageTestables.normalizeStoredTranscript([
      { content: "Provider failed.", finish_reason: "error", role: "assistant" },
      { content: "Stopped by user.", finish_reason: "interrupted", role: "assistant" },
    ]);

    expect(failed.status).toBe("error");
    expect(interrupted.status).toBe("interrupted");
    expect(
      __chatPageTestables.turnCompletionPresentation("complete", false, true),
    ).toMatchObject({
      messageStatus: "error",
      statusText: "Finished with issues",
      unfinishedToolStatus: "error",
    });
    expect(
      __chatPageTestables.turnCompletionPresentation("interrupted"),
    ).toMatchObject({ messageStatus: "interrupted", statusText: "Interrupted" });
    expect(
      __chatPageTestables.turnCompletionPresentation("pending"),
    ).toMatchObject({
      messageStatus: "pending",
      statusText: "Waiting for completion",
    });
    expect(
      __chatPageTestables.turnCompletionPresentation("incomplete"),
    ).toMatchObject({ messageStatus: "pending" });
    expect(
      __chatPageTestables.turnCompletionPresentation("needs_input"),
    ).toMatchObject({
      messageStatus: "needs_input",
      statusText: "Waiting for your input",
    });
  });
});

describe("background task ordering", () => {
  it("orders finished subagents by completion time instead of start time", () => {
    const sorted = __chatPageTestables.sortBackgroundTasksForDisplay([
      backgroundTask({
        id: "media",
        startedAt: 1_000,
        completedAt: 4_000,
        status: "done",
      }),
      backgroundTask({
        id: "seller-follow-up",
        startedAt: 2_000,
        completedAt: 3_000,
        status: "done",
      }),
      backgroundTask({
        id: "pricing-retry",
        startedAt: 5_000,
        status: "running",
      }),
    ]);

    expect(sorted.map((item) => item.id)).toEqual([
      "pricing-retry",
      "media",
      "seller-follow-up",
    ]);
  });
});
