import { useEffect, useId, useMemo, useRef, useState } from "react";

import { api } from "@/lib/api";
import type { ContactNote, ContactTask, CrmColumn, ThreadContextResponse } from "@/lib/api-types";
import type { LeadsDraft, LeadsDraftAction, LeadsProfile } from "../leads-data";
import type { DraftSendLifecycleNotice } from "../draft-send-lifecycle";
import { CRM_TEMPERATURE_LABELS, crmTemperatureForProfile } from "./crm-profile-helpers";
import { DraftRow } from "./draft-row";
import { StatusPill } from "./profile-status";

type ContactTab = "overview" | "searches" | "properties" | "documents" | "automations";

const CONTACT_TABS: Array<{ id: ContactTab; label: string }> = [
  { id: "overview", label: "Overview" },
  { id: "searches", label: "Searches" },
  { id: "properties", label: "Properties" },
  { id: "documents", label: "Documents" },
  { id: "automations", label: "Automations" },
];

const UNDER_CONSTRUCTION: Partial<Record<ContactTab, { title: string; body: string }>> = {
  properties: {
    title: "Properties",
    body: "Homes this contact has actually engaged with — viewed, favorited, shown, or sent, each with a status. On the build list.",
  },
  documents: {
    title: "Documents",
    body: "Pre-approvals and signed files attached to the person instead of buried in a drive. On the build list.",
  },
  automations: {
    title: "Automations",
    body: "Where drip campaigns will live — multi-step text + email follow-up that stops the moment they reply. Coming after the core card.",
  },
};

const TAG_GROUPS: Array<{ label: string; tags: string[] }> = [
  { label: "Property needs", tags: ["First-time buyer", "Upsizing", "Downsizing", "Investor", "Suite / income", "Move-in ready"] },
  { label: "Financial", tags: ["Pre-approved", "Needs to sell first", "$500k max", "$750k max", "$1M+ max"] },
  { label: "Location", tags: ["Kamloops", "Kelowna", "Wants rural", "Urban core"] },
  { label: "Relationship", tags: ["SOI", "Past Client", "Referral", "Open House Lead", "PPC Lead", "Sign Call"] },
  { label: "Buying window", tags: ["Spring 2026", "Fall 2026", "Winter 2026"] },
  { label: "Mortgage renewal", tags: ["Renewal 2027", "Renewal 2030"] },
];

interface SearchCriteriaForm {
  priceRange: string;
  propertyType: string;
  bedrooms: string;
  bathrooms: string;
  parking: string;
  timeline: string;
  areas: string;
  notes: string;
}

const EMPTY_CRITERIA: SearchCriteriaForm = {
  priceRange: "", propertyType: "", bedrooms: "", bathrooms: "",
  parking: "", timeline: "", areas: "", notes: "",
};

function parseCriteria(raw: string | null | undefined): SearchCriteriaForm {
  if (!raw) return EMPTY_CRITERIA;
  try {
    const parsed = JSON.parse(raw) as Partial<SearchCriteriaForm> | null;
    if (!parsed || typeof parsed !== "object") return EMPTY_CRITERIA;
    return { ...EMPTY_CRITERIA, ...Object.fromEntries(
      Object.entries(parsed).filter(([key, value]) => key in EMPTY_CRITERIA && typeof value === "string"),
    ) };
  } catch {
    return EMPTY_CRITERIA;
  }
}

type TimelineItem = {
  id: string;
  kind: "message-in" | "message-out" | "note" | "activity" | "send";
  label: string;
  title: string;
  body: string;
  timestamp: string | null;
};

function timestampValue(value: string | null | undefined): number {
  if (!value) return 0;
  const parsed = new Date(value).getTime();
  return Number.isFinite(parsed) ? parsed : 0;
}

function formatTime(value: string | null | undefined): string {
  if (!value) return "Time unavailable";
  const parsed = new Date(value);
  if (!Number.isFinite(parsed.getTime())) return "Time unavailable";
  return parsed.toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}

function buildConversationTimeline(context: ThreadContextResponse | null, profile: LeadsProfile): TimelineItem[] {
  if (!context) return [];
  const items: TimelineItem[] = [];

  for (const message of context.messages || []) {
    const outbound = message.direction === "outbound";
    items.push({
      id: `message:${message.id}`,
      kind: outbound ? "message-out" : "message-in",
      label: outbound ? "Text sent" : "Text received",
      title: outbound ? "You" : message.sender || profile.name,
      body: message.text || "Message text unavailable.",
      timestamp: message.timestamp,
    });
  }
  for (const note of context.notes || []) {
    items.push({
      id: `note:${note.id}`,
      kind: "note",
      label: "Note",
      title: note.author || note.title || "CRM note",
      body: note.summary || note.title || "Note details unavailable.",
      timestamp: note.timestamp,
    });
  }
  for (const activity of context.activity || []) {
    items.push({
      id: `activity:${activity.id}`,
      kind: "activity",
      label: (activity.type || "Activity").replace(/_/g, " "),
      title: activity.title || "CRM activity",
      body: activity.summary || activity.address || "Activity details unavailable.",
      timestamp: activity.timestamp,
    });
  }
  for (const send of context.sends || []) {
    const body = send.payload?.text || send.payload?.body || "Outbound content unavailable.";
    items.push({
      id: `send:${send.id}`,
      kind: "send",
      label: `${(send.channel || "outbound").toUpperCase()} · ${send.status || "unknown"}`,
      title: "Delivery record",
      body,
      timestamp: send.updatedAt || send.createdAt,
    });
  }
  return items.sort((a, b) => timestampValue(b.timestamp) - timestampValue(a.timestamp));
}

