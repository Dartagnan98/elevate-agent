import { useCallback, useEffect, useMemo, useState } from "react";
import { useRealEstateHubData } from "@/pages/real-estate-hub/_shared";
import { api } from "@/lib/api";
import type {
  OutreachTemplate,
  SourceInboxProfileStatus,
  SourceInboxResponse,
  SourceInboxSentItem,
} from "@/lib/api-types";
import type { LeadsDraft, LeadsDraftAction, LeadsProfile } from "./leads-data";
import {
  draftApprovalBlockedReason,
  initialDraftSendLifecycleState,
  pollExactDraftSendStatus,
  type DraftSendLifecycleNotice,
  type DraftSendLifecycleState,
} from "./draft-send-lifecycle";
import {
  computeLeadsKpis,
  mapLeadsDrafts,
  mapLeadsPipeline,
  mapLeadsProfiles,
  mapLeadsSent,
  mapLeadsSources,
  mapLeadsTemplates,
} from "./compute-leads-data";

export function sourceInboxDebugNote(inbox: SourceInboxResponse | null): string | null {
  const debug = inbox?.debug;
  if (!debug) return null;

  const { counts } = debug;
  const total =
    counts.profiles +
    counts.threads +
    counts.drafts +
    counts.skippedDrafts +
    counts.privateSearchBuyers;
  if (!debug.fallback && total > 0) return null;

  const note = `Source inbox read: ${debug.readPath} | ${counts.threads} threads | ${counts.drafts} drafts | ${counts.profiles} profiles | ${counts.skippedDrafts} skipped | ${counts.privateSearchBuyers} private buyers`;
  if (!debug.fallback) return note;
  return debug.fallbackError ? `${note} | fallback: ${debug.fallbackError}` : `${note} | fallback`;
}

export function sourceInboxProfileStatusForLabel(label: string): SourceInboxProfileStatus | null | undefined {
  const key = label.trim().toLowerCase();
  if (key === "no status") return null;
  if (key === "new lead") return "new_lead";
  if (key === "follow up") return "follow_up";
  if (key === "ghosting") return "ghosting";
  if (key === "dead") return "dead";
  if (key === "closed seller") return "closed_seller";
  if (key === "closed buyer") return "closed_buyer";
  return undefined;
}

