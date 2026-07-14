import { useEffect, useId, useMemo, useRef, useState } from "react";

import { api } from "@/lib/api";
import type { ThreadContextResponse } from "@/lib/api-types";
import type { LeadsDraft, LeadsDraftAction, LeadsProfile } from "../leads-data";
import type { DraftSendLifecycleNotice } from "../draft-send-lifecycle";
import { crmTemperatureForProfile } from "./crm-profile-helpers";
import { DraftRow } from "./draft-row";
import { StatusPill } from "./profile-status";

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

        {(statusError || favoriteError || draftError) && (
          <div className="crm-contact-error" role="alert">{statusError || favoriteError || draftError}</div>
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

        <div className="crm-contact-body">
          <div className="crm-contact-main">
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
                <div><dt>Temperature</dt><dd><span className={`crm-temp ${temperature}`}>{temperature} · {profile.heat}</span></dd></div>
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
              <div className="crm-section-heading"><h3>Tags</h3><span className="mono">{tags.length}</span></div>
              {tags.length > 0 ? (
                <div className="crm-contact-tags">{tags.map((tag) => <span key={tag}>{tag}</span>)}</div>
              ) : <p className="crm-rail-empty">No tags on this source record.</p>}
            </section>

            <section className="crm-contact-section">
              <div className="crm-section-heading"><h3>Tasks</h3><span className="mono">{context?.tasks.length ?? 0}</span></div>
              {(context?.tasks.length ?? 0) > 0 ? (
                <ul className="crm-task-list">
                  {context?.tasks.map((task) => (
                    <li key={task.id}>
                      <span className={`crm-task-state ${task.status === "done" ? "done" : ""}`} aria-hidden="true" />
                      <div><strong>{task.title || "Task"}</strong><span>{task.summary || formatTime(task.dueAt || task.timestamp)}</span></div>
                    </li>
                  ))}
                </ul>
              ) : <p className="crm-rail-empty">No tasks on this conversation.</p>}
            </section>
          </aside>
        </div>
      </aside>
    </div>
  );
}
