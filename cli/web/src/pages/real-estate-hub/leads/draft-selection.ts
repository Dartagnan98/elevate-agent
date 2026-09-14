import type { LeadsDraft, LeadsProfile } from "./leads-data";

// A displayed name is never a recipient identifier. Require an unambiguous
// contact match, or an exact source/thread match when no contact ID exists.
export function indexProfileDrafts(profiles: LeadsProfile[], drafts: LeadsDraft[]) {
  const index = new Map<string, LeadsDraft[]>();
  const seen = new Set<string>();
  for (const draft of drafts) {
    if (seen.has(draft.id)) continue;
    seen.add(draft.id);

    // Prefer a real contact ID match when the draft and profile use the same
    // identifier namespace. Some CRM drafts carry the provider lead id while
    // DB-backed profiles carry the internal contact UUID, so fall back to the
    // exact source/thread pair only when the contact id produced no match.
    const contactMatches = draft.contactId
      ? profiles.filter((p) => p.id === draft.contactId || p.contactIds?.includes(draft.contactId!))
      : [];
    const providerContactIdCanFallback = Boolean(
      !draft.contactId || (draft.threadId && draft.threadId.includes(draft.contactId)),
    );
    const matches = contactMatches.length > 0
      ? contactMatches
      : providerContactIdCanFallback
        ? profiles.filter((p) => Boolean(draft.sourceId && draft.threadId && (
          p.threadIds?.includes(`${draft.sourceId}:${draft.threadId}`) ||
          (p.sourceId === draft.sourceId && p.threadId === draft.threadId)
        )))
        : [];

    if (matches.length !== 1) continue;
    const id = matches[0].id;
    index.set(id, [...(index.get(id) || []), draft]);
  }
  return index;
}

export function sameReviewedDraft(a: LeadsDraft, b: LeadsDraft) {
  return a.id === b.id && a.sourceId === b.sourceId && a.taskId === b.taskId &&
    a.contactId === b.contactId && a.threadId === b.threadId &&
    a.channel === b.channel && a.body === b.body;
}

// Sequential submission preserves individual results and stops on uncertainty.
// A network failure must never trigger an automatic retry of an approval.
export async function submitReviewedDrafts(
  drafts: LeadsDraft[],
  submit: (draft: LeadsDraft) => Promise<void>,
  onAccepted: (draft: LeadsDraft) => void,
) {
  const accepted: string[] = [];
  for (const draft of drafts) {
    if (accepted.includes(draft.id)) continue;
    try {
      await submit(draft);
      accepted.push(draft.id);
      onAccepted(draft);
    } catch (error) {
      return { accepted, stoppedAt: draft.id,
        error: error instanceof Error ? error.message : "Could not confirm approval. Check Sent and Didn't Send before trying again." };
    }
  }
  return { accepted, stoppedAt: null, error: null };
}
