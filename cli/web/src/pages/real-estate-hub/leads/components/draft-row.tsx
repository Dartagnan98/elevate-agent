import { useState } from "react";

import type { LeadsDraft, LeadsDraftAction } from "../leads-data";
import { draftApprovalBlockedReason, hasRegisteredDraftTransport } from "../draft-send-lifecycle";

export function draftHasRegisteredTransport(draft: LeadsDraft): boolean {
  return hasRegisteredDraftTransport(draft.channel);
}

/** Tomorrow 9:00 local, as a datetime-local input value. */
function defaultScheduleValue(): string {
  const d = new Date();
  d.setDate(d.getDate() + 1);
  d.setHours(9, 0, 0, 0);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

export function DraftRow({
  draft,
  selected,
  expanded,
  onToggle,
  onExpand,
  onAction,
  busy,
  onEditTemplate,
  hideSelection = false,
  expandable = true,
}: {
  draft: LeadsDraft;
  selected: boolean;
  expanded: boolean;
  onToggle?: () => void;
  onExpand?: () => void;
  onAction?: (action: LeadsDraftAction, draft: LeadsDraft, scheduledAt?: string) => void;
  busy?: boolean;
  onEditTemplate?: () => void;
  hideSelection?: boolean;
  expandable?: boolean;
}) {
  const [editState, setEditState] = useState(() => ({
    draftId: draft.id,
    sourceBody: draft.body,
    value: draft.body,
  }));
  const [schedulerOpen, setSchedulerOpen] = useState(false);
  const [scheduleValue, setScheduleValue] = useState(() => defaultScheduleValue());
  const [scheduleError, setScheduleError] = useState<string | null>(null);
  const editText = editState.draftId === draft.id && editState.sourceBody === draft.body
    ? editState.value
    : draft.body;
  const setEditText = (value: string) => setEditState({ draftId: draft.id, sourceBody: draft.body, value });
  // Channel switch (email<->text) state: error surfaces inline when the target
  // has no usable recipient (backend guard returns 400).
  const [switchErr, setSwitchErr] = useState<string | null>(null);

  const chanLc = (draft.channel || "").toLowerCase();
  const isText = ["sms", "text", "imessage"].includes(chanLc);
  const isEmail = ["email", "gmail"].includes(chanLc);
  const channelSwitchable = isText || isEmail;
  const currentChannel: "text" | "email" | null = isText ? "text" : isEmail ? "email" : null;

  const switchChannel = async (target: "sms" | "email") => {
    if (!onAction) return;
    setSwitchErr(null);
    try {
      // draft.channel carries the TARGET the backend switches to.
      await Promise.resolve(onAction("channel", { ...draft, channel: target }));
    } catch (e) {
      setSwitchErr((e as Error)?.message || "Couldn't switch channel.");
    }
  };

  const dirty = editText.trim() !== draft.body.trim();
  const exactIdentityReady = Boolean(draft.sourceId && draft.threadId && draft.taskId);
  const approveBlockedReason = draftApprovalBlockedReason(draft);
  // Always act on the CURRENT edited text — approving with the original body was
  // dropping every edit. Saving persists the edit (action "edit") without sending.
  const editedDraft = { ...draft, body: editText };

  return (
    <div className={"lb-draft" + (selected ? " selected" : "") + (expanded ? " expanded" : "") + (hideSelection ? " inline" : "")}>
      {!hideSelection && (
        <button
          type="button"
          role="checkbox"
          aria-checked={selected}
          className="lb-draft-check"
          onClick={onToggle}
          aria-label={`Select draft for ${draft.name}`}
        >
          <span className={"lb-checkbox" + (selected ? " checked" : "")}>
            {selected && <span className="lb-check">✓</span>}
          </span>
        </button>
      )}
      <div className="lb-draft-body">
        {expandable ? (
          <button type="button" className="lb-draft-summary" onClick={onExpand} aria-expanded={expanded}>
            <div className="lb-draft-head">
              <span className="lb-draft-name">{draft.name}</span>
              <span className="lb-draft-meta mono">{draft.source} · {draft.channel}</span>
              {draft.heat === "hot" && <span className="lb-heat">Hot</span>}
              <span className="lb-draft-age">{draft.age} ago</span>
            </div>
            {!expanded && <p className="lb-draft-text">{draft.body}</p>}
          </button>
        ) : (
          <div className="lb-draft-summary">
            <div className="lb-draft-head">
              <span className="lb-draft-name">{draft.name}</span>
              <span className="lb-draft-meta mono">{draft.source} · {draft.channel}</span>
              {draft.heat === "hot" && <span className="lb-heat">Hot</span>}
              <span className="lb-draft-age">{draft.age} ago</span>
            </div>
          </div>
        )}
        {expanded ? (
          <div className="lb-draft-expand">
            <div className="lb-draft-recipient mono">To · {draft.name} · {draft.source}</div>
            {channelSwitchable && (
              <div className="lb-chan-toggle" onClick={(e) => e.stopPropagation()}>
                <span className="lb-chan-label">Send via</span>
                <div className="lb-chan-seg">
                  <button
                    type="button"
                    className={"lb-chan-opt" + (currentChannel === "text" ? " on" : "")}
                    disabled={busy || !onAction || currentChannel === "text"}
                    onClick={() => switchChannel("sms")}
                  >
                    Text
                  </button>
                  <button
                    type="button"
                    className={"lb-chan-opt" + (currentChannel === "email" ? " on" : "")}
                    disabled={busy || !onAction || currentChannel === "email"}
                    onClick={() => switchChannel("email")}
                  >
                    Email
                  </button>
                </div>
                {switchErr && <span className="lb-chan-err">{switchErr}</span>}
              </div>
            )}
            <textarea
              className="lb-draft-edit"
              value={editText}
              onChange={(e) => setEditText(e.target.value)}
              rows={Math.max(3, Math.ceil(editText.length / 70))}
              aria-label={`Edit draft for ${draft.name}`}
              onClick={(e) => e.stopPropagation()}
            />
            <div className="lb-draft-expand-foot">
              <span className="lb-draft-template-link">
                {draft.templateName ? <>Generated from <strong>{draft.templateName}</strong> template</> : "AI-generated draft"}
                {draft.templateName && onEditTemplate && (
                  <>
                    {" · "}
                    <button
                      type="button"
                      className="lb-link"
                      onClick={(e) => {
                        e.stopPropagation();
                        onEditTemplate();
                      }}
                    >
                      edit template
                    </button>
                  </>
                )}
              </span>
              {dirty && (
                <button
                  type="button"
                  className="lb-btn ghost sm lb-draft-save"
                  disabled={busy || !onAction}
                  onClick={(e) => {
                    e.stopPropagation();
                    onAction?.("edit", editedDraft);
                  }}
                >
                  {busy ? "…" : "Save"}
                </button>
              )}
            </div>
          </div>
        ) : null}
      </div>
      <div className="lb-draft-actions">
          <button
            type="button"
            className="lb-btn ghost sm"
            disabled={busy || !onAction}
            onClick={(e) => {
              e.stopPropagation();
              onAction?.("skip", draft);
            }}
          >
            {busy ? "…" : "Skip"}
          </button>
          {approveBlockedReason ? (
            <span
              className="lb-schedule-unavailable"
              title={approveBlockedReason}
            >
              {!exactIdentityReady
                ? "Exact draft identity unavailable"
                : `${draft.channel || "Message"} transport unavailable`}
              <span className="sr-only">
                {!exactIdentityReady
                  ? ". This draft cannot be approved until exact source, thread, and task identifiers are available."
                  : ". This draft cannot be approved until a real delivery transport is connected."}
              </span>
            </span>
          ) : (
            <button
              type="button"
              className="lb-btn ghost sm lb-draft-later"
              aria-expanded={schedulerOpen}
              disabled={busy || !onAction}
              onClick={(e) => {
                e.stopPropagation();
                setScheduleError(null);
                setSchedulerOpen((open) => !open);
              }}
            >
              Send later ▾
            </button>
          )}
          <button
            type="button"
            className="lb-btn primary sm"
            disabled={busy || !onAction || Boolean(approveBlockedReason)}
            title={approveBlockedReason ?? undefined}
            onClick={(e) => {
              e.stopPropagation();
              onAction?.("approve", editedDraft);
            }}
          >
            {busy ? "…" : approveBlockedReason ? "Cannot send" : "Approve"}
          </button>
      </div>
      {schedulerOpen && !approveBlockedReason && (
        <div className="lb-draft-scheduler" onClick={(e) => e.stopPropagation()}>
          <label className="lb-draft-scheduler-when">
            <span>Hold the send until</span>
            <input
              type="datetime-local"
              value={scheduleValue}
              min={new Date().toISOString().slice(0, 16)}
              onChange={(e) => { setScheduleValue(e.target.value); setScheduleError(null); }}
            />
          </label>
          <button
            type="button"
            className="lb-btn primary sm"
            disabled={busy || !onAction}
            onClick={() => {
              const when = new Date(scheduleValue);
              if (Number.isNaN(when.getTime()) || when.getTime() <= Date.now()) {
                setScheduleError("Pick a date and time in the future.");
                return;
              }
              setSchedulerOpen(false);
              onAction?.("approve", editedDraft, when.toISOString());
            }}
          >
            {busy ? "…" : "Schedule"}
          </button>
          <button
            type="button"
            className="lb-btn ghost sm"
            disabled={busy}
            onClick={() => setSchedulerOpen(false)}
          >
            Cancel
          </button>
          {scheduleError && <span className="lb-draft-scheduler-error" role="alert">{scheduleError}</span>}
          <span className="lb-draft-scheduler-note mono">
            Delivered by the next sender run after the chosen time.
          </span>
        </div>
      )}
    </div>
  );
}
