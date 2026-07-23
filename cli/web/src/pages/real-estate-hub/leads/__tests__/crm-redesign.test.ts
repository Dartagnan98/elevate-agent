import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";

import type { SourceInboxDraft, SourceInboxProfile } from "@/lib/api-types";
import type { LeadsDraft, LeadsProfile } from "../leads-data";
import { mapLeadsDrafts, mapLeadsProfiles, mapLeadsSent } from "../compute-leads-data";
import {
  crmTemperatureForProfile,
  draftMatchesProfile,
  matchesCrmProfile,
} from "../components/crm-profile-helpers";
import { draftHasRegisteredTransport } from "../components/draft-row";

function profile(overrides: Partial<LeadsProfile> = {}): LeadsProfile {
  return {
    id: "profile-a",
    name: "John Smith",
    heat: 86,
    group: "active",
    verified: true,
    status: "Follow Up",
    source: "Email",
    email: "john@example.com",
    phone: "+12505550199",
    contact: "john@example.com",
    threads: 1,
    age: "2h",
    tags: ["Buyer", "Kamloops"],
    sub: "",
    lastMsg: "Can we see it Saturday?",
    lastTouch: "2h",
    sourceId: "email",
    threadId: "thread-a",
    contactIds: ["contact-a"],
    ...overrides,
  };
}

function draft(overrides: Partial<LeadsDraft> = {}): LeadsDraft {
  return {
    id: "draft-a",
    name: "John Smith",
    source: "Email",
    channel: "EMAIL",
    age: "1h",
    body: "Saturday works. What time is best?",
    heat: "hot",
    sourceId: "email",
    taskId: "task-a",
    contactId: "contact-a",
    threadId: "thread-a",
    ...overrides,
  };
}

