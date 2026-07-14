import { useState } from "react";

import type { LeadsDraft, LeadsDraftAction } from "../leads-data";
import { draftApprovalBlockedReason, hasRegisteredDraftTransport } from "../draft-send-lifecycle";

export function draftHasRegisteredTransport(draft: LeadsDraft): boolean {
  return hasRegisteredDraftTransport(draft.channel);
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
  const editText = editState.draftId === draft.id && editState.sourceBody === draft.body
    ? editState.value
    : draft.body;
  const setEditText = (value: string) => setEditState({ draftId: draft.id, sourceBody: draft.body, value });

  const dirty = editText.trim() !== draft.body.trim();
  const sendable = draftHasRegisteredTransport(draft);
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
          <span
            className="lb-schedule-unavailable"
            title={!exactIdentityReady
              ? approveBlockedReason ?? undefined
              : sendable
                ? "Scheduled sending is not yet persisted by the delivery service. Approving would send immediately."
                : `${draft.channel || "This"} transport is not registered, so Elevate will not claim this draft was sent.`}
          >
            {!exactIdentityReady
              ? "Exact draft identity unavailable"
              : sendable
                ? "Schedule unavailable"
                : `${draft.channel || "Message"} transport unavailable`}
            <span className="sr-only">
              {!exactIdentityReady
                ? ". This draft cannot be approved until exact source, thread, and task identifiers are available."
                : sendable
                  ? ". Scheduled sending is not yet persisted, so approving would send immediately."
                  : ". This draft cannot be approved until a real delivery transport is connected."}
            </span>
          </span>
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
    </div>
  );
}
