import { useCallback, useEffect, useMemo, useState } from "react";
import { useRealEstateHubData } from "@/pages/real-estate-hub/_shared";
import { api } from "@/lib/api";
import type {
  OutreachTemplate,
  SourceInboxResponse,
  SourceInboxSentItem,
} from "@/lib/api-types";
import type { LeadsDraft, LeadsDraftAction, LeadsProfile } from "./leads-data";
import { pipelineSlugForLabel } from "./pipeline-stages";
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

// Map an operator-picked status-pill label to the slug to persist. Handles
// Skyleigh's 9 stages plus the legacy labels older rows may still show.
// Returns null to clear, undefined for an unrecognized label.
export function sourceInboxProfileStatusForLabel(label: string): string | null | undefined {
  return pipelineSlugForLabel(label);
}

export function useLeadsBoardData() {
  const data = useRealEstateHubData();
  const inbox = data.sourceInbox;
  const setSourceInbox = data.setSourceInbox;
  const [templatesRaw, setTemplatesRaw] = useState<OutreachTemplate[] | null>(null);
  const [sentRaw, setSentRaw] = useState<SourceInboxSentItem[] | null>(null);
  const [tempOverrides, setTempOverrides] = useState<Record<string, string>>({});

  const refreshTemplates = useCallback(async () => {
    const res = await api.getOutreachTemplates();
    setTemplatesRaw(res.templates ?? []);
  }, []);

  const refreshSent = useCallback(async (includePending = false) => {
    const res = await api.getSourceInboxSent(100, includePending);
    setSentRaw(res.items ?? []);
  }, []);

  useEffect(() => {
    let cancelled = false;
    api
      .getOutreachTemplates()
      .then((res) => {
        if (!cancelled) setTemplatesRaw(res.templates ?? []);
      })
      .catch(() => {
        if (!cancelled) setTemplatesRaw([]);
      });
    api
      .getSourceInboxSent(100)
      .then((res) => {
        if (!cancelled) setSentRaw(res.items ?? []);
      })
      .catch(() => {
        if (!cancelled) setSentRaw([]);
      });
    api
      .getAdminContactTemperatures()
      .then((res) => {
        if (!cancelled) setTempOverrides(res.overrides ?? {});
      })
      .catch(() => {
        if (!cancelled) setTempOverrides({});
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
    () => (inbox ? mapLeadsProfiles(inbox.profiles ?? [], tempOverrides) : undefined),
    [inbox, tempOverrides],
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
      if (!draft.sourceId || !draft.taskId) throw new Error("Draft is missing source/task identifiers.");
      try {
        // For a channel switch, draft.channel carries the TARGET channel the
        // toggle picked (e.g. "sms" or "email"); everything else sends the body.
        const options =
          action === "channel"
            ? { channel: draft.channel }
            : scheduledAt
              ? { scheduledAt }
              : undefined;
        const res = await api.updateSourceInboxDraft(
          draft.sourceId, draft.taskId, action, draft.body ?? "",
          options,
        );
        setSourceInbox(res);
      } catch (err) {
        console.error("draft action failed", err);
        throw err;
      }
    },
    [setSourceInbox],
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

  // Bulk tag/segment/pipeline change from the redesigned Leads table selection
  // bar. Fans the selected profiles out to their contactIds, calls the bulk
  // endpoint, then refreshes so the board reflects the write.
  const handleBulkUpdate = useCallback(
    async (
      profiles: LeadsProfile[],
      action: "tags" | "segments" | "pipeline",
      value: unknown,
      mode?: "add" | "replace" | "remove",
    ) => {
      const contactIds = Array.from(
        new Set(profiles.flatMap((p) => p.contactIds ?? []).filter(Boolean)),
      );
      if (contactIds.length === 0) {
        throw new Error("None of the selected leads have a linked contact to update.");
      }
      const res = await api.bulkUpdateContacts(contactIds, action, value, mode);
      await data.refresh({ force: true });
      return res;
    },
    [data],
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
    sent,
    debugNote: sourceInboxDebugNote(inbox),
    handleDraftAction,
    handleDraftActionComplete,
    handleProfileFavoriteChange,
    handleProfileStatusChange,
    handleBulkUpdate,
    handleToggleDirection,
    refreshSent,
    templateMutations,
  };
}
