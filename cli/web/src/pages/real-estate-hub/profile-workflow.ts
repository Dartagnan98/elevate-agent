import type {
  AdminDealSide,
  AgentHandoff,
  SourceInboxProfile,
  SourceInboxProfileVerifier,
  SourceInboxThread,
} from "@/lib/api";

export function profileSortTime(profile: SourceInboxProfile): number {
  const ms = Date.parse(profile.latestAt || "");
  return Number.isFinite(ms) ? ms : 0;
}

export function profileContactLine(profile: SourceInboxProfile): string {
  const contacts = [...profile.phones.slice(0, 1), ...profile.emails.slice(0, 1)];
  return contacts.length ? contacts.join(" · ") : "No phone or email yet";
}

export type ProfileAdminDealIds = Partial<Record<AdminDealSide, string>>;

export type ProfilePendingAdminAction = {
  profileId: string;
  side: AdminDealSide;
};

export type ProfileHandoffIds = Partial<Record<AdminDealSide, AgentHandoff>>;

export type ProfileActionBucketId = "active-conversation" | "push-admin" | "needs-verifier" | "follow-up" | "in-admin";

export const PROFILE_WORKFLOW_JOB_PREFIX = "Lead profile workflow";

export const PROFILE_ACTION_BUCKETS: Array<{
  id: ProfileActionBucketId;
  label: string;
  description: string;
}> = [
  {
    id: "active-conversation",
    label: "Active conversations",
    description: "People they are actively messaging stay first, sorted by the newest conversation activity.",
  },
  {
    id: "push-admin",
    label: "Ready for skill handoff",
    description: "Verified hot or potential leads ready for a buyer workflow or seller CMA before Admin handoff.",
  },
  {
    id: "needs-verifier",
    label: "Needs phone or email",
    description: "People with useful conversation context but no matching verifier yet.",
  },
  {
    id: "follow-up",
    label: "Follow up",
    description: "Lower-urgency profiles to review, message, or keep watching from the source inbox.",
  },
  {
    id: "in-admin",
    label: "Already in Admin",
    description: "Profiles already pushed into Buyers Admin, Sellers Admin, or both.",
  },
];

export const PROFILE_ADMIN_SIDE_COPY = {
  listing: {
    actionLabel: "Run CMA skill",
    queuedLabel: "CMA queued",
    openLabel: "Open Sellers",
    badgeLabel: "Sellers Admin",
    queuedBadgeLabel: "CMA skill queued",
    workflow: "seller-cma-admin",
    skill: "cma",
    workflowLabel: "Seller CMA",
    errorLabel: "CMA skill",
  },
  buyer: {
    actionLabel: "Run buyer skill",
    queuedLabel: "Buyer queued",
    openLabel: "Open Buyers",
    badgeLabel: "Buyers Admin",
    queuedBadgeLabel: "buyer skill queued",
    workflow: "buyer-admin-intake",
    skill: "outreach",
    workflowLabel: "Buyer qualification",
    errorLabel: "buyer workflow",
  },
} satisfies Record<
  AdminDealSide,
  {
    actionLabel: string;
    queuedLabel: string;
    openLabel: string;
    badgeLabel: string;
    queuedBadgeLabel: string;
    workflow: string;
    skill: string;
    workflowLabel: string;
    errorLabel: string;
  }
>;

export function profileWorkflowToken(side: AdminDealSide): string {
  return side === "listing" ? "seller-cma" : "buyer-admin";
}

export function profileSkillWorkflowName(profile: SourceInboxProfile, side: AdminDealSide): string {
  const name = profile.displayName?.trim() || "New profile";
  return `${PROFILE_WORKFLOW_JOB_PREFIX}: ${profileWorkflowToken(side)}: ${name}: ${profile.id}`;
}

