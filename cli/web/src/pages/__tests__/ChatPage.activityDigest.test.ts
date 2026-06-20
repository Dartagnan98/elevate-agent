import { afterEach, describe, expect, it } from "vitest";

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
});

describe("ChatActivityDigest reasoning persistence", () => {
  it("collapses completed work by default", () => {
    expect(
      __chatPageTestables.defaultActivityDigestOpen({
        busy: false,
        hasErroredStep: false,
        hasSteps: true,
      }),
    ).toBe(false);
  });

  it("keeps live work open but collapses historical work after completion", () => {
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
    expect(completed).toMatchObject({ expanded: false, showSteps: false });
  });

  it("keeps errored completed work expanded for debugging", () => {
    expect(
      __chatPageTestables.resolveActivityDigestVisibility({
        busy: false,
        hasErroredStep: true,
        hasSteps: true,
        userOpen: null,
      }),
    ).toEqual({ expanded: true, showSteps: true });
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

describe("stored transcript hydration", () => {
  it("restores a tool-only turn as an interrupted assistant response", () => {
    const restored = __chatPageTestables.normalizeStoredTranscript([
      {
        content: "Previous answer",
        message_id: "assistant-before",
        role: "assistant",
        timestamp: 1,
      },
      {
        content: "Run QA",
        message_id: "user-qa",
        role: "user",
        timestamp: 2,
      },
      {
        content: "",
        role: "assistant",
        timestamp: 3,
        tool_calls: [
          {
            id: "call-1",
            function: { name: "browser_cdp", arguments: "{}" },
          },
        ],
      },
      {
        content: '{"success":true}',
        role: "tool",
        timestamp: 4,
        tool_call_id: "call-1",
        tool_name: "browser_cdp",
      },
    ]);

    expect(restored).toHaveLength(3);
    expect(restored[0]).toMatchObject({
      content: "Previous answer",
      role: "assistant",
    });
    expect(restored[0].tools).toBeUndefined();
    expect(restored[2]).toMatchObject({
      role: "assistant",
      status: "interrupted",
    });
    expect(restored[2].content).toContain("stopped after tool activity");
    expect(restored[2].tools).toHaveLength(1);
    expect(restored[2].tools?.[0]).toMatchObject({
      messageId: restored[2].id,
      name: "browser_cdp",
    });
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
      __chatPageTestables.shouldClearUsageForStatusUpdate(
        "lifecycle",
        "Working through earlier context so I can continue...",
      ),
    ).toBe(false);
    expect(
      __chatPageTestables.shouldClearUsageForStatusUpdate("session_compacted", "Session compacted"),
    ).toBe(false);
  });

  it("accepts live frames from any owned session id", () => {
    const owned = new Set(["persisted-session", "lineage-root", "gateway-live"]);

    expect(
      __chatPageTestables.shouldAcceptGatewayEventSession(
        "gateway-live",
        "other-live",
        owned,
      ),
    ).toBe(true);
    expect(
      __chatPageTestables.shouldAcceptGatewayEventSession(
        "other-live",
        "other-live",
        owned,
      ),
    ).toBe(true);
    expect(
      __chatPageTestables.shouldAcceptGatewayEventSession(
        "foreign-live",
        "other-live",
        owned,
      ),
    ).toBe(false);
  });

  it("detects an unanswered visible turn after a dropped run", () => {
    const owned = new Set(["chat-1"]);

    expect(
      __chatPageTestables.hasUnfinishedVisibleTurn(
        [
          message({
            id: "user-1",
            role: "user",
            content: "please keep going",
            sessionKey: "chat-1",
          }),
        ],
        owned,
      ),
    ).toBe(true);
    expect(
      __chatPageTestables.hasUnfinishedVisibleTurn(
        [
          message({
            id: "user-1",
            role: "user",
            content: "please keep going",
            sessionKey: "chat-1",
          }),
          message({
            id: "assistant-1",
            role: "assistant",
            content: "",
            status: "streaming",
            sessionKey: "chat-1",
          }),
        ],
        owned,
      ),
    ).toBe(true);
    expect(
      __chatPageTestables.hasUnfinishedVisibleTurn(
        [
          message({
            id: "user-1",
            role: "user",
            content: "please keep going",
            sessionKey: "chat-1",
          }),
          message({
            id: "assistant-1",
            role: "assistant",
            content: "done",
            status: "complete",
            sessionKey: "chat-1",
          }),
        ],
        owned,
      ),
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
    ).toBe("Context left: 89%. 11% used. 29,310 / 272,000 tokens used");
  });
});

describe("blank trace diagnostics", () => {
  const storageKey = "elevate.debug.blankTrace";
  const originalWindowDescriptor = Object.getOwnPropertyDescriptor(globalThis, "window");

  afterEach(() => {
    if (originalWindowDescriptor) {
      Object.defineProperty(globalThis, "window", originalWindowDescriptor);
    } else {
      delete (globalThis as typeof globalThis & { window?: unknown }).window;
    }
  });

  it("stays disabled by default and requires an explicit opt-in", () => {
    expect(__chatPageTestables.isBlankTraceEnabled()).toBe(false);

    const values = new Map<string, string>();
    const fakeWindow = {
      localStorage: {
        getItem: (key: string) => values.get(key) ?? null,
        removeItem: (key: string) => {
          values.delete(key);
        },
        setItem: (key: string, value: string) => {
          values.set(key, value);
        },
      },
    } as { __ELEVATE_BLANK_TRACE__?: unknown; localStorage: Pick<Storage, "getItem" | "removeItem" | "setItem"> };

    Object.defineProperty(globalThis, "window", {
      configurable: true,
      value: fakeWindow,
    });

    expect(__chatPageTestables.isBlankTraceEnabled()).toBe(false);

    fakeWindow.localStorage.setItem(storageKey, "1");
    expect(__chatPageTestables.isBlankTraceEnabled()).toBe(true);

    fakeWindow.localStorage.removeItem(storageKey);
    fakeWindow.__ELEVATE_BLANK_TRACE__ = true;
    expect(__chatPageTestables.isBlankTraceEnabled()).toBe(true);
  });
});

describe("queued disconnected sends", () => {
  it("preserves the already-rendered user bubble id for later submit", () => {
    const restored = __chatPageTestables.normalizeStoredQueue([
      {
        agentId: "executive-assistant",
        createdAt: 123,
        id: "queued-1",
        routedText: "hello",
        status: "queued",
        text: "hello",
        userMessageId: "user-visible-1",
      },
    ]);

    expect(restored).toHaveLength(1);
    expect(__chatPageTestables.queuedInputExistingUserMessageId(restored[0])).toBe(
      "user-visible-1",
    );
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

  it("does not treat queue show-all prompts as preview commands", () => {
    const text =
      "Test the Leads queue deeply. Verify select all across a large filtered queue, show all, skipped sorting, approved/sent refresh, bulk approve, bulk skip, restore, empty states, and failure recovery. Use mocked or disposable data only. Keep a running checklist of each behavior and the evidence that proves it.";

    expect(__chatPageTestables.isOpenPreviewIntent(text)).toBe(false);
    expect(
      __chatPageTestables.shouldHandlePreviewShortcut({
        currentKey: null,
        sidePanel: "none",
        targetKey: "image:browser_screenshot",
        text,
      }),
    ).toBe(false);
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