describe("CRM actionable draft identity", () => {
  it("does not bind a draft to a different contact with the same display name", () => {
    const sameNameOtherContact = profile({
      id: "profile-b",
      contactIds: ["contact-b"],
      threadId: "thread-b",
    });

    expect(draftMatchesProfile(draft(), sameNameOtherContact)).toBe(false);
  });

  it("binds by contact id or by an exact source-and-thread pair", () => {
    expect(draftMatchesProfile(draft(), profile())).toBe(true);
    expect(draftMatchesProfile(
      draft({ contactId: undefined }),
      profile({ contactIds: [] }),
    )).toBe(true);
    expect(draftMatchesProfile(
      draft({ contactId: undefined, sourceId: "sms" }),
      profile({ contactIds: [] }),
    )).toBe(false);
    expect(draftMatchesProfile(
      draft({ sourceId: undefined, threadId: undefined }),
      profile({ sourceId: undefined, threadId: undefined }),
    )).toBe(true);
  });

  it("does not attach another thread's draft merely because the contact id matches", () => {
    expect(draftMatchesProfile(
      draft({ contactId: "contact-a", sourceId: "email", threadId: "thread-b" }),
      profile({ contactIds: ["contact-a"], sourceId: "email", threadId: "thread-a" }),
    )).toBe(false);
  });

  it("never falls back to a matching name when stable identity is absent", () => {
    expect(draftMatchesProfile(
      draft({ contactId: undefined, threadId: undefined }),
      profile({ contactIds: [], threadId: undefined }),
    )).toBe(false);
  });

  it("carries source identity and the real template label through the mapper", () => {
    const raw = {
      id: "draft-a",
      sourceId: "email",
      sourceLabel: "Email",
      taskId: "task-a",
      threadId: "thread-a",
      contactId: "contact-a",
      personName: "John Smith",
      channel: "email",
      latestText: "",
      latestAt: "2026-07-13T10:00:00Z",
      draftText: "Draft",
      context: "",
      title: "",
      status: "pending",
      approvalRequired: true,
      generated: true,
      templateName: "Buyer showing follow-up",
    } as SourceInboxDraft;

    expect(mapLeadsDrafts([raw])[0]).toMatchObject({
      contactId: "contact-a",
      threadId: "thread-a",
      sourceId: "email",
      taskId: "task-a",
      templateName: "Buyer showing follow-up",
    });
  });

  it("opens the exact source thread that produced the latest profile message", () => {
    const raw = {
      id: "email:john@example.com",
      displayName: "John Smith",
      sources: ["Apple Messages", "Gmail"],
      sourceIds: ["apple-messages", "gmail"],
      channels: ["email", "imessage"],
      contactIds: ["contact-a"],
      conversationIds: ["conversation-a", "conversation-b"],
      verifiers: [],
      phones: [],
      emails: ["john@example.com"],
      threadIds: ["apple-messages:aaa-older", "gmail:zzz-newer"],
      threadCount: 2,
      latestText: "Newest email thread",
      latestAt: "2026-07-13T11:00:00Z",
      latestSourceId: "gmail",
      latestSourceLabel: "Gmail",
      latestThreadId: "zzz-newer",
      heatScore: 55,
      heatLabel: "warm",
      hasCrm: false,
      hasConversation: true,
      isPotentialLead: false,
      crmStage: null,
      leadSource: null,
      tags: [],
      status: null,
      statusUpdatedAt: null,
    } as SourceInboxProfile;

    expect(mapLeadsProfiles([raw])[0]).toMatchObject({
      source: "Gmail",
      sourceId: "gmail",
      threadId: "zzz-newer",
      lastMsg: "Newest email thread",
    });
  });

  it("does not guess a thread from multi-source arrays returned by an older backend", () => {
    const raw = {
      id: "profile-a",
      displayName: "John Smith",
      sources: ["Apple Messages", "Gmail"],
      sourceIds: ["apple-messages", "gmail"],
      channels: ["email", "imessage"],
      contactIds: ["contact-a"],
      conversationIds: [],
      verifiers: [],
      phones: [],
      emails: [],
      threadIds: ["apple-messages:aaa", "gmail:zzz"],
      threadCount: 2,
      latestText: "Latest is unknown",
      latestAt: "2026-07-13T11:00:00Z",
      heatScore: 40,
      heatLabel: "watch",
      hasCrm: false,
      hasConversation: true,
      isPotentialLead: false,
      crmStage: null,
      leadSource: null,
      tags: [],
      status: null,
      statusUpdatedAt: null,
    } as SourceInboxProfile;

    expect(mapLeadsProfiles([raw])[0]).toMatchObject({
      source: "Multiple sources",
      sourceId: undefined,
      threadId: undefined,
    });
  });

  it("fails closed in the UI when a draft channel has no real transport", () => {
    expect(draftHasRegisteredTransport(draft({ channel: "SMS" }))).toBe(true);
    expect(draftHasRegisteredTransport(draft({ channel: "text" }))).toBe(true);
    expect(draftHasRegisteredTransport(draft({ channel: "iMessage" }))).toBe(true);
    expect(draftHasRegisteredTransport(draft({ channel: "Apple Messages" }))).toBe(true);
    expect(draftHasRegisteredTransport(draft({ channel: "Messages" }))).toBe(true);
    expect(draftHasRegisteredTransport(draft({ channel: "EMAIL" }))).toBe(false);
    expect(draftHasRegisteredTransport(draft({ channel: "Gmail" }))).toBe(false);
    expect(draftHasRegisteredTransport(draft({ channel: "SOCIAL_DM" }))).toBe(false);
    expect(draftHasRegisteredTransport(draft({ channel: "CRM_NOTE" }))).toBe(false);

    const row = readFileSync(new URL("../components/draft-row.tsx", import.meta.url), "utf8");
    expect(row).toContain("Boolean(approveBlockedReason)");
    expect(row).toContain("transport unavailable");
    expect(row).toContain("Cannot send");
  });
});

