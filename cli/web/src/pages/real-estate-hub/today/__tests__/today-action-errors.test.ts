import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const here = dirname(fileURLToPath(import.meta.url));
const shell = readFileSync(resolve(here, "../TodayDesignShell.tsx"), "utf8");
const board = readFileSync(resolve(here, "../components/today-board.tsx"), "utf8");
const threadDrawer = readFileSync(resolve(here, "../../thread-drawer.tsx"), "utf8");
const profileDrawer = readFileSync(resolve(here, "../../leads/components/profile-drawer.tsx"), "utf8");
const leadsBoard = readFileSync(resolve(here, "../../leads/components/leads-board.tsx"), "utf8");

describe("today draft action failures", () => {
  it("surfaces failed quick approvals and keeps failed drafts retryable", () => {
    expect(shell).toContain("todayActionError");
    expect(shell).toContain("Could not ${verb} draft");
    expect(shell).toContain("throw err instanceof Error ? err : new Error(detail)");
    expect(shell).toContain("error={todayActionError || todayError}");

    expect(board).toContain('role="alert"');
    expect(board).toContain("Parent surfaces the action error; keep the draft visible for retry.");
    expect(board).toContain("if (action === \"skip\") setSkipped");
  });

  it("keeps Today approvals visible through exact terminal send status", () => {
    expect(shell).toContain("initialDraftSendLifecycleState");
    expect(shell).toContain("pollExactDraftSendStatus");
    expect(shell).toContain("getSourceInboxDraftSendStatus");
    expect(shell).toContain("draftApprovalBlockedReason");
    expect(shell).toContain("draftSendNotices={draftSendNotices}");

    expect(board).toContain("Today approved draft send status");
    expect(board).toContain("notice.message");
    expect(board).toContain("approvalBlockedReason");
    expect(board).toContain("Processing…");
  });

  it("keeps the shared thread drawer open until exact status is visible", () => {
    expect(threadDrawer).toContain("initialDraftSendLifecycleState");
    expect(threadDrawer).toContain("pollExactDraftSendStatus");
    expect(threadDrawer).toContain("getSourceInboxDraftSendStatus");
    expect(threadDrawer).toContain("draftApprovalBlockedReason");
    expect(threadDrawer).toContain("approvalInProgress");
    expect(threadDrawer).toContain("requestClose");
    expect(threadDrawer).toContain('if (action === "skip")');
    expect(threadDrawer).toContain("setSendLifecycle(terminal)");
    expect(threadDrawer).toContain("pendingDraft: null");
    expect(threadDrawer).toContain("Checking exact status…");
  });

  it("renders the Leads contact-drawer lifecycle above its modal", () => {
    expect(leadsBoard).toContain("draftSendNotices={draftSendNotices}");
    expect(profileDrawer).toContain("trackedDraftId");
    expect(profileDrawer).toContain("trackedDraftSendNotice");
    expect(profileDrawer).toContain("approvalInProgress");
    expect(profileDrawer).toContain("requestClose");
    expect(profileDrawer).toContain("trackedDraftSendNotice.message");
  });
});