export function ProfileDrawer({
  profile,
  draft,
  onClose,
  onStatusChange,
  onFavoriteChange,
  onTop25Change,
  onTagsChange,
  customColumns = [],
  onContactSaved,
  onDraftAction,
  onDraftActionComplete,
  draftSendNotices = [],
  onEditTemplate,
}: {
  profile: LeadsProfile;
  draft?: LeadsDraft;
  onClose: () => void;
  onStatusChange?: (profile: LeadsProfile, value: string) => void | Promise<void>;
  onFavoriteChange?: (profile: LeadsProfile, favorite: boolean) => void | Promise<void>;
  onTop25Change?: (profile: LeadsProfile, top25: boolean) => void | Promise<void>;
  onTagsChange?: (profile: LeadsProfile, tags: string[]) => void | Promise<void>;
  customColumns?: CrmColumn[];
  onContactSaved?: () => void;
  onDraftAction?: (action: LeadsDraftAction, draft: LeadsDraft, scheduledAt?: string) => void | Promise<void>;
  onDraftActionComplete?: (action: LeadsDraftAction) => void | Promise<void>;
  draftSendNotices?: DraftSendLifecycleNotice[];
  onEditTemplate?: () => void;
}) {
  const titleId = useId();
  const drawerRef = useRef<HTMLElement | null>(null);
  const closeRef = useRef<HTMLButtonElement | null>(null);
  const [context, setContext] = useState<ThreadContextResponse | null>(null);
  const [loadingContext, setLoadingContext] = useState(Boolean(profile.sourceId && profile.threadId));
  const [contextError, setContextError] = useState<string | null>(null);
  const [favoriteBusy, setFavoriteBusy] = useState(false);
  const [favoriteError, setFavoriteError] = useState<string | null>(null);
  const [statusBusy, setStatusBusy] = useState(false);
  const [statusError, setStatusError] = useState<string | null>(null);
  const [draftBusy, setDraftBusy] = useState(false);
  const [draftError, setDraftError] = useState<string | null>(null);
  const [trackedDraftId, setTrackedDraftId] = useState<string | null>(null);
  const [tab, setTab] = useState<ContactTab>("overview");
  const [notes, setNotes] = useState<ContactNote[] | null>(null);
  const [notesError, setNotesError] = useState<string | null>(null);
  const [noteText, setNoteText] = useState("");
  const [noteBusy, setNoteBusy] = useState(false);
  const [composeMode, setComposeMode] = useState<"note" | "text" | "email">("note");
  const [top25Busy, setTop25Busy] = useState(false);
  const [top25Error, setTop25Error] = useState<string | null>(null);
  const [tagPickerOpen, setTagPickerOpen] = useState(false);
  const [tagBusy, setTagBusy] = useState(false);
  const [tagError, setTagError] = useState<string | null>(null);
  const [customTag, setCustomTag] = useState("");
  const [criteria, setCriteria] = useState<SearchCriteriaForm>(() => parseCriteria(profile.searchCriteria));
  const [criteriaBusy, setCriteriaBusy] = useState(false);
  const [criteriaNotice, setCriteriaNotice] = useState<string | null>(null);
  const [editOpen, setEditOpen] = useState(false);
  const [editForm, setEditForm] = useState(() => ({
    displayName: profile.name === "Unnamed contact" ? "" : profile.name,
    primaryEmail: profile.email || "",
    primaryPhone: profile.phone || "",
    type: profile.contactType || "unclassified",
    consentText: profile.consent?.text ?? true,
    consentCall: profile.consent?.call ?? true,
    consentEmail: profile.consent?.email ?? true,
    customFields: { ...(profile.customFields || {}) } as Record<string, string>,
  }));
  const [editBusy, setEditBusy] = useState(false);
  const [editNotice, setEditNotice] = useState<string | null>(null);
  const [taskTitle, setTaskTitle] = useState("");
  const [taskDue, setTaskDue] = useState("");
  const [taskBusy, setTaskBusy] = useState(false);
  const [taskError, setTaskError] = useState<string | null>(null);
  const [contactTasks, setContactTasks] = useState<ContactTask[] | null>(null);
  const contactId = profile.contactIds?.[0] ?? null;

  useEffect(() => {
    if (!contactId) return;
    let cancelled = false;
    api.getContactTasks(contactId)
      .then((result) => { if (!cancelled) setContactTasks(result.tasks || []); })
      .catch(() => undefined);
    return () => { cancelled = true; };
  }, [contactId]);

  const refetchTasks = async () => {
    if (!contactId) return;
    try {
      const result = await api.getContactTasks(contactId);
      setContactTasks(result.tasks || []);
    } catch {
      /* keep the current list on refresh failure */
    }
  };

  const handleSaveDetails = async () => {
    if (!contactId || editBusy) return;
    setEditBusy(true);
    setEditNotice(null);
    try {
      await api.updateSourceInboxContact({
        contactId,
        displayName: editForm.displayName.trim() || undefined,
        primaryEmail: editForm.primaryEmail.trim() || undefined,
        primaryPhone: editForm.primaryPhone.trim() || undefined,
        type: editForm.type,
        cannotText: !editForm.consentText,
        cannotCall: !editForm.consentCall,
        cannotEmail: !editForm.consentEmail,
        customFields: editForm.customFields,
      });
      setEditNotice("Saved.");
      onContactSaved?.();
    } catch (error) {
      setEditNotice(error instanceof Error ? error.message : "Could not save the contact.");
    } finally {
      setEditBusy(false);
    }
  };

  const handleAddTask = async () => {
    const title = taskTitle.trim();
    if (!title || !contactId || taskBusy) return;
    setTaskBusy(true);
    setTaskError(null);
    try {
      await api.createContactTask(contactId, title, taskDue.trim() || undefined);
      setTaskTitle("");
      setTaskDue("");
      await refetchTasks();
    } catch (error) {
      setTaskError(error instanceof Error ? error.message : "Could not add the task.");
    } finally {
      setTaskBusy(false);
    }
  };

  const handleToggleTask = async (taskId: string, done: boolean) => {
    if (taskBusy) return;
    setTaskBusy(true);
    setTaskError(null);
    try {
      await api.setContactTaskStatus(taskId, done ? "done" : "open");
      await refetchTasks();
    } catch (error) {
      setTaskError(error instanceof Error ? error.message : "Could not update the task.");
    } finally {
      setTaskBusy(false);
    }
  };
  const trackedDraftSendNotice = trackedDraftId
    ? draftSendNotices.find((notice) => notice.draftId === trackedDraftId) ?? null
    : null;
  const approvalInProgress = Boolean(
    trackedDraftId
    && draftBusy
    && (!trackedDraftSendNotice || trackedDraftSendNotice.phase === "pending"),
  );

  const requestClose = () => {
    if (approvalInProgress) {
      setDraftError("Approval is still processing. Wait for the exact send result before closing this contact.");
      return;
    }
    onClose();
  };

  useEffect(() => {
    const previousOverflow = document.body.style.overflow;
    const previouslyFocused = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    document.body.style.overflow = "hidden";
    window.requestAnimationFrame(() => closeRef.current?.focus());
    return () => {
      document.body.style.overflow = previousOverflow;
      previouslyFocused?.focus();
    };
  }, []);

  useEffect(() => {
    const sourceId = profile.sourceId || "";
    const threadId = profile.threadId || "";
    if (!sourceId || !threadId) return;

    let cancelled = false;
    api.getThreadContext(sourceId, threadId)
      .then((result) => { if (!cancelled) setContext(result); })
      .catch((error: { message?: string }) => {
        if (!cancelled) setContextError(error?.message || "Could not load this conversation.");
      })
      .finally(() => { if (!cancelled) setLoadingContext(false); });
    return () => { cancelled = true; };
  }, [profile.sourceId, profile.threadId]);

  const handleDialogKeyDown = (event: React.KeyboardEvent<HTMLElement>) => {
    if (event.key === "Escape") {
      event.preventDefault();
      requestClose();
      return;
    }
    if (event.key !== "Tab" || !drawerRef.current) return;
    const focusable = Array.from(drawerRef.current.querySelectorAll<HTMLElement>(
      'button:not([disabled]), a[href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
    )).filter((element) => !element.hasAttribute("hidden"));
    if (focusable.length === 0) return;
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  };

  const handleFavorite = async () => {
    if (!onFavoriteChange) return;
    setFavoriteBusy(true);
    setFavoriteError(null);
    try {
      await onFavoriteChange(profile, !profile.favorite);
    } catch (error) {
      setFavoriteError(error instanceof Error ? error.message : "Could not update favorite.");
    } finally {
      setFavoriteBusy(false);
    }
  };

  const handleStatus = async (value: string) => {
    if (!onStatusChange) return;
    setStatusBusy(true);
    setStatusError(null);
    try {
      await onStatusChange(profile, value);
    } catch (error) {
      setStatusError(error instanceof Error ? error.message : "Could not update lead status.");
    } finally {
      setStatusBusy(false);
    }
  };

  useEffect(() => {
    if (!contactId) return;
    let cancelled = false;
    api.getSourceInboxNotes(contactId)
      .then((result) => { if (!cancelled) setNotes(result.notes || []); })
      .catch((error: { message?: string }) => {
        if (!cancelled) setNotesError(error?.message || "Could not load notes.");
      });
    return () => { cancelled = true; };
  }, [contactId]);

  const refreshNotes = async () => {
    if (!contactId) return;
    try {
      const result = await api.getSourceInboxNotes(contactId);
      setNotes(result.notes || []);
      setNotesError(null);
    } catch (error) {
      setNotesError(error instanceof Error ? error.message : "Could not load notes.");
    }
  };

  const handleAddNote = async () => {
    const text = noteText.trim();
    if (!text || !contactId || noteBusy) return;
    setNoteBusy(true);
    try {
      await api.createSourceInboxNote(contactId, text);
      setNoteText("");
      await refreshNotes();
    } catch (error) {
      setNotesError(error instanceof Error ? error.message : "Could not save the note.");
    } finally {
      setNoteBusy(false);
    }
  };

  const handlePinNote = async (note: ContactNote) => {
    if (noteBusy) return;
    setNoteBusy(true);
    try {
      await api.pinSourceInboxNote(note.id, !note.pinned);
      await refreshNotes();
    } catch (error) {
      setNotesError(error instanceof Error ? error.message : "Could not pin the note.");
    } finally {
      setNoteBusy(false);
    }
  };

  const handleTop25 = async () => {
    if (!onTop25Change) return;
    setTop25Busy(true);
    setTop25Error(null);
    try {
      await onTop25Change(profile, !profile.top25);
    } catch (error) {
      setTop25Error(error instanceof Error ? error.message : "Could not update Top 25.");
    } finally {
      setTop25Busy(false);
    }
  };

  const handleToggleTag = async (tag: string) => {
    if (!onTagsChange || tagBusy) return;
    const current = profile.tags || [];
    const next = current.includes(tag)
      ? current.filter((item) => item !== tag)
      : [...current, tag];
    setTagBusy(true);
    setTagError(null);
    try {
      await onTagsChange(profile, next);
    } catch (error) {
      setTagError(error instanceof Error ? error.message : "Could not update tags.");
    } finally {
      setTagBusy(false);
    }
  };

  const handleAddCustomTag = async () => {
    const tag = customTag.trim();
    if (!tag) return;
    setCustomTag("");
    await handleToggleTag(tag);
  };

  const handleSaveCriteria = async () => {
    if (!contactId || criteriaBusy) return;
    setCriteriaBusy(true);
    setCriteriaNotice(null);
    try {
      const payload = Object.fromEntries(
        Object.entries(criteria).filter(([, value]) => value.trim() !== ""),
      );
      await api.updateSearchCriteria(contactId, Object.keys(payload).length ? payload : null);
      setCriteriaNotice("Saved.");
    } catch (error) {
      setCriteriaNotice(error instanceof Error ? error.message : "Could not save criteria.");
    } finally {
      setCriteriaBusy(false);
    }
  };

  const handleDraftAction = async (action: LeadsDraftAction, nextDraft: LeadsDraft, scheduledAt?: string) => {
    if (!onDraftAction) return;
    if (action === "approve") setTrackedDraftId(nextDraft.id);
    setDraftBusy(true);
    setDraftError(null);
    try {
      await onDraftAction(action, nextDraft, scheduledAt);
      await onDraftActionComplete?.(action);
      setDraftError(null);
    } catch (error) {
      setDraftError(error instanceof Error ? error.message : `Could not ${action} draft.`);
    } finally {
      setDraftBusy(false);
    }
  };

  const timeline = useMemo(() => buildConversationTimeline(context, profile), [context, profile]);
  const lead = context?.lead;
  const tags = lead?.tags?.length ? lead.tags : profile.tags;
  const emails = lead?.emails?.length ? lead.emails : (profile.email ? [profile.email] : []);
  const phones = lead?.phones?.length ? lead.phones : (profile.phone ? [profile.phone] : []);
  const owner = lead?.assignedUser || context?.source.ownerAgent || "Unassigned";
  const temperature = crmTemperatureForProfile(profile);
  const initials = profile.name.split(/\s+/).map((part) => part[0]).filter(Boolean).slice(0, 2).join("").toUpperCase();
  const hasConversationIdentity = Boolean(profile.sourceId && profile.threadId);

  return (
    <div className="lb-drawer-backdrop crm-contact-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) requestClose(); }}>
      <aside
        ref={drawerRef}
        className="lb-drawer crm-contact-card"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        onKeyDown={handleDialogKeyDown}
      >
        <header className="crm-contact-head">
          <div className="crm-contact-identity">
            <div className="crm-contact-avatar" data-tone={temperature} aria-hidden="true">{initials}</div>
            <div>
              <div className="crm-contact-name-row">
                <h2 id={titleId}>{profile.name}</h2>
                {profile.verified && <span className="crm-verified">✓ Verified</span>}
                {profile.favorite && <span className="crm-favorite-badge">★ Favorite</span>}
                {profile.top25 && <span className="crm-top25-badge">★ Top 25</span>}
              </div>
              <p>{profile.source}{lead?.leadSource ? ` · ${lead.leadSource}` : ""}</p>
              <div className="crm-contact-inline-details">
                {emails[0] && <a href={`mailto:${emails[0]}`}>{emails[0]}</a>}
                {phones[0] && <a href={`tel:${phones[0]}`}>{phones[0]}</a>}
              </div>
            </div>
          </div>
          <div className="crm-contact-head-actions">
            {onStatusChange
              ? <StatusPill status={profile.status} onChange={(value) => void handleStatus(value)} disabled={statusBusy} />
              : <span className="lb-profile-status">{profile.status || "No status"}</span>}
            {statusBusy && <span className="sr-only" role="status">Saving lead status…</span>}
            {onFavoriteChange && (
              <button type="button" className="crm-favorite-button" onClick={() => void handleFavorite()} disabled={favoriteBusy} aria-pressed={Boolean(profile.favorite)}>
                {favoriteBusy ? "Saving…" : profile.favorite ? "★ Favorited" : "☆ Favorite"}
              </button>
            )}
            {onTop25Change && (
              <button
                type="button"
                className={"crm-top25-button" + (profile.top25 ? " on" : "")}
                onClick={() => void handleTop25()}
                disabled={top25Busy}
                aria-pressed={Boolean(profile.top25)}
                title="Top 25 leads get their own view on the admin board for special-care follow-up."
              >
                {top25Busy ? "Saving…" : profile.top25 ? "★ In Top 25" : "☆ Add to Top 25"}
              </button>
            )}
            {contactId && (
              <button
                type="button"
                className="crm-favorite-button crm-edit-details-toggle"
                aria-expanded={editOpen}
                onClick={() => { setEditNotice(null); setEditOpen((open) => !open); }}
              >
                {editOpen ? "Close editor" : "✎ Edit details"}
              </button>
            )}
            <button
              ref={closeRef}
              type="button"
              className="lb-drawer-close"
              onClick={requestClose}
              disabled={approvalInProgress}
              title={approvalInProgress ? "Wait for the exact send result before closing" : undefined}
              aria-label={`Close ${profile.name}`}
            >×</button>
          </div>
        </header>

        {(statusError || favoriteError || draftError || top25Error || tagError) && (
          <div className="crm-contact-error" role="alert">
            {statusError || favoriteError || draftError || top25Error || tagError}
          </div>
        )}
        {trackedDraftSendNotice && (
          <div
            className={trackedDraftSendNotice.phase === "failed" || trackedDraftSendNotice.phase === "timeout" || trackedDraftSendNotice.phase === "unknown"
              ? "crm-contact-error"
              : "crm-contact-scope"}
            role={trackedDraftSendNotice.phase === "failed" || trackedDraftSendNotice.phase === "timeout" || trackedDraftSendNotice.phase === "unknown" ? "alert" : "status"}
            aria-live="polite"
          >
            <strong>{trackedDraftSendNotice.draftName}</strong> · {trackedDraftSendNotice.message}
          </div>
        )}
        <div className="crm-contact-scope" role="note">
          {hasConversationIdentity
            ? `Conversation details are from the selected ${profile.source} thread. Other channels may appear separately.`
            : "No conversation identifier is attached to this lead, so only list-level CRM details are available."}
        </div>

        <div className="crm-contact-tabs" role="tablist" aria-label="Contact sections">
          {CONTACT_TABS.map((item) => (
            <button
              key={item.id}
              type="button"
              role="tab"
              id={`${titleId}-tab-${item.id}`}
              aria-selected={tab === item.id}
              aria-controls={`${titleId}-panel-${item.id}`}
              className={tab === item.id ? "on" : ""}
              onClick={() => setTab(item.id)}
            >
              {item.label}
            </button>
          ))}
        </div>

        {editOpen && contactId && (
          <section className="crm-contact-section crm-edit-details" aria-label={`Edit details for ${profile.name}`}>
            <div className="crm-section-heading">
              <div><span className="crm-section-kicker">Edit details</span><h3>Contact record</h3></div>
              <button
                type="button"
                className="crm-criteria-save"
                onClick={() => void handleSaveDetails()}
                disabled={editBusy}
              >
                {editBusy ? "Saving…" : "Save"}
              </button>
            </div>
            {editNotice && <div className={editNotice === "Saved." ? "crm-contact-scope" : "crm-contact-error"} role="status">{editNotice}</div>}
            <div className="crm-criteria-grid">
              <label className="crm-criteria-field">
                <span>Name</span>
                <input type="text" value={editForm.displayName} onChange={(event) => setEditForm((c) => ({ ...c, displayName: event.target.value }))} />
              </label>
              <label className="crm-criteria-field">
                <span>Lead type</span>
                <select value={editForm.type} onChange={(event) => setEditForm((c) => ({ ...c, type: event.target.value }))}>
                  <option value="buyer">Buyer</option>
                  <option value="listing">Seller</option>
                  <option value="other">Other</option>
                  <option value="unclassified">Unclassified</option>
                </select>
              </label>
              <label className="crm-criteria-field">
                <span>Email</span>
                <input type="email" value={editForm.primaryEmail} onChange={(event) => setEditForm((c) => ({ ...c, primaryEmail: event.target.value }))} />
              </label>
              <label className="crm-criteria-field">
                <span>Phone</span>
                <input type="tel" value={editForm.primaryPhone} onChange={(event) => setEditForm((c) => ({ ...c, primaryPhone: event.target.value }))} />
              </label>
              {customColumns.map((column) => (
                <label key={column.key} className="crm-criteria-field">
                  <span>{column.label}</span>
                  <input
                    type="text"
                    value={editForm.customFields[column.key] || ""}
                    onChange={(event) => setEditForm((c) => ({
                      ...c,
                      customFields: { ...c.customFields, [column.key]: event.target.value },
                    }))}
                  />
                </label>
              ))}
              <div className="crm-criteria-field crm-criteria-notes">
                <span>Consent to contact · applied to every send</span>
                <div className="crm-consent-toggles">
                  {([
                    ["consentCall", "Call"],
                    ["consentText", "Text"],
                    ["consentEmail", "Email"],
                  ] as const).map(([key, label]) => (
                    <label key={key} className="crm-consent-toggle">
                      <input
                        type="checkbox"
                        checked={editForm[key]}
                        onChange={(event) => setEditForm((c) => ({ ...c, [key]: event.target.checked }))}
                      />
                      <span>{label}</span>
                    </label>
                  ))}
                </div>
              </div>
            </div>
          </section>
        )}

        {tab !== "overview" && tab !== "searches" && (
          <div
            className="crm-contact-uc"
            role="tabpanel"
            id={`${titleId}-panel-${tab}`}
            aria-labelledby={`${titleId}-tab-${tab}`}
          >
            <span aria-hidden="true">🚧</span>
            <strong>{UNDER_CONSTRUCTION[tab]?.title}</strong>
            <p>{UNDER_CONSTRUCTION[tab]?.body}</p>
          </div>
        )}

        {tab === "searches" && (
          <div
            className="crm-contact-searches"
            role="tabpanel"
            id={`${titleId}-panel-searches`}
            aria-labelledby={`${titleId}-tab-searches`}
          >
            <section className="crm-contact-section">
              <div className="crm-section-heading">
                <div><span className="crm-section-kicker">Saved criteria</span><h3>What they're looking for</h3></div>
                {contactId && (
                  <button
                    type="button"
                    className="crm-criteria-save"
                    onClick={() => void handleSaveCriteria()}
                    disabled={criteriaBusy}
                  >
                    {criteriaBusy ? "Saving…" : "Save criteria"}
                  </button>
                )}
              </div>
              {!contactId ? (
                <div className="crm-contact-empty">
                  <strong>No merged contact record yet.</strong>
                  <span>Saved-search criteria attach to a contact — they'll be available once this profile is merged.</span>
                </div>
              ) : (
                <div className="crm-criteria-grid">
                  {([
                    ["priceRange", "Price range", "e.g. $500k – $625k"],
                    ["propertyType", "Property type", "e.g. House / half-duplex"],
                    ["bedrooms", "Bedrooms", "e.g. 3+"],
                    ["bathrooms", "Bathrooms", "e.g. 2+"],
                    ["parking", "Parking", "e.g. Garage or carport"],
                    ["timeline", "Timeline", "e.g. 60–90 days"],
                    ["areas", "Preferred areas", "e.g. Sahali, Aberdeen"],
                  ] as const).map(([key, label, placeholder]) => (
                    <label key={key} className="crm-criteria-field">
                      <span>{label}</span>
                      <input
                        type="text"
                        value={criteria[key]}
                        placeholder={placeholder}
                        onChange={(event) => setCriteria((current) => ({ ...current, [key]: event.target.value }))}
                      />
                    </label>
                  ))}
                  <label className="crm-criteria-field crm-criteria-notes">
                    <span>Notes / more details</span>
                    <textarea
                      value={criteria.notes}
                      placeholder="Anything else about what they want…"
                      rows={3}
                      onChange={(event) => setCriteria((current) => ({ ...current, notes: event.target.value }))}
                    />
                  </label>
                  {criteriaNotice && <span className="crm-criteria-notice" role="status">{criteriaNotice}</span>}
                </div>
              )}
            </section>
          </div>
        )}

        <div
          className="crm-contact-body"
          role="tabpanel"
          id={`${titleId}-panel-overview`}
          aria-labelledby={`${titleId}-tab-overview`}
          hidden={tab !== "overview"}
        >
          <div className="crm-contact-main">
            <section className="crm-contact-section crm-contact-compose" aria-labelledby={`${titleId}-compose`}>
              <div className="crm-section-heading">
                <div><span className="crm-section-kicker">Log it</span><h3 id={`${titleId}-compose`}>Notes</h3></div>
                <div className="crm-compose-modes" role="group" aria-label="Compose mode">
                  {(["note", "text", "email"] as const).map((mode) => (
                    <button
                      key={mode}
                      type="button"
                      className={composeMode === mode ? "on" : ""}
                      data-mode={mode}
                      aria-pressed={composeMode === mode}
                      disabled={mode !== "note"}
                      title={mode === "note"
                        ? undefined
                        : "Texts and emails go through the AI draft approval flow — compose here is notes-only for now."}
                      onClick={() => setComposeMode(mode)}
                    >
                      {mode === "note" ? "Note" : mode === "text" ? "Text" : "Email"}
                    </button>
                  ))}
                </div>
              </div>
              {!contactId ? (
                <p className="crm-rail-empty">Notes attach to a merged contact record — none exists for this profile yet.</p>
              ) : (
                <>
                  <div className="crm-compose-box">
                    <textarea
                      value={noteText}
                      placeholder="Add a note / log…"
                      rows={2}
                      aria-label={`Add a note for ${profile.name}`}
                      onChange={(event) => setNoteText(event.target.value)}
                    />
                    <button
                      type="button"
                      className="crm-compose-send"
                      onClick={() => void handleAddNote()}
                      disabled={noteBusy || !noteText.trim()}
                    >
                      {noteBusy ? "Saving…" : "Log note"}
                    </button>
                  </div>
                  {notesError && <div className="crm-contact-error" role="alert">{notesError}</div>}
                  {notes === null ? (
                    <div className="crm-contact-loading" role="status">Loading notes…</div>
                  ) : notes.length === 0 ? (
                    <p className="crm-rail-empty">No notes yet — the first one you log lands here.</p>
                  ) : (
                    <ul className="crm-note-list">
                      {notes.filter((note) => !note.deleted).map((note) => (
                        <li key={note.id} className={note.pinned ? "pinned" : ""}>
                          <div className="crm-note-top">
                            {note.pinned && <span className="crm-note-pin-badge">📌 Pinned</span>}
                            <span className="crm-note-when mono">
                              {formatTime(note.createdAt)} · {note.authorKind === "operator" ? "you" : note.authorName}
                            </span>
                            <button
                              type="button"
                              className={"crm-note-pin" + (note.pinned ? " on" : "")}
                              aria-label={note.pinned ? "Unpin note" : "Pin note to top"}
                              aria-pressed={note.pinned}
                              disabled={noteBusy}
                              onClick={() => void handlePinNote(note)}
                            >
                              📌
                            </button>
                          </div>
                          <p>{note.body}</p>
                        </li>
                      ))}
                    </ul>
                  )}
                </>
              )}
            </section>

            {draft && (
              <section className="crm-contact-section crm-contact-draft" aria-labelledby={`${titleId}-draft`}>
                <div className="crm-section-heading">
                  <div><span className="crm-section-kicker">Approval gate</span><h3 id={`${titleId}-draft`}>Draft ready</h3></div>
                  <span className="crm-safe-send">Nothing sends until approved</span>
                </div>
                <DraftRow
                  draft={draft}
                  selected={false}
                  expanded
                  onAction={onDraftAction ? (action, nextDraft, scheduledAt) => void handleDraftAction(action, nextDraft, scheduledAt) : undefined}
                  busy={draftBusy}
                  onEditTemplate={approvalInProgress ? undefined : onEditTemplate}
                  hideSelection
                  expandable={false}
                />
              </section>
            )}

            <section className="crm-contact-section" aria-labelledby={`${titleId}-timeline`}>
              <div className="crm-section-heading">
                <div><span className="crm-section-kicker">Selected thread</span><h3 id={`${titleId}-timeline`}>Conversation timeline</h3></div>
                <span className="mono">{timeline.length} events</span>
              </div>
              {loadingContext ? (
                <div className="crm-contact-loading" role="status">Loading conversation details…</div>
              ) : contextError ? (
                <div className="crm-contact-empty" role="alert"><strong>Conversation unavailable</strong><span>{contextError}</span></div>
              ) : timeline.length === 0 ? (
                <div className="crm-contact-empty"><strong>No conversation events on file.</strong><span>New messages, notes, sends, and source activity will appear here.</span></div>
              ) : (
                <ol className="crm-timeline">
                  {timeline.map((item) => (
                    <li key={item.id} data-kind={item.kind}>
                      <span className="crm-timeline-marker" aria-hidden="true" />
                      <article>
                        <div className="crm-timeline-meta">
                          <span className="crm-timeline-label">{item.label}</span>
                          <time dateTime={item.timestamp || undefined}>{formatTime(item.timestamp)}</time>
                        </div>
                        <strong>{item.title}</strong>
                        <p>{item.body}</p>
                      </article>
                    </li>
                  ))}
                </ol>
              )}
            </section>
          </div>

          <aside className="crm-contact-rail" aria-label="Contact details">
            <section className="crm-contact-section">
              <div className="crm-section-heading"><h3>Lead details</h3></div>
              <dl className="crm-detail-list">
                <div><dt>Pipeline</dt><dd>{lead?.stage || profile.status || "No status"}</dd></div>
                <div><dt>Segment</dt><dd><span className={`crm-temp ${temperature}`}>{CRM_TEMPERATURE_LABELS[temperature]}</span></dd></div>
                <div><dt>Owner</dt><dd>{owner}</dd></div>
                <div><dt>Source</dt><dd>{lead?.leadSource || profile.source}</dd></div>
                <div><dt>Last touch</dt><dd>{profile.lastTouch || profile.age || "Unknown"}</dd></div>
              </dl>
              {lead?.summary && <p className="crm-lead-summary">{lead.summary}</p>}
            </section>

            <section className="crm-contact-section">
              <div className="crm-section-heading"><h3>Contact</h3></div>
              <div className="crm-contact-links">
                {emails.map((email) => <a key={email} href={`mailto:${email}`}>{email}</a>)}
                {phones.map((phone) => <a key={phone} href={`tel:${phone}`}>{phone}</a>)}
                {emails.length === 0 && phones.length === 0 && <span>No contact details on file.</span>}
              </div>
            </section>

            <section className="crm-contact-section">
              <div className="crm-section-heading">
                <h3>Tags</h3>
                <span className="mono">{tags.length}</span>
              </div>
              {tags.length > 0 ? (
                <div className="crm-contact-tags">
                  {tags.map((tag) => (
                    onTagsChange && contactId ? (
                      <span key={tag} className="crm-tag-editable">
                        {tag}
                        <button
                          type="button"
                          aria-label={`Remove tag ${tag}`}
                          disabled={tagBusy}
                          onClick={() => void handleToggleTag(tag)}
                        >×</button>
                      </span>
                    ) : <span key={tag}>{tag}</span>
                  ))}
                </div>
              ) : <p className="crm-rail-empty">No tags on this contact yet.</p>}
              {onTagsChange && (
                contactId ? (
                  <button
                    type="button"
                    className="crm-tag-add"
                    onClick={() => setTagPickerOpen(true)}
                    disabled={tagBusy}
                  >
                    ＋ Tag
                  </button>
                ) : (
                  <p className="crm-rail-empty">Tagging needs a merged contact record.</p>
                )
              )}
            </section>

            <section className="crm-contact-section">
              <div className="crm-section-heading"><h3>Tasks</h3><span className="mono">{(contactId ? contactTasks?.length : context?.tasks.length) ?? 0}</span></div>
              {taskError && <div className="crm-contact-error" role="alert">{taskError}</div>}
              {((contactId ? contactTasks : context?.tasks)?.length ?? 0) > 0 ? (
                <ul className="crm-task-list">
                  {(contactId ? contactTasks || [] : context?.tasks || []).map((task) => {
                    const done = task.status === "done";
                    return (
                      <li key={task.id}>
                        <input
                          type="checkbox"
                          className="crm-task-check"
                          checked={done}
                          disabled={taskBusy}
                          aria-label={done ? `Reopen task: ${task.title || "Task"}` : `Complete task: ${task.title || "Task"}`}
                          onChange={() => void handleToggleTask(task.id, !done)}
                        />
                        <div>
                          <strong className={done ? "crm-task-done" : undefined}>{task.title || "Task"}</strong>
                          <span>{task.summary || formatTime(task.dueAt || task.timestamp)}</span>
                        </div>
                      </li>
                    );
                  })}
                </ul>
              ) : <p className="crm-rail-empty">{contactId ? "No tasks yet — add the first one below." : "No tasks on this conversation."}</p>}
              {contactId && (
                <div className="crm-task-add">
                  <input
                    type="text"
                    value={taskTitle}
                    placeholder="Add a task…"
                    aria-label={`New task for ${profile.name}`}
                    onChange={(event) => setTaskTitle(event.target.value)}
                    onKeyDown={(event) => { if (event.key === "Enter") void handleAddTask(); }}
                  />
                  <input
                    type="text"
                    className="crm-task-add-due"
                    value={taskDue}
                    placeholder="When (e.g. Fri · call)"
                    aria-label="When the task is due"
                    onChange={(event) => setTaskDue(event.target.value)}
                    onKeyDown={(event) => { if (event.key === "Enter") void handleAddTask(); }}
                  />
                  <button type="button" disabled={taskBusy || !taskTitle.trim()} onClick={() => void handleAddTask()}>
                    {taskBusy ? "…" : "＋ Add"}
                  </button>
                </div>
              )}
            </section>
          </aside>
        </div>

        {tagPickerOpen && (
          <div
            className="crm-tagpicker-backdrop"
            onMouseDown={(event) => { if (event.target === event.currentTarget) setTagPickerOpen(false); }}
          >
            <div className="crm-tagpicker" role="dialog" aria-modal="true" aria-label={`Add tags for ${profile.name}`}>
              <div className="crm-tagpicker-head">
                <h3>Add tags</h3>
                <button type="button" aria-label="Close tag picker" onClick={() => setTagPickerOpen(false)}>×</button>
              </div>
              <p className="crm-tagpicker-sub">Tap to add or remove — or make your own at the bottom.</p>
              {tagError && <div className="crm-contact-error" role="alert">{tagError}</div>}
              {TAG_GROUPS.map((group) => (
                <div key={group.label} className="crm-tagpicker-group">
                  <span className="crm-tagpicker-label mono">{group.label}</span>
                  <div className="crm-tagpicker-opts">
                    {group.tags.map((tag) => {
                      const active = tags.includes(tag);
                      return (
                        <button
                          key={tag}
                          type="button"
                          className={active ? "added" : ""}
                          aria-pressed={active}
                          disabled={tagBusy}
                          onClick={() => void handleToggleTag(tag)}
                        >
                          {tag}
                        </button>
                      );
                    })}
                  </div>
                </div>
              ))}
              <div className="crm-tagpicker-custom">
                <input
                  type="text"
                  value={customTag}
                  placeholder="Add your own tag…"
                  aria-label="Custom tag name"
                  onChange={(event) => setCustomTag(event.target.value)}
                  onKeyDown={(event) => { if (event.key === "Enter") void handleAddCustomTag(); }}
                />
                <button type="button" disabled={tagBusy || !customTag.trim()} onClick={() => void handleAddCustomTag()}>Add</button>
              </div>
              <div className="crm-tagpicker-foot">
                <button type="button" onClick={() => setTagPickerOpen(false)}>Done</button>
              </div>
            </div>
          </div>
        )}
      </aside>
    </div>
  );
}