describe("CRM lead filters", () => {
  it("uses the visible heat thresholds when there is no activity timestamp", () => {
    expect(crmTemperatureForProfile(profile({ heat: 80 }))).toBe("hot");
    expect(crmTemperatureForProfile(profile({ heat: 50 }))).toBe("warm");
    expect(crmTemperatureForProfile(profile({ heat: 49 }))).toBe("cool");
  });

  it("derives the follow-up segment from days since last activity", () => {
    const daysAgo = (n: number) => new Date(Date.now() - n * 24 * 60 * 60 * 1000).toISOString();
    expect(crmTemperatureForProfile(profile({ heat: 0, latestAt: daysAgo(10) }))).toBe("hot");
    expect(crmTemperatureForProfile(profile({ heat: 0, latestAt: daysAgo(60) }))).toBe("warm");
    expect(crmTemperatureForProfile(profile({ heat: 0, latestAt: daysAgo(120) }))).toBe("lukewarm");
    expect(crmTemperatureForProfile(profile({ heat: 0, latestAt: daysAgo(250) }))).toBe("cool");
    expect(crmTemperatureForProfile(profile({ heat: 0, latestAt: daysAgo(400) }))).toBe("nurture");
  });

  it("routes closed and past-client relationships to SOI regardless of recency", () => {
    const daysAgo = (n: number) => new Date(Date.now() - n * 24 * 60 * 60 * 1000).toISOString();
    expect(crmTemperatureForProfile(profile({ heat: 0, status: "Closed", latestAt: daysAgo(2) }))).toBe("soi");
    expect(crmTemperatureForProfile(profile({ heat: 0, status: "Closed Buyer", latestAt: daysAgo(500) }))).toBe("soi");
    expect(crmTemperatureForProfile(profile({ heat: 0, tags: ["Past Client"], latestAt: daysAgo(40) }))).toBe("soi");
  });

  it("keeps source, pipeline, temperature, tags, and search in one predicate", () => {
    expect(matchesCrmProfile(profile(), {
      sourceFilter: "email",
      pipelineFilter: "Follow Up",
      temperatureFilter: "hot",
      tagFilters: ["buyer", "kamloops"],
      searchQuery: "+1250",
    })).toBe(true);
    expect(matchesCrmProfile(profile(), {
      sourceFilter: "email",
      pipelineFilter: "Follow Up",
      temperatureFilter: "hot",
      tagFilters: ["Seller"],
      searchQuery: "",
    })).toBe(false);
  });
});