export function profileHandoffSide(handoff: AgentHandoff): AdminDealSide | null {
  const payload = handoff.payload ?? {};
  const side = payload.targetSide;
  if (side === "listing" || side === "buyer") return side;
  const workflow = String(payload.workflow ?? "").toLowerCase();
  if (workflow.includes("seller") || workflow.includes("listing")) return "listing";
  if (workflow.includes("buyer")) return "buyer";
  const title = handoff.title.toLowerCase();
  if (title.includes("seller-cma")) return "listing";
  if (title.includes("buyer-admin")) return "buyer";
  return null;
}

export function profileHandoffIsActive(handoff: AgentHandoff | undefined): boolean {
  if (!handoff) return false;
  return ["queued", "running", "waiting_human"].includes(String(handoff.status));
}

export function profileHandoffBadgeLabel(handoff: AgentHandoff | undefined, side: AdminDealSide): string | null {
  if (!handoff) return null;
  const label = PROFILE_ADMIN_SIDE_COPY[side].workflowLabel;
  if (handoff.status === "completed") return `${label} done`;
  if (handoff.status === "failed") return `${label} failed`;
  if (handoff.status === "cancelled") return `${label} cancelled`;
  if (handoff.status === "waiting_human") return `${label} waiting`;
  return PROFILE_ADMIN_SIDE_COPY[side].queuedBadgeLabel;
}

export function profileSkillWorkflowContext(profile: SourceInboxProfile, side: AdminDealSide): string {
  const sideCopy = PROFILE_ADMIN_SIDE_COPY[side];
  return JSON.stringify(
    {
      profileId: profile.id,
      targetSide: side,
      workflow: sideCopy.workflow,
      skill: sideCopy.skill,
      displayName: profile.displayName,
      primaryContactId: profilePrimaryContactId(profile),
      contactIds: profile.contactIds ?? [],
      conversationIds: profile.conversationIds ?? [],
      threadIds: profile.threadIds,
      sourceIds: profile.sourceIds,
      sources: profile.sources,
      channels: profile.channels,
      phones: profile.phones,
      emails: profile.emails,
      verifiers: profileVerifiers(profile),
      latestText: profile.latestText,
      latestAt: profile.latestAt,
      heatScore: profile.heatScore,
      heatLabel: profile.heatLabel,
      tags: profile.tags,
      sourceMeta: profileSourceMeta(profile),
    },
    null,
    2,
  );
}

export function profileSkillWorkflowPrompt(profile: SourceInboxProfile, side: AdminDealSide): string {
  const sideCopy = PROFILE_ADMIN_SIDE_COPY[side];
  const context = profileSkillWorkflowContext(profile, side);
  if (side === "listing") {
    return `Run the seller CMA handoff for this lead profile.

Profile context:
${context}

Workflow rules:
1. This is a skill-owned handoff, not a direct dashboard push to Sellers Admin.
2. Confirm from the profile, thread history, or source records that there is enough seller appointment/property context to run the CMA.
3. If the property address or appointment context is missing, draft or queue the next same-channel follow-up needed to get it. Do not fabricate missing details and do not create an Admin record yet.
4. Once the appointment/property context is present, run the installed CMA skill workflow. Preserve CMA handoffs and generated artifacts.
5. Only after the CMA outputs are complete, use the admin_profile tool with action=promote, side=listing, profile_id=${profile.id}, workflow=${sideCopy.workflow}, profile_context from above, and the available verifiers/contact ids. Do not create a duplicate deal manually.
6. Hand control to Admin by using the Admin stage mutation after the record exists. Move or re-enter the listing card at Admin stage 0 (CMA / Prospect) unless the CMA outcome clearly belongs in a later listing stage. This stage event is what lets the Admin action registry run next.
7. Leave a concise run note explaining whether the person stayed in lead follow-up or moved into CMA/Admin.`;
  }

  return `Run the buyer qualification handoff for this lead profile.

Profile context:
${context}

Workflow rules:
1. This is a skill-owned handoff, not a direct dashboard push to Buyers Admin.
2. Use the outreach/lead context to determine whether a buyer appointment, qualification, financing, search criteria, or follow-up is still needed.
3. If qualification details are missing, draft or queue the next same-channel message needed to collect them. Do not fabricate budget, financing, timeline, or area criteria.
4. After the buyer workflow has enough appointment and qualification context, use the admin_profile tool with action=promote, side=buyer, profile_id=${profile.id}, workflow=${sideCopy.workflow}, profile_context from above, and the available verifiers/contact ids. Do not create a duplicate deal manually.
5. Hand control to Admin by using the Admin stage mutation after the record exists. Move or re-enter the buyer card at Admin stage 0 (Intake) unless the qualification outcome clearly belongs in a later buyer stage. This stage event is what lets the Admin action registry run next.
6. Leave a concise run note explaining whether the person stayed in lead follow-up or moved into Buyers Admin.`;
}

