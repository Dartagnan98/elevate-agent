import type { LeadsTemplateItem } from "../leads-data";

export type TplEditor =
  | { mode: "create"; laneId: string; name: string; body: string }
  | { mode: "edit"; id: string; laneId: string; name: string; body: string };

export function TemplateEditorRow({
  editor,
  onChange,
  onSave,
  onCancel,
  busy,
}: {
  editor: TplEditor;
  onChange: (patch: Partial<{ name: string; body: string }>) => void;
  onSave: () => void;
  onCancel: () => void;
  busy: boolean;
}) {
  return (
    <div className="lb-tpl-row lb-tpl-editor">
      <div className="lb-tpl-row-body">
        <input
          type="text"
          className="lb-tpl-edit-name"
          value={editor.name}
          placeholder="Template name"
          onChange={(e) => onChange({ name: e.target.value })}
          disabled={busy}
        />
        <textarea
          className="lb-draft-edit"
          value={editor.body}
          placeholder="Body. Use {first_name}, {area}, {topic}, etc."
          rows={4}
          onChange={(e) => onChange({ body: e.target.value })}
          disabled={busy}
        />
      </div>
      <div className="lb-tpl-row-actions">
        <button type="button" className="lb-btn ghost sm" onClick={onCancel} disabled={busy}>
          Cancel
        </button>
        <button type="button" className="lb-btn primary sm" onClick={onSave} disabled={busy}>
          {busy ? "…" : editor.mode === "create" ? "Add" : "Save"}
        </button>
      </div>
    </div>
  );
}

export function TemplateRow({
  template,
  onPause,
  onEdit,
  onDelete,
  busy,
}: {
  template: LeadsTemplateItem;
  onPause?: () => void;
  onEdit?: () => void;
  onDelete?: () => void;
  busy?: boolean;
}) {
  return (
    <div className={"lb-tpl-row" + (template.active ? "" : " paused")}>
      <div className="lb-tpl-row-body">
        <div className="lb-tpl-row-name">{template.name}</div>
        <div className="lb-tpl-row-text">{template.body}</div>
        <div className="lb-tpl-row-meta mono">
          <span>Used {template.used}×</span>
          <span className="lb-tpl-meta-sep">·</span>
          <span>{template.replies} replies</span>
          {template.replyRate != null && (
            <>
              <span className="lb-tpl-meta-sep">·</span>
              <span>{template.replyRate}% reply rate</span>
            </>
          )}
          {!template.active && (
            <>
              <span className="lb-tpl-meta-sep">·</span>
              <span>paused</span>
            </>
          )}
        </div>
      </div>
      <div className="lb-tpl-row-actions">
        <button
          type="button"
          className="lb-tpl-icon-btn"
          aria-label={template.active ? "Pause" : "Resume"}
          title={template.active ? "Pause" : "Resume"}
          disabled={busy || !onPause}
          onClick={onPause}
        >
          {template.active ? "‖" : "▸"}
        </button>
        <button
          type="button"
          className="lb-tpl-icon-btn"
          aria-label="Edit"
          disabled={busy || !onEdit}
          onClick={onEdit}
        >
          ✎
        </button>
        <button
          type="button"
          className="lb-tpl-icon-btn danger"
          aria-label="Delete"
          disabled={busy || !onDelete}
          onClick={onDelete}
        >
          🗑
        </button>
      </div>
    </div>
  );
}
