import { useCallback, useState } from "react";
import { CheckCircle2, Pencil, Plus, Trash2 } from "lucide-react";
import { Link } from "react-router-dom";

import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { api } from "@/lib/api";
import type { OutreachTemplate } from "@/lib/api-types";
import { cn } from "@/lib/utils";

import {
  errorMessage,
  LEADS_TEMPLATE_LANES,
  type LeadsSetupDraft,
} from "./onboarding-data";
import {
  TemplateEditorCard,
  type TemplateEditorState,
  WizardField,
} from "./onboarding-form-parts";

export function LeadsPolicyStep({
  draft,
  updateField,
  firstTouchTemplates,
  refreshTemplates,
}: {
  draft: LeadsSetupDraft;
  updateField: <K extends keyof LeadsSetupDraft>(key: K, value: LeadsSetupDraft[K]) => void;
  firstTouchTemplates: OutreachTemplate[];
  refreshTemplates: () => Promise<void>;
}) {
  const [templateEditor, setTemplateEditor] = useState<TemplateEditorState | null>(null);
  const [templateMutating, setTemplateMutating] = useState(false);
  const [templateError, setTemplateError] = useState<string | null>(null);
  const [deleteTemplateTarget, setDeleteTemplateTarget] = useState<OutreachTemplate | null>(null);

  const openCreateTemplate = useCallback((lane: string) => {
    setTemplateError(null);
    setTemplateEditor({ mode: "create", lane, name: "", body: "" });
  }, []);

  const openEditTemplate = useCallback((tpl: OutreachTemplate) => {
    setTemplateError(null);
    setTemplateEditor({ mode: "edit", id: tpl.id, lane: tpl.lane, name: tpl.name, body: tpl.body });
  }, []);

  const closeTemplateEditor = useCallback(() => {
    setTemplateEditor(null);
    setTemplateError(null);
  }, []);

  const saveTemplate = useCallback(async () => {
    if (!templateEditor) return;
    const name = templateEditor.name.trim();
    const body = templateEditor.body.trim();
    if (!name || !body) {
      setTemplateError("Name and body are both required.");
      return;
    }
    setTemplateMutating(true);
    setTemplateError(null);
    try {
      if (templateEditor.mode === "create") {
        await api.createOutreachTemplate({ lane: templateEditor.lane, name, body });
      } else {
        await api.updateOutreachTemplate(templateEditor.id, { name, body });
      }
      await refreshTemplates();
      setTemplateEditor(null);
    } catch (err) {
      setTemplateError(errorMessage(err, "Could not save template."));
    } finally {
      setTemplateMutating(false);
    }
  }, [templateEditor, refreshTemplates]);

  const deleteTemplate = useCallback(
    async (tpl: OutreachTemplate) => {
      setTemplateMutating(true);
      setTemplateError(null);
      try {
        await api.deleteOutreachTemplate(tpl.id);
        await refreshTemplates();
        setDeleteTemplateTarget(null);
      } catch (err) {
        setTemplateError(errorMessage(err, "Could not delete template."));
      } finally {
        setTemplateMutating(false);
      }
    },
    [refreshTemplates],
  );

  return (
    <div className="flex flex-col gap-4">
      <label className="flex items-start gap-3 rounded-md border border-border bg-card/60 px-4 py-3 backdrop-blur-sm">
        <input
          type="checkbox"
          checked={draft.autoReplyEnabled}
          onChange={(e) => updateField("autoReplyEnabled", e.target.checked)}
          className="mt-0.5 h-3.5 w-3.5 rounded border-border accent-primary"
        />
        <div className="min-w-0">
          <div className="text-[13px] font-medium text-foreground">
            Send an automated first reply when a lead lands
          </div>
          <p className="mt-0.5 text-[11.5px] text-muted-foreground">
            Off by default — Elevation drafts and queues a reply for your approval instead.
          </p>
        </div>
      </label>
      <div className="flex flex-col gap-4">
        <div className="flex items-baseline justify-between gap-2">
          <div className="flex flex-col gap-0.5">
            <span className="text-[12.5px] font-medium text-foreground">
              Template library
            </span>
            <span className="text-[11px] leading-[1.4] text-muted-foreground">
              Elevation picks per situation — best-fit template is auto-attached by ID and tracked for reply rate. Click any card to pin it as the default first-touch.
            </span>
          </div>
          <Link
            to="/real-estate/templates"
            className="shrink-0 text-[11px] text-muted-foreground underline-offset-2 hover:text-foreground hover:underline"
          >
            Manage all
          </Link>
        </div>
        {templateError && (
          <div className="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-1.5 text-[11.5px] text-destructive">
            {templateError}
          </div>
        )}
        {LEADS_TEMPLATE_LANES.map((lane) => {
          const laneTemplates = firstTouchTemplates.filter((t) => t.lane === lane.id);
          const editingThisLane =
            templateEditor && templateEditor.lane === lane.id ? templateEditor : null;
          return (
            <div key={lane.id} className="flex flex-col gap-2">
              <div className="flex items-baseline justify-between gap-2">
                <div className="flex items-baseline gap-2">
                  <span className="font-mono-ui text-[10px] uppercase tracking-[0.12em] text-muted-foreground">
                    {lane.label}
                  </span>
                  <span className="text-[10.5px] text-muted-foreground/70">
                    {laneTemplates.length} · {lane.hint}
                  </span>
                </div>
                <button
                  type="button"
                  onClick={() => openCreateTemplate(lane.id)}
                  className="inline-flex items-center gap-1 rounded-sm px-1.5 py-0.5 font-mono-ui text-[10px] uppercase tracking-wide text-muted-foreground transition hover:bg-muted hover:text-foreground"
                  disabled={templateMutating}
                >
                  <Plus className="h-3 w-3" />
                  Add
                </button>
              </div>
              <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                {laneTemplates.map((tpl) => {
                  const isActive = draft.autoReplyTemplate.trim() === tpl.body.trim();
                  const hasGif = /\[\[gif:/i.test(tpl.body);
                  const isEditingThis =
                    editingThisLane?.mode === "edit" && editingThisLane.id === tpl.id;
                  if (isEditingThis) {
                    return (
                      <TemplateEditorCard
                        key={tpl.id}
                        editor={editingThisLane}
                        onChange={(patch) =>
                          setTemplateEditor((prev) => (prev ? { ...prev, ...patch } : prev))
                        }
                        onSave={saveTemplate}
                        onCancel={closeTemplateEditor}
                        busy={templateMutating}
                      />
                    );
                  }
                  return (
                    <div
                      key={tpl.id}
                      className={cn(
                        "group relative flex flex-col gap-1 rounded-md border px-3 py-2.5 text-left backdrop-blur-sm transition",
                        isActive
                          ? "border-primary/60 bg-primary/10"
                          : "border-border bg-card/60 hover:border-border/80 hover:bg-card",
                      )}
                    >
                      <button
                        type="button"
                        onClick={() => updateField("autoReplyTemplate", tpl.body)}
                        className="flex flex-col gap-1 text-left"
                      >
                        <div className="flex items-center justify-between gap-2 pr-12">
                          <span className="text-[12.5px] font-medium text-foreground">{tpl.name}</span>
                          <div className="flex items-center gap-1.5">
                            {hasGif && (
                              <span className="inline-flex items-center rounded-sm border border-border/70 bg-muted/50 px-1.5 py-px font-mono-ui text-[9px] uppercase tracking-wide text-muted-foreground">
                                GIF
                              </span>
                            )}
                            {isActive && <CheckCircle2 className="h-3.5 w-3.5 text-primary" />}
                          </div>
                        </div>
                        <span className="line-clamp-2 text-[11.5px] leading-[1.4] text-muted-foreground">
                          {tpl.body}
                        </span>
                        <span className="mt-0.5 font-mono-ui text-[9.5px] tracking-wide text-muted-foreground/60">
                          id · {tpl.id.slice(0, 8)}
                        </span>
                      </button>
                      <div className="absolute right-2 top-2 flex items-center gap-1 opacity-0 transition group-hover:opacity-100">
                        <button
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation();
                            openEditTemplate(tpl);
                          }}
                          className="rounded-sm p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
                          title="Rename or edit body"
                          disabled={templateMutating}
                        >
                          <Pencil className="h-3 w-3" />
                        </button>
                        <button
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation();
                            setDeleteTemplateTarget(tpl);
                          }}
                          className="rounded-sm p-1 text-muted-foreground hover:bg-destructive/20 hover:text-destructive"
                          title="Delete template"
                          disabled={templateMutating}
                        >
                          <Trash2 className="h-3 w-3" />
                        </button>
                      </div>
                    </div>
                  );
                })}
                {editingThisLane?.mode === "create" && (
                  <TemplateEditorCard
                    editor={editingThisLane}
                    onChange={(patch) =>
                      setTemplateEditor((prev) => (prev ? { ...prev, ...patch } : prev))
                    }
                    onSave={saveTemplate}
                    onCancel={closeTemplateEditor}
                    busy={templateMutating}
                  />
                )}
                {laneTemplates.length === 0 && editingThisLane?.mode !== "create" && (
                  <button
                    type="button"
                    onClick={() => openCreateTemplate(lane.id)}
                    className="flex flex-col items-center justify-center gap-1 rounded-md border border-dashed border-border/70 px-3 py-4 text-[11.5px] text-muted-foreground hover:border-border hover:text-foreground"
                    disabled={templateMutating}
                  >
                    <Plus className="h-3.5 w-3.5" />
                    Add the first {lane.label.toLowerCase()} template
                  </button>
                )}
              </div>
            </div>
          );
        })}
      </div>
      <label className="block">
        <span className="mb-1.5 block text-[12px] font-medium text-muted-foreground">
          Initial reply template {draft.autoReplyEnabled && <span className="text-destructive">*</span>}
        </span>
        <textarea
          value={draft.autoReplyTemplate}
          onChange={(e) => updateField("autoReplyTemplate", e.target.value)}
          rows={4}
          placeholder="Hey {{firstName}} — thanks for reaching out. What's the property address or area you're looking at?"
          className="min-h-28 w-full resize-y rounded-md border border-border bg-card/60 px-3 py-2 text-[13px] leading-5 text-foreground outline-none backdrop-blur-sm placeholder:text-muted-foreground/60 focus:border-primary focus:ring-1 focus:ring-primary/30"
        />
        <span className="mt-1.5 block text-[11.5px] leading-5 text-muted-foreground/80">
          {firstTouchTemplates.length > 0
            ? "Pick one above to load it here — edit freely. Used both as the auto-send template (if enabled) and the default draft otherwise."
            : "Used both as the auto-send template (if enabled) and the default draft otherwise."}
        </span>
      </label>
      <WizardField
        label="Follow-up cadence (days between nudges)"
        value={draft.followUpCadenceDays}
        onChange={(v) => updateField("followUpCadenceDays", v)}
        placeholder="2"
        type="number"
      />
      <ConfirmDialog
        open={deleteTemplateTarget !== null}
        title={`Delete "${deleteTemplateTarget?.name ?? "this template"}"?`}
        description="This removes the outreach template from the wizard. This action cannot be undone here."
        confirmLabel="Delete"
        destructive
        loading={templateMutating}
        onCancel={() => setDeleteTemplateTarget(null)}
        onConfirm={() => {
          if (deleteTemplateTarget) void deleteTemplate(deleteTemplateTarget);
        }}
      />
    </div>
  );
}
