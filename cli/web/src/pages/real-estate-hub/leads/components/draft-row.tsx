import { useEffect, useState } from "react";

import type { LeadsDraft, LeadsDraftAction } from "../leads-data";

export function DraftRow({
  draft,
  selected,
  expanded,
  onToggle,
  onExpand,
  onAction,
  busy,
  onEditTemplate,
}: {
  draft: LeadsDraft;
  selected: boolean;
  expanded: boolean;
  onToggle: () => void;
  onExpand: () => void;
  onAction?: (action: LeadsDraftAction, draft: LeadsDraft, scheduledAt?: string) => void;
  busy?: boolean;
  onEditTemplate?: () => void;
}) {
  const [editText, setEditText] = useState(draft.body);
  // Approve & Schedule: when open, show a date/time picker; on confirm the
  // chosen local time is sent to the backend as UTC so the send is held.
  const [scheduling, setScheduling] = useState(false);
  const [whenLocal, setWhenLocal] = useState("");
  const [scheduleError, setScheduleError] = useState<string | null>(null);

  useEffect(() => {
    setEditText(draft.body);
  }, [draft.id, draft.body]);

  // datetime-local default: tomorrow 9:00 AM local.
  const defaultWhen = () => {
    const d = new Date();
    d.setDate(d.getDate() + 1);
    d.setHours(9, 0, 0, 0);
    const pad = (n: number) => String(n).padStart(2, "0");
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
  };

  const dirty = editText.trim() !== draft.body.trim();
  // Always act on the CURRENT edited text — approving with the original body was
  // dropping every edit. Saving persists the edit (action "edit") without sending.
  const editedDraft = { ...draft, body: editText };

  return (
    <div className={"lb-draft" + (selected ? " selected" : "") + (expanded ? " expanded" : "")}>
      <button type="button" className="lb-draft-check" onClick={onToggle} aria-label="Select draft">
        <span className={"lb-checkbox" + (selected ? " checked" : "")}>
          {selected && <span className="lb-check">✓</span>}
        </span>
      </button>
      <div className="lb-draft-body">
        <button type="button" className="lb-draft-summary" onClick={onExpand}>
          <div className="lb-draft-head">
            <span className="lb-draft-name">{draft.name}</span>
            <span className="lb-draft-meta mono">{draft.source} · {draft.channel}</span>
            {draft.heat === "hot" && <span className="lb-heat">Hot</span>}
            <span className="lb-draft-age">{draft.age} ago</span>
          </div>
          {!expanded && <p className="lb-draft-text">{draft.body}</p>}
        </button>
        {expanded ? (
          <div className="lb-draft-expand">
            <div className="lb-draft-recipient mono">To · {draft.name} · {draft.source}</div>
            <textarea
              className="lb-draft-edit"
              value={editText}
              onChange={(e) => setEditText(e.target.value)}
              rows={Math.max(3, Math.ceil(editText.length / 70))}
              onClick={(e) => e.stopPropagation()}
              onBlur={(e) => {
                e.stopPropagation();
                if (dirty && onAction) onAction("edit", editedDraft);
              }}
            />
            <div className="lb-draft-expand-foot">
              <span className="lb-draft-template-link">
                Generated from <strong>Warm intro</strong> template ·{" "}
                <button
                  type="button"
                  className="lb-link"
                  onClick={(e) => {
                    e.stopPropagation();
                    onEditTemplate?.();
                  }}
                >
                  edit template
                </button>
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
      {scheduling ? (
        <div className="lb-draft-actions lb-draft-schedule" onClick={(e) => e.stopPropagation()}>
          <input
            type="datetime-local"
            className="lb-schedule-input"
            value={whenLocal}
            min={defaultWhen().slice(0, 10) + "T00:00"}
            onChange={(e) => setWhenLocal(e.target.value)}
          />
          <button
            type="button"
            className="lb-btn ghost sm"
            disabled={busy}
            onClick={(e) => { e.stopPropagation(); setScheduling(false); }}
          >
            Cancel
          </button>
          <button
            type="button"
            className="lb-btn primary sm"
            disabled={busy || !onAction || !whenLocal}
            onClick={(e) => {
              e.stopPropagation();
              if (!whenLocal) return;
              const when = new Date(whenLocal);
              if (isNaN(when.getTime()) || when.getTime() <= Date.now()) {
                setScheduleError("Pick a date and time in the future.");
                return;
              }
              setScheduleError(null);
              onAction?.("approve", editedDraft, when.toISOString());
              setScheduling(false);
            }}
          >
            {busy ? "…" : "Schedule"}
          </button>
          {scheduleError && <span className="lb-error" role="alert">{scheduleError}</span>}
        </div>
      ) : (
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
          <button
            type="button"
            className="lb-btn ghost sm"
            disabled={busy || !onAction}
            onClick={(e) => {
              e.stopPropagation();
              setWhenLocal(defaultWhen());
              setScheduling(true);
            }}
            title="Approve now but hold the send until a time you pick"
          >
            Approve &amp; Schedule
          </button>
          <button
            type="button"
            className="lb-btn primary sm"
            disabled={busy || !onAction}
            onClick={(e) => {
              e.stopPropagation();
              onAction?.("approve", editedDraft);
            }}
          >
            {busy ? "…" : "Approve"}
          </button>
        </div>
      )}
    </div>
  );
}