describe("CRM truth guards", () => {
  it("never presents sandbox or queue status as confirmed delivery", () => {
    const accepted = mapLeadsSent([{
      id: "send-1",
      idempotencyKey: "key-1",
      sourceId: "email",
      threadId: "thread-1",
      taskId: "task-1",
      channel: "email",
      payload: { draft_text: "Hello" },
      status: "sent",
      attempts: 1,
      nextRetryAt: null,
      lastError: null,
      providerMessageId: "provider-1",
      attemptId: null,
      createdAt: "2026-07-13T10:00:00Z",
      updatedAt: "2026-07-13T10:00:01Z",
    }]);
    const simulated = mapLeadsSent([{
      id: "send-2",
      idempotencyKey: "key-2",
      sourceId: "crm",
      threadId: "thread-2",
      taskId: "task-2",
      channel: "crm_note",
      payload: { draft_text: "Hello" },
      status: "sent",
      attempts: 1,
      nextRetryAt: null,
      lastError: null,
      providerMessageId: "stub-crm_note-123",
      attemptId: null,
      createdAt: "2026-07-13T10:00:00Z",
      updatedAt: "2026-07-13T10:00:01Z",
    }]);

    expect(accepted[0].status).toBe("dispatch accepted");
    expect(simulated[0]).toMatchObject({ status: "simulated — not sent", transport: "STUB" });
  });

  it("does not render demo fallbacks when live source data is absent", () => {
    const board = readFileSync(new URL("../components/leads-board.tsx", import.meta.url), "utf8");
    expect(board).not.toContain("DEFAULT_PROFILES");
    expect(board).not.toContain("DEFAULT_DRAFTS");
    // Migration 0036: the reader appends CRM-only/manual contacts, so the
    // list is a full directory and the note must say so honestly.
    expect(board).toContain("Full directory: every contact on record is listed");
  });

  it("offers Send later now that the backend persists scheduledAt (next_retry_at)", () => {
    // Migration 0035 era: approve accepts scheduledAt, the send_queue row is
    // held by next_retry_at, and the app's cron sender tick delivers it. The
    // scheduler must exist, validate the future, and never show on a blocked draft.
    const row = readFileSync(new URL("../components/draft-row.tsx", import.meta.url), "utf8");
    expect(row).toContain('type="datetime-local"');
    expect(row).toContain("Send later");
    expect(row).toContain("Pick a date and time in the future.");
    expect(row).toContain("schedulerOpen && !approveBlockedReason");
    expect(row).toContain('onAction?.("approve", editedDraft, when.toISOString())');
    expect(row).toContain("aria-checked={selected}");
  });

  it("keeps queue actions individual and removes unsupported automation claims", () => {
    const queue = readFileSync(new URL("../components/action-queue.tsx", import.meta.url), "utf8");
    expect(queue).not.toContain("handleBulkAction");
    expect(queue).not.toContain("Draft reply");
    expect(queue).not.toContain("Select all");
    expect(queue).not.toContain("~1h");
    expect(queue).not.toContain("re-enter this queue automatically");
    expect(queue).toContain("Review each recipient separately");
  });

  it("does not fabricate a profile when a queue item lacks a stable thread match", () => {
    const board = readFileSync(new URL("../components/leads-board.tsx", import.meta.url), "utf8");
    expect(board).not.toContain("heat: 80");
    expect(board).not.toContain("verified: false");
    expect(board).toContain("Source refresh failed");
    expect(board).toContain("Refreshing source inbox");
    expect(board).toContain("Source inbox ready");
    expect(board).toContain("Source inbox not loaded");
  });

  it("keeps source onboarding available without hiding the CRM board", () => {
    const shell = readFileSync(new URL("../LeadsDesignShell.tsx", import.meta.url), "utf8");
    const hubPage = readFileSync(new URL("../../../RealEstateHubPages.tsx", import.meta.url), "utf8");
    expect(shell).toContain("forceOnboarding");
    expect(shell).toContain("The CRM remains available");
    expect(shell).not.toContain("!setupSnapshot.complete || forceOnboarding");
    expect(hubPage).toContain("export function RealEstateLeadsPage() {\n  return <LeadsDesignShell />;\n}");
  });

  it("never converts delivery-history failures into a success-shaped empty state", () => {
    const notSent = readFileSync(new URL("../components/not-sent-view.tsx", import.meta.url), "utf8");
    const sent = readFileSync(new URL("../components/sent-view.tsx", import.meta.url), "utf8");
    const dataHook = readFileSync(new URL("../use-leads-board-data.ts", import.meta.url), "utf8");

    expect(notSent).toContain("Didn't-send history is unavailable");
    expect(notSent).not.toContain("every recent message went out");
    expect(notSent).toContain("retrySendOutcomeLabel");
    expect(notSent).not.toContain('? "Sent"');
    expect(sent).toContain('type="checkbox"');
    expect(sent).toContain("Older messages may not be included");
    expect(dataHook).toContain("setSentRaw(null)");
    expect(dataHook).toContain("setTemplatesRaw(null)");
  });

  it("tracks an approval through its exact send endpoint before refreshing history", () => {
    const api = readFileSync(new URL("../../../../lib/api.ts", import.meta.url), "utf8");
    const board = readFileSync(new URL("../components/leads-board.tsx", import.meta.url), "utf8");
    const dataHook = readFileSync(new URL("../use-leads-board-data.ts", import.meta.url), "utf8");

    expect(api).toContain("getSourceInboxDraftSendStatus");
    expect(api).toContain("/send-status`");
    expect(api).toContain('{ cache: "no-store" }');
    expect(dataHook).toContain("pollExactDraftSendStatus");
    expect(dataHook).toContain("draft.threadId");
    expect(dataHook).toContain("draftSendNotices");
    expect(board).toContain("Approved draft send status");
    expect(board).toContain("notice.message");
  });

  it("announces status-save failures inside the contact dialog", () => {
    const drawer = readFileSync(new URL("../components/profile-drawer.tsx", import.meta.url), "utf8");
    expect(drawer).toContain("statusError");
    expect(drawer).toContain("Saving lead status");
    expect(drawer).toContain('role="alert"');
  });

  it("lets refreshed canonical profile status replace every prior UI value", () => {
    const board = readFileSync(new URL("../components/leads-board.tsx", import.meta.url), "utf8");
    const profiles = readFileSync(new URL("../components/profiles-list.tsx", import.meta.url), "utf8");

    expect(board).not.toContain("statusOverrides");
    expect(profiles).not.toContain("statusOverrides");
    expect(board).toContain("profile={activeProfileFromLive}");
    expect(profiles).toContain("const profiles = profilesProp;");
  });

  it("provides a no-save exit from every forced onboarding dialog", () => {
    const launch = readFileSync(new URL("../onboarding.tsx", import.meta.url), "utf8");
    const welcome = readFileSync(new URL("../onboarding-shell.tsx", import.meta.url), "utf8");
    const wizard = readFileSync(new URL("../onboarding-wizard.tsx", import.meta.url), "utf8");

    expect(launch.match(/onClose=\{onForceOnboardingDone\}/g)).toHaveLength(2);
    expect(launch).not.toContain('phase === "form"');
    for (const dialog of [welcome, wizard]) {
      expect(dialog).toContain('event.key === "Escape"');
      expect(dialog).toContain("onClick={onClose}");
      expect(dialog).toContain("Back to CRM");
      expect(dialog).not.toContain("completeLeadsSetup");
    }
  });
});
