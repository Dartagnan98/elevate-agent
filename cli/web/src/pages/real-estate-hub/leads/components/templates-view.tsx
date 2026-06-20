import { useState } from "react";

import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import type { LeadsTemplateItem, LeadsTemplateLane } from "../leads-data";
import { TemplateEditorRow, TemplateRow, type TplEditor } from "./template-rows";

export interface TemplateMutations {
  // Create a template in a lane. Returns once the list is refreshed.
  onCreate: (laneId: string, name: string, body: string) => Promise<void>;
  // Save name/body edits to an existing template.
  onSave: (id: string, name: string, body: string) => Promise<void>;
  // Toggle a template's active flag (Pause / Resume).
  onTogglePause: (id: string, active: boolean) => Promise<void>;
  // Delete a template.
  onDelete: (id: string) => Promise<void>;
  // Ask the backend for a suggested variant for a lane. Resolves to the
  // suggested name/body so the caller can open a prefilled editor.
  onSuggest: (laneId: string) => Promise<{ name: string; body: string }>;
}

export function TemplatesView({ groups, mutations }: { groups: LeadsTemplateLane[]; mutations?: TemplateMutations }) {
  const total = groups.reduce((n, g) => n + g.templates.length, 0);
  const active = groups.reduce((n, g) => n + g.active, 0);

  const [editor, setEditor] = useState<TplEditor | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<LeadsTemplateItem | null>(null);

  const openCreate = (laneId: string) => {
    setError(null);
    setEditor({ mode: "create", laneId, name: "", body: "" });
  };
  const openEdit = (laneId: string, t: LeadsTemplateItem) => {
    setError(null);
    setEditor({ mode: "edit", id: t.id, laneId, name: t.name, body: t.body });
  };
  const closeEditor = () => { setEditor(null); setError(null); };

  const saveEditor = async () => {
    if (!editor || !mutations) return;
    const name = editor.name.trim();
    const body = editor.body.trim();
    if (!name || !body) { setError("Name and body are both required."); return; }
    setBusy(true);
    setError(null);
    try {
      if (editor.mode === "create") await mutations.onCreate(editor.laneId, name, body);
      else await mutations.onSave(editor.id, name, body);
      setEditor(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save template.");
    } finally {
      setBusy(false);
    }
  };

  const suggest = async (laneId: string) => {
    if (!mutations) return;
    setBusy(true);
    setError(null);
    try {
      const variant = await mutations.onSuggest(laneId);
      setEditor({ mode: "create", laneId, name: variant.name, body: variant.body });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not suggest a variant.");
    } finally {
      setBusy(false);
    }
  };

  const togglePause = async (t: LeadsTemplateItem) => {
    if (!mutations) return;
    setBusy(true);
    setError(null);
    try {
      await mutations.onTogglePause(t.id, !t.active);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not update template.");
    } finally {
      setBusy(false);
    }
  };

  const remove = async (t: LeadsTemplateItem) => {
    if (!mutations) return;
    setBusy(true);
    setError(null);
    try {
      await mutations.onDelete(t.id);
      setDeleteTarget(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not delete template.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="lb-templates">
      <section className="ab-card lb-tpl-overview">
        <header className="lb-tpl-overview-head">
          <div>
            <h2 className="lb-profiles-title">Templates overview</h2>
            <p className="lb-profiles-desc">
              What's working, what's not, and fresh variants for approval. Best/worst rank after 5+ sends. Drift flags templates whose 30-day reply rate dropped 30%+ vs all-time.
            </p>
          </div>
          <span className="lb-tpl-overview-total mono">{total} total · {active} active</span>
        </header>

        {error && <div className="lb-replies-empty" style={{ color: "var(--accent-warn, #e0a44c)" }}>{error}</div>}

        <div className="lb-tpl-summary">
          {groups.map(g => (
            <div key={g.lane} className="lb-tpl-summary-card">
              <div className="lb-tpl-summary-head">
                <span className="lb-tpl-summary-icon" aria-hidden="true">{g.icon}</span>
                <span className="lb-tpl-summary-name">{g.lane}</span>
                <button type="button" className="lb-btn ghost sm" disabled={busy || !mutations} onClick={() => void suggest(g.laneId)}>✦ Suggest variant</button>
              </div>
              <div className="lb-tpl-summary-stats">
                <span><strong className="mono">{g.active}</strong> <span className="lb-tpl-stat-label">active</span></span>
                <span className="lb-tpl-stat-sep">·</span>
                <span><strong className="mono">{g.sent}</strong> <span className="lb-tpl-stat-label">sent</span></span>
                <span className="lb-tpl-stat-sep">·</span>
                <span><strong className="mono">{g.replyRate}%</strong> <span className="lb-tpl-stat-label">reply</span></span>
              </div>
              <div className="lb-tpl-summary-foot">{g.needMore}</div>
            </div>
          ))}
        </div>
      </section>

      {groups.map(g => (
        <section key={g.lane} className="ab-card lb-tpl-group">
          <header className="lb-tpl-group-head">
            <span className="lb-tpl-group-icon" aria-hidden="true">{g.icon}</span>
            <span className="lb-tpl-group-name">{g.lane}</span>
            <span className="lb-tpl-group-count mono">{g.templates.length} templates</span>
            <button type="button" className="lb-btn ghost sm" style={{ marginLeft: "auto" }} disabled={busy || !mutations} onClick={() => openCreate(g.laneId)}>+ New template</button>
          </header>
          <div className="lb-tpl-list">
            {g.templates.map(t => (
              editor?.mode === "edit" && editor.id === t.id ? (
                <TemplateEditorRow
                  key={t.id}
                  editor={editor}
                  onChange={(patch) => setEditor((prev) => (prev ? { ...prev, ...patch } : prev))}
                  onSave={saveEditor}
                  onCancel={closeEditor}
                  busy={busy}
                />
              ) : (
                <TemplateRow
                  key={t.id}
                  template={t}
                  onPause={mutations ? () => void togglePause(t) : undefined}
                  onEdit={mutations ? () => openEdit(g.laneId, t) : undefined}
                  onDelete={mutations ? () => setDeleteTarget(t) : undefined}
                  busy={busy}
                />
              )
            ))}
            {editor?.mode === "create" && editor.laneId === g.laneId && (
              <TemplateEditorRow
                editor={editor}
                onChange={(patch) => setEditor((prev) => (prev ? { ...prev, ...patch } : prev))}
                onSave={saveEditor}
                onCancel={closeEditor}
                busy={busy}
              />
            )}
          </div>
        </section>
      ))}
      <ConfirmDialog
        open={deleteTarget !== null}
        title={`Delete "${deleteTarget?.name ?? "this template"}"?`}
        description="This removes the outreach template from this lane. This action cannot be undone here."
        confirmLabel="Delete"
        destructive
        loading={busy}
        onCancel={() => setDeleteTarget(null)}
        onConfirm={() => {
          if (deleteTarget) void remove(deleteTarget);
        }}
      />
    </div>
  );
}