export function profileSourceMeta(profile: SourceInboxProfile): string {
  const sources = profile.sources.length ? profile.sources.slice(0, 2).join(" + ") : "Source inbox";
  const channels = profile.channels.length ? profile.channels.slice(0, 2).join(" + ") : "unknown channel";
  return `${sources} / ${channels}`;
}

export function profilePrimaryContactId(profile: SourceInboxProfile): string | null {
  return profile.contactIds?.[0] ?? null;
}

export function profileVerifiers(profile: SourceInboxProfile): SourceInboxProfileVerifier[] {
  return (profile.verifiers ?? []).filter((verifier) => verifier.key && verifier.value);
}

export function verifierSummary(verifiers: SourceInboxProfileVerifier[]): string {
  const kinds = Array.from(new Set(verifiers.map((verifier) => verifier.kind))).sort();
  if (!kinds.length) return "needs phone/email";
  return `verified by ${kinds.join(" + ")}`;
}

export function profileVerifierSummary(profile: SourceInboxProfile): string {
  return verifierSummary(profileVerifiers(profile));
}

export function profileHasVerifier(profile: SourceInboxProfile): boolean {
  return profileVerifiers(profile).length > 0;
}

export function profileHasAdminDeal(dealIds?: ProfileAdminDealIds): boolean {
  return Boolean(dealIds?.listing || dealIds?.buyer);
}

export function threadSortTime(thread: SourceInboxThread): number {
  const ms = Date.parse(thread.latestAt || "");
  return Number.isFinite(ms) ? ms : 0;
}

export function isActiveProfileThread(thread: SourceInboxThread): boolean {
  const status = String(thread.status || "open").toLowerCase();
  return status !== "done" && status !== "archived";
}

export function profileHasActiveConversation(
  profile: SourceInboxProfile,
  threadsForProfile?: SourceInboxThread[],
): boolean {
  if (!profile.hasConversation || profile.threadCount < 1) return false;
  if (!threadsForProfile?.length) return true;
  return threadsForProfile.some(isActiveProfileThread);
}

export function profileActionBucket(
  profile: SourceInboxProfile,
  dealIds?: ProfileAdminDealIds,
  activeConversation = false,
): ProfileActionBucketId {
  if (activeConversation) return "active-conversation";
  if (profileHasAdminDeal(dealIds)) return "in-admin";
  if (!profileHasVerifier(profile)) return "needs-verifier";
  if (profile.isPotentialLead || profile.heatLabel === "hot" || profile.heatLabel === "warm") return "push-admin";
  return "follow-up";
}

export function profileActionSort(a: SourceInboxProfile, b: SourceInboxProfile): number {
  if (a.isPotentialLead !== b.isPotentialLead) return a.isPotentialLead ? -1 : 1;
  const heat = (b.heatScore ?? 0) - (a.heatScore ?? 0);
  if (heat !== 0) return heat;
  return profileSortTime(b) - profileSortTime(a);
}

export function profileConversationSort(a: SourceInboxProfile, b: SourceInboxProfile): number {
  const recency = profileSortTime(b) - profileSortTime(a);
  if (recency !== 0) return recency;
  const heat = (b.heatScore ?? 0) - (a.heatScore ?? 0);
  if (heat !== 0) return heat;
  return a.displayName.localeCompare(b.displayName);
}