export function useLeadsBoardData() {
  const data = useRealEstateHubData();
  const inbox = data.sourceInbox;
  const setSourceInbox = data.setSourceInbox;
  const [templatesRaw, setTemplatesRaw] = useState<OutreachTemplate[] | null>(null);
  const [sentRaw, setSentRaw] = useState<SourceInboxSentItem[] | null>(null);
  const [templatesLoading, setTemplatesLoading] = useState(true);
  const [templatesError, setTemplatesError] = useState<string | null>(null);
  const [sentLoading, setSentLoading] = useState(true);
  const [sentError, setSentError] = useState<string | null>(null);
  const [sentPartial, setSentPartial] = useState(false);
  const [draftSendLifecycleById, setDraftSendLifecycleById] = useState<Record<string, DraftSendLifecycleNotice>>({});

  const refreshTemplates = useCallback(async () => {
    setTemplatesLoading(true);
    setTemplatesError(null);
    try {
      const res = await api.getOutreachTemplates();
      setTemplatesRaw(res.templates ?? []);
    } catch (error) {
      setTemplatesRaw(null);
      setTemplatesError(error instanceof Error ? error.message : "Template history did not load.");
      throw error;
    } finally {
      setTemplatesLoading(false);
    }
  }, []);

  const refreshSent = useCallback(async (includePending = false) => {
    setSentLoading(true);
    setSentError(null);
    try {
      const res = await api.getSourceInboxSent(100, includePending);
      const items = res.items ?? [];
      const effectiveLimit = Math.max(1, Math.min(Number(res.limit) || 100, 100));
      setSentRaw(items);
      setSentPartial(items.length >= effectiveLimit);
    } catch (error) {
      setSentRaw(null);
      setSentPartial(false);
      setSentError(error instanceof Error ? error.message : "Outbound history did not load.");
      throw error;
    } finally {
      setSentLoading(false);
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    api
      .getOutreachTemplates()
      .then((res) => {
        if (!cancelled) {
          setTemplatesRaw(res.templates ?? []);
          setTemplatesError(null);
        }
      })
      .catch((error) => {
        if (!cancelled) {
          setTemplatesRaw(null);
          setTemplatesError(error instanceof Error ? error.message : "Template history did not load.");
        }
      })
      .finally(() => {
        if (!cancelled) setTemplatesLoading(false);
      });
    api
      .getSourceInboxSent(100)
      .then((res) => {
        if (!cancelled) {
          const items = res.items ?? [];
          const effectiveLimit = Math.max(1, Math.min(Number(res.limit) || 100, 100));
          setSentRaw(items);
          setSentPartial(items.length >= effectiveLimit);
          setSentError(null);
        }
      })
      .catch((error) => {
        if (!cancelled) {
          setSentRaw(null);
          setSentPartial(false);
          setSentError(error instanceof Error ? error.message : "Outbound history did not load.");
        }
      })
      .finally(() => {
        if (!cancelled) setSentLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const templateMutations = useMemo(
    () => ({
      onCreate: async (laneId: string, name: string, body: string) => {
        await api.createOutreachTemplate({ lane: laneId, name, body });
        await refreshTemplates();
      },
      onSave: async (id: string, name: string, body: string) => {
        await api.updateOutreachTemplate(id, { name, body });
        await refreshTemplates();
      },
      onTogglePause: async (id: string, active: boolean) => {
        await api.updateOutreachTemplate(id, { active });
        await refreshTemplates();
      },
      onDelete: async (id: string) => {
        await api.deleteOutreachTemplate(id);
        await refreshTemplates();
      },
      onSuggest: async (laneId: string) => {
        const res = await api.suggestOutreachTemplate({ lane: laneId });
        await refreshTemplates();
        return { name: res.template.name, body: res.template.body };
      },
    }),
    [refreshTemplates],
  );

  const sources = useMemo(
    () =>
      inbox ? mapLeadsSources(inbox.sources ?? [], inbox.drafts ?? [], inbox.threads ?? []) : undefined,
    [inbox],
  );
  const drafts = useMemo(
    () => (inbox ? mapLeadsDrafts(inbox.drafts ?? []) : undefined),
    [inbox],
  );
  const profiles = useMemo(
    () => (inbox ? mapLeadsProfiles(inbox.profiles ?? []) : undefined),
    [inbox],
  );
  const pipeline = useMemo(
    () =>
      inbox
        ? mapLeadsPipeline(
            inbox.drafts ?? [],
            inbox.skippedDrafts ?? [],
            inbox.privateSearchBuyers ?? [],
            inbox.leadSections,
            inbox.profiles ?? [],
            inbox.threads ?? [],
          )
        : undefined,
    [inbox],
  );
  const kpis = useMemo(
    () => (inbox ? computeLeadsKpis(inbox.drafts ?? [], inbox.profiles ?? []) : undefined),
    [inbox],
  );
  const templates = useMemo(
    () => (templatesRaw ? mapLeadsTemplates(templatesRaw) : undefined),
    [templatesRaw],
  );
  const sent = useMemo(
    () => (sentRaw ? mapLeadsSent(sentRaw) : undefined),
    [sentRaw],
  );
  const draftSendNotices = useMemo(
    () => Object.values(draftSendLifecycleById)
      .sort((left, right) => left.updatedAt - right.updatedAt)
      .slice(-4),
    [draftSendLifecycleById],
  );

  const updateDraftSendLifecycle = useCallback((draft: LeadsDraft, state: DraftSendLifecycleState) => {
    setDraftSendLifecycleById((current) => ({
      ...current,
      [draft.id]: {
        ...state,
        draftId: draft.id,
        draftName: draft.name,
        updatedAt: Date.now(),
      },
    }));
  }, []);

  const handleToggleDirection = useCallback(
    async (dir: "inbound" | "outbound", value: boolean) => {
      try {
        await api.setAppleMessagesDirections({ [dir]: value });
        await data.refresh({ force: true });
      } catch (err) {
        console.error("apple messages direction toggle failed", err);
        throw err;
      }
    },
    [data],
  );

  const handleDraftAction = useCallback(
    async (action: LeadsDraftAction, draft: LeadsDraft, scheduledAt?: string) => {
      const sourceId = draft.sourceId;
      const taskId = draft.taskId;
      const threadId = draft.threadId;
      if (!sourceId || !taskId) throw new Error("Draft is missing source/task identifiers.");
      const approvalBlockedReason = action === "approve" ? draftApprovalBlockedReason(draft) : null;
      if (approvalBlockedReason) {
        throw new Error(approvalBlockedReason);
      }
      if (action === "approve") updateDraftSendLifecycle(draft, initialDraftSendLifecycleState());
      try {
        const res = await api.updateSourceInboxDraft(
          sourceId, taskId, action, draft.body ?? "",
          scheduledAt ? { scheduledAt } : undefined,
        );
        setSourceInbox(res);
        if (action === "approve" && threadId) {
          const terminal = await pollExactDraftSendStatus(
            (remainingMs) => api.getSourceInboxDraftSendStatus(sourceId, threadId, taskId, { timeoutMs: remainingMs }),
            { onProgress: (state) => updateDraftSendLifecycle(draft, state) },
          );
          updateDraftSendLifecycle(draft, terminal);
        }
      } catch (err) {
        if (action === "approve") {
          const detail = err instanceof Error ? err.message : "approval request failed";
          updateDraftSendLifecycle(draft, {
            phase: "unknown",
            status: null,
            message: `Approval/send outcome is unknown — ${detail}`,
          });
        }
        console.error("draft action failed", err);
        throw err;
      }
    },
    [setSourceInbox, updateDraftSendLifecycle],
  );

  const handleDraftActionComplete = useCallback(
    async (action: LeadsDraftAction) => {
      if (action === "approve") await refreshSent(false);
    },
    [refreshSent],
  );

  const handleProfileFavoriteChange = useCallback(
    async (profile: LeadsProfile, favorite: boolean) => {
      try {
        const res = await api.updateSourceInboxProfileFavorite(profile.id, favorite, {
          contactId: profile.contactIds?.[0] ?? null,
        });
        setSourceInbox(res);
      } catch (err) {
        console.error("favorite toggle failed", err);
        throw err;
      }
    },
    [setSourceInbox],
  );

  const handleProfileStatusChange = useCallback(
    async (profile: LeadsProfile, label: string) => {
      const status = sourceInboxProfileStatusForLabel(label);
      if (status === undefined) throw new Error(`Unsupported lead status: ${label}`);
      const res = await api.updateSourceInboxProfile(profile.id, status);
      setSourceInbox(res);
    },
    [setSourceInbox],
  );

  return {
    data,
    inbox,
    sources,
    drafts,
    profiles,
    pipeline,
    kpis,
    templates,
    templatesState: {
      error: templatesError,
      loading: templatesLoading,
    },
    sent,
    sentState: {
      error: sentError,
      loading: sentLoading,
      partial: sentPartial,
      limit: 100,
    },
    debugNote: sourceInboxDebugNote(inbox),
    draftSendNotices,
    handleDraftAction,
    handleDraftActionComplete,
    handleProfileFavoriteChange,
    handleProfileStatusChange,
    handleToggleDirection,
    refreshSent,
    templateMutations,
  };
}
