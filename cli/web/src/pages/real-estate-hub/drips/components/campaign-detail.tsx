import { useCallback, useEffect, useMemo, useState } from "react";
import { ArrowLeft, ExternalLink, Loader2, Plus } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { Input } from "@/components/ui/input";
import { Select, SelectOption } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { api } from "@/lib/api";
import type {
  DripCampaignDetail,
  DripCampaignKind,
  DripCampaignRole,
  DripChannel,
  DripEnrollment,
  DripSegment,
  DripStep,
  DripStepInput,
  DripVideo,
} from "@/lib/api";
import {
  CHANNEL_LABELS,
  CHANNEL_OPTIONS,
  KIND_LABELS,
  ROLE_LABELS,
  errorMessage,
  sameDayClashes,
  segmentLabel,
} from "../drips-helpers";
import { EnrollDialog } from "./enroll-dialog";
import { ChannelBadge, Field, Note, SegmentChip, Section, fieldClass } from "./shared";

type MetaForm = {
  name: string;
  description: string;
  kind: DripCampaignKind;
  role: DripCampaignRole;
  triggerSegment: string;
  layerFlag: string;
  runOnce: boolean;
  deferLayers: boolean;
  exitDay: string;
  exitRule: string;
  notes: string;
  sourceUrl: string;
};

function formFromCampaign(c: DripCampaignDetail): MetaForm {
  return {
    name: c.name,
    description: c.description ?? "",
    kind: c.kind,
    role: c.role,
    triggerSegment: c.triggerSegment ?? "",
    layerFlag: c.layerFlag ?? "",
    runOnce: c.runOnce,
    deferLayers: c.deferLayers,
    exitDay: c.exitDay != null ? String(c.exitDay) : "",
    exitRule: c.exitRule ?? "",
    notes: c.notes ?? "",
    sourceUrl: c.sourceUrl ?? "",
  };
}

type StepForm = DripStepInput & { id?: string };

const EMPTY_STEP: StepForm = { day: 1, channel: "text", title: "", subject: "", body: "", video: "", notes: "", routeTo: "" };

export function CampaignDetail({
  campaignId,
  segments,
  videos,
  onBack,
  onChanged,
}: {
  campaignId: string;
  segments: DripSegment[];
  videos: DripVideo[];
  onBack: () => void;
  onChanged: () => Promise<void> | void;
}) {
  const [campaign, setCampaign] = useState<DripCampaignDetail | null>(null);
  const [form, setForm] = useState<MetaForm | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [stepEditor, setStepEditor] = useState<StepForm | null>(null);
  const [enrolling, setEnrolling] = useState(false);
  const [confirm, setConfirm] = useState<"delete" | "reset" | null>(null);

  const load = useCallback(async () => {
    try {
      const res = await api.getDripCampaign(campaignId);
      setCampaign(res.campaign);
      setForm(formFromCampaign(res.campaign));
      setError(null);
    } catch (err) {
      setError(errorMessage(err, "Could not load this campaign."));
    } finally {
      setLoading(false);
    }
  }, [campaignId]);

  useEffect(() => {
    void load();
  }, [load]);

  const run = async (label: string, fn: () => Promise<unknown>, successNote?: string) => {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      await fn();
      await load();
      await onChanged();
      if (successNote) setNotice(successNote);
    } catch (err) {
      setError(errorMessage(err, `${label} failed.`));
    } finally {
      setBusy(false);
    }
  };

  const dirty = useMemo(() => {
    if (!campaign || !form) return false;
    return JSON.stringify(form) !== JSON.stringify(formFromCampaign(campaign));
  }, [campaign, form]);

  const clashes = useMemo(() => (campaign ? sameDayClashes(campaign.steps) : []), [campaign]);

  if (loading || !campaign || !form) {
    return (
      <div className="flex items-center gap-2 text-sm text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
        {error ?? "Loading campaign…"}
      </div>
    );
  }

  const saveMeta = () =>
    run("Save", () =>
      api.updateDripCampaign(campaign.id, {
        name: form.name,
        description: form.description,
        kind: form.kind,
        role: form.role,
        triggerSegment: form.triggerSegment || "",
        layerFlag: form.role === "layer" ? ((form.layerFlag || null) as "buying" | "selling" | null) : null,
        runOnce: form.runOnce,
        deferLayers: form.deferLayers,
        exitDay: form.exitDay.trim() ? Number(form.exitDay) : null,
        exitRule: form.exitRule,
        notes: form.notes,
        sourceUrl: form.sourceUrl,
      }),
      "Saved.",
    );

  const saveStep = () => {
    if (!stepEditor) return;
    const payload: DripStepInput = {
      day: Number(stepEditor.day) || 1,
      channel: stepEditor.channel,
      title: stepEditor.title.trim(),
      subject: stepEditor.channel === "email" ? stepEditor.subject || null : null,
      body: stepEditor.body || null,
      video: stepEditor.channel === "text" || stepEditor.channel === "email" ? stepEditor.video || null : null,
      notes: stepEditor.notes || null,
      routeTo: stepEditor.channel === "tag" ? stepEditor.routeTo || null : null,
    };
    if (!payload.title) {
      setError("Give the step a title.");
      return;
    }
    const id = stepEditor.id;
    void run(
      "Save step",
      () => (id ? api.updateDripStep(id, payload) : api.addDripStep(campaign.id, payload)),
      id ? "Step saved. Anyone on the campaign is rescheduled." : "Step added.",
    ).then(() => setStepEditor(null));
  };

  const enabledSegments = segments.filter((s) => s.enabled);

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex min-w-0 items-center gap-3">
          <Button variant="ghost" size="sm" onClick={onBack}>
            <ArrowLeft className="h-3.5 w-3.5" aria-hidden="true" />
            All campaigns
          </Button>
          <h2 className="truncate text-lg font-semibold text-foreground">{campaign.name}</h2>
          <Badge variant={campaign.enabled ? "success" : "secondary"}>{campaign.enabled ? "On" : "Off"}</Badge>
          {campaign.templateSlug && <Badge variant="outline">Elevation template</Badge>}
        </div>
        <div className="flex items-center gap-2">
          <span className="text-xs text-muted-foreground">{campaign.enabled ? "Running" : "Switched off"}</span>
          <Switch
            checked={campaign.enabled}
            onCheckedChange={(next) => void run("Toggle", () => api.setDripCampaignEnabled(campaign.id, next))}
            disabled={busy}
            className={campaign.enabled ? "border-success bg-success" : undefined}
            aria-label={campaign.enabled ? "Switch campaign off" : "Switch campaign on"}
          />
          <Button size="sm" onClick={() => setEnrolling(true)} disabled={!campaign.enabled || busy}>
            <Plus className="h-3.5 w-3.5" aria-hidden="true" />
            Add a contact
          </Button>
        </div>
      </div>

      {error && <Note tone="error">{error}</Note>}
      {notice && <Note tone="success">{notice}</Note>}

      <Section
        title="How it starts and stops"
        hint="Who it starts for, whether it runs alone or alongside, and what happens on the last day."
        actions={
          <Button size="sm" onClick={() => void saveMeta()} disabled={!dirty || busy}>
            {busy ? "Saving…" : "Save changes"}
          </Button>
        }
      >
        <div className="grid gap-3 md:grid-cols-2">
          <Field label="Name">
            <Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} disabled={busy} />
          </Field>
          <Field label="Kind">
            <Select value={form.kind} onValueChange={(v) => setForm({ ...form, kind: v as DripCampaignKind })} disabled={busy}>
              {(Object.keys(KIND_LABELS) as DripCampaignKind[]).map((k) => (
                <SelectOption key={k} value={k}>
                  {KIND_LABELS[k]}
                </SelectOption>
              ))}
            </Select>
          </Field>
          <Field label="Description" className="md:col-span-2">
            <textarea className={fieldClass} rows={2} value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} disabled={busy} />
          </Field>
          <Field label="Runs" hint="One at a time: starting it ends any other nurture campaign. Alongside: it layers on top (courses).">
            <Select value={form.role} onValueChange={(v) => setForm({ ...form, role: v as DripCampaignRole })} disabled={busy}>
              {(Object.keys(ROLE_LABELS) as DripCampaignRole[]).map((r) => (
                <SelectOption key={r} value={r}>
                  {ROLE_LABELS[r]}
                </SelectOption>
              ))}
            </Select>
          </Field>
          <Field label="Starts automatically when a contact becomes" hint="Leave blank to only start it by hand.">
            <Select value={form.triggerSegment || "none"} onValueChange={(v) => setForm({ ...form, triggerSegment: v === "none" ? "" : v })} disabled={busy}>
              <SelectOption value="none">Nobody (start by hand)</SelectOption>
              {enabledSegments.map((s) => (
                <SelectOption key={s.key} value={s.key}>
                  {s.label}
                </SelectOption>
              ))}
            </Select>
          </Field>
          {form.role === "layer" && (
            <Field label="Layer onto" hint="Starts for everyone flagged as buying or selling the day their segment is set.">
              <Select value={form.layerFlag || "none"} onValueChange={(v) => setForm({ ...form, layerFlag: v === "none" ? "" : v })} disabled={busy}>
                <SelectOption value="none">Nobody automatically</SelectOption>
                <SelectOption value="buying">Everyone who is buying</SelectOption>
                <SelectOption value="selling">Everyone who is selling</SelectOption>
              </Select>
            </Field>
          )}
          <Field label="Exit day" hint="The day the campaign routes them on. Add a tag step on this day to move the segment.">
            <Input type="number" min={1} value={form.exitDay} onChange={(e) => setForm({ ...form, exitDay: e.target.value })} disabled={busy} />
          </Field>
          <Field label="Exit rule" className="md:col-span-2">
            <textarea className={fieldClass} rows={2} value={form.exitRule} onChange={(e) => setForm({ ...form, exitRule: e.target.value })} disabled={busy} />
          </Field>
          <div className="flex flex-col gap-2 md:col-span-2">
            <label className="flex items-center gap-2 text-xs text-foreground">
              <Switch checked={form.runOnce} onCheckedChange={(v) => setForm({ ...form, runOnce: v })} disabled={busy} aria-label="Runs once per person" />
              Runs once per person (a course)
            </label>
            <label className="flex items-center gap-2 text-xs text-foreground">
              <Switch checked={form.deferLayers} onCheckedChange={(v) => setForm({ ...form, deferLayers: v })} disabled={busy} aria-label="Hold the courses until this campaign routes them" />
              Hold the courses until this campaign routes them (The First 14 Days does this)
            </label>
          </div>
          <Field label="Notes and checklist" hint="Shown on the campaign card. Playbooks keep their checklist here." className="md:col-span-2">
            <textarea className={fieldClass} rows={5} value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} disabled={busy} />
          </Field>
          <Field label="Source PDF or guide link" className="md:col-span-2">
            <div className="flex items-center gap-2">
              <Input value={form.sourceUrl} onChange={(e) => setForm({ ...form, sourceUrl: e.target.value })} disabled={busy} placeholder="https://" />
              {campaign.sourceUrl && (
                <a href={campaign.sourceUrl} target="_blank" rel="noreferrer" className="inline-flex shrink-0 items-center gap-1 text-xs text-foreground underline-offset-4 hover:underline">
                  Open <ExternalLink className="h-3 w-3" aria-hidden="true" />
                </a>
              )}
            </div>
          </Field>
        </div>
      </Section>

      <Section
        title={`Steps (${campaign.steps.length})`}
        hint="Day 1 is the day the campaign starts. Calls and tasks go on your task list; texts and emails go out on their day; a tag step moves the segment."
        actions={
          <Button size="sm" variant="outline" onClick={() => setStepEditor({ ...EMPTY_STEP, day: nextDay(campaign.steps) })} disabled={busy || !!stepEditor}>
            <Plus className="h-3.5 w-3.5" aria-hidden="true" />
            Add step
          </Button>
        }
      >
        {clashes.length > 0 && (
          <Note tone="warning" className="mb-3">
            Two sends land on the same day for day {clashes.join(", ")}. Move one so nobody gets two messages at once.
          </Note>
        )}
        {campaign.steps.length === 0 && !stepEditor && (
          <p className="text-xs text-muted-foreground">No steps yet. Add the first touch.</p>
        )}
        <ol className="flex flex-col gap-2">
          {campaign.steps.map((step) =>
            stepEditor?.id === step.id ? (
              <li key={step.id}>
                <StepEditor
                  value={stepEditor}
                  segments={enabledSegments}
                  videos={videos}
                  busy={busy}
                  onChange={setStepEditor}
                  onSave={saveStep}
                  onCancel={() => setStepEditor(null)}
                />
              </li>
            ) : (
              <li key={step.id}>
                <StepRow
                  step={step}
                  segments={segments}
                  videos={videos}
                  busy={busy}
                  onEdit={() =>
                    setStepEditor({
                      id: step.id,
                      day: step.day,
                      channel: step.channel,
                      title: step.title,
                      subject: step.subject ?? "",
                      body: step.body ?? "",
                      video: step.video ?? "",
                      notes: step.notes ?? "",
                      routeTo: step.routeTo ?? "",
                    })
                  }
                  onDelete={() => void run("Delete step", () => api.deleteDripStep(step.id), "Step removed.")}
                />
              </li>
            ),
          )}
          {stepEditor && !stepEditor.id && (
            <li>
              <StepEditor
                value={stepEditor}
                segments={enabledSegments}
                videos={videos}
                busy={busy}
                onChange={setStepEditor}
                onSave={saveStep}
                onCancel={() => setStepEditor(null)}
              />
            </li>
          )}
        </ol>
      </Section>

      <Section
        title={`People on it (${campaign.enrollments.filter((e) => e.status === "active" || e.status === "paused").length})`}
        hint="Pause someone to hold their schedule, stop them to end it. Finished runs stay here for the record."
      >
        <EnrollmentList
          enrollments={campaign.enrollments}
          busy={busy}
          onPause={(e) => void run("Pause", () => api.pauseDripEnrollment(e.id))}
          onResume={(e) => void run("Resume", () => api.resumeDripEnrollment(e.id))}
          onStop={(e) => void run("Stop", () => api.stopDripEnrollment(e.id, "stopped from the dashboard"))}
        />
      </Section>

      <Section title="Copy, reset or delete">
        <div className="flex flex-wrap gap-2">
          <Button variant="outline" size="sm" disabled={busy} onClick={() => void run("Duplicate", () => api.duplicateDripCampaign(campaign.id), "Copy made (switched off, no automatic start). Find it in the list.")}>
            Make a copy
          </Button>
          {campaign.templateSlug && (
            <Button variant="outline" size="sm" disabled={busy} onClick={() => setConfirm("reset")}>
              Reset to the Elevation original
            </Button>
          )}
          <Button variant="destructive" size="sm" disabled={busy} onClick={() => setConfirm("delete")}>
            Delete campaign
          </Button>
        </div>
      </Section>

      {enrolling && (
        <EnrollDialog
          campaign={campaign}
          segments={segments}
          onClose={() => setEnrolling(false)}
          onEnrolled={async () => {
            await load();
            await onChanged();
          }}
        />
      )}
      <ConfirmDialog
        open={confirm === "delete"}
        title={`Delete "${campaign.name}"?`}
        description="Everyone still on it is taken off and their remaining touches are cancelled. This cannot be undone."
        confirmLabel="Delete"
        destructive
        loading={busy}
        onCancel={() => setConfirm(null)}
        onConfirm={() => {
          setConfirm(null);
          void run("Delete", () => api.deleteDripCampaign(campaign.id, true)).then(onBack);
        }}
      />
      <ConfirmDialog
        open={confirm === "reset"}
        title="Reset to the Elevation original?"
        description="Your edits to the copy, days and settings are replaced with the template. People still on it get the template schedule from today onward."
        confirmLabel="Reset"
        loading={busy}
        onCancel={() => setConfirm(null)}
        onConfirm={() => {
          setConfirm(null);
          void run("Reset", () => api.resetDripCampaign(campaign.id), "Back to the Elevation original.");
        }}
      />
    </div>
  );
}

function nextDay(steps: DripStep[]): number {
  const max = steps.reduce((m, s) => Math.max(m, s.day), 0);
  return max + 1;
}

function StepRow({
  step,
  segments,
  videos,
  busy,
  onEdit,
  onDelete,
}: {
  step: DripStep;
  segments: DripSegment[];
  videos: DripVideo[];
  busy: boolean;
  onEdit: () => void;
  onDelete: () => void;
}) {
  const video = step.video ? videos.find((v) => v.slug === step.video) : null;
  const routeLabel =
    step.routeTo === "done" ? "finish the course" : step.routeTo === "restart" ? "start again at day 1" : step.routeTo ? `move to ${segmentLabel(segments, step.routeTo)}` : null;
  return (
    <div className="grid gap-2 rounded-md border border-border px-3 py-2 md:grid-cols-[4.5rem_1fr_auto]">
      <div className="font-mono-ui text-[0.72rem] text-muted-foreground">Day {step.day}</div>
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-1.5">
          <ChannelBadge channel={step.channel} />
          <span className="text-sm font-medium text-foreground">{step.title}</span>
          {routeLabel && <span className="text-xs text-muted-foreground">· {routeLabel}</span>}
        </div>
        {step.subject && <div className="mt-1 text-xs text-foreground">Subject: {step.subject}</div>}
        {step.body && <p className="mt-1 line-clamp-2 whitespace-pre-line text-xs leading-5 text-muted-foreground">{step.body}</p>}
        <div className="mt-1 flex flex-wrap gap-x-3 text-[0.7rem] text-muted-foreground">
          {video && <span>Video: {video.name}{video.link ? "" : " (not recorded yet)"}</span>}
          {step.notes && <span className="line-clamp-1">{step.notes}</span>}
        </div>
      </div>
      <div className="flex items-start gap-1">
        <Button variant="ghost" size="sm" onClick={onEdit} disabled={busy}>
          Edit
        </Button>
        <Button variant="ghost" size="sm" className="text-destructive" onClick={onDelete} disabled={busy}>
          Remove
        </Button>
      </div>
    </div>
  );
}

function StepEditor({
  value,
  segments,
  videos,
  busy,
  onChange,
  onSave,
  onCancel,
}: {
  value: StepForm;
  segments: DripSegment[];
  videos: DripVideo[];
  busy: boolean;
  onChange: (next: StepForm) => void;
  onSave: () => void;
  onCancel: () => void;
}) {
  const isSend = value.channel === "text" || value.channel === "email";
  return (
    <div className="grid gap-3 rounded-md border border-border bg-muted/20 p-3 md:grid-cols-4">
      <Field label="Day">
        <Input type="number" min={1} value={String(value.day)} onChange={(e) => onChange({ ...value, day: Number(e.target.value) || 1 })} disabled={busy} />
      </Field>
      <Field label="Channel">
        <Select value={value.channel} onValueChange={(v) => onChange({ ...value, channel: v as DripChannel })} disabled={busy}>
          {CHANNEL_OPTIONS.map((c) => (
            <SelectOption key={c} value={c}>
              {CHANNEL_LABELS[c]}
            </SelectOption>
          ))}
        </Select>
      </Field>
      <Field label="Title" className="md:col-span-2">
        <Input value={value.title} onChange={(e) => onChange({ ...value, title: e.target.value })} disabled={busy} placeholder="What goes out" />
      </Field>
      {value.channel === "email" && (
        <Field label="Subject" className="md:col-span-4">
          <Input value={value.subject ?? ""} onChange={(e) => onChange({ ...value, subject: e.target.value })} disabled={busy} />
        </Field>
      )}
      {value.channel === "tag" ? (
        <Field label="Move them to" hint="Fires automatically on its day while the contact is still in this campaign's segment." className="md:col-span-2">
          <Select value={value.routeTo || "none"} onValueChange={(v) => onChange({ ...value, routeTo: v === "none" ? "" : v })} disabled={busy}>
            <SelectOption value="none">Decide by hand on the board</SelectOption>
            {segments.map((s) => (
              <SelectOption key={s.key} value={s.key}>
                {s.label}
              </SelectOption>
            ))}
            <SelectOption value="done">Finish the course (runs once)</SelectOption>
            <SelectOption value="restart">Start again at day 1</SelectOption>
          </Select>
        </Field>
      ) : null}
      <Field label={value.channel === "call" ? "What to say" : value.channel === "task" ? "What to do" : "Message"} className="md:col-span-4">
        <textarea className={fieldClass} rows={6} value={value.body ?? ""} onChange={(e) => onChange({ ...value, body: e.target.value })} disabled={busy} placeholder="Use [First Name], [Your Name], [Brokerage], [Area]… The board fills in what it knows and flags the rest." />
      </Field>
      {isSend && (
        <Field label="Video" hint="Put [Insert video: Name] in the message; the recorded link drops in on the board." className="md:col-span-2">
          <Select value={value.video || "none"} onValueChange={(v) => onChange({ ...value, video: v === "none" ? "" : v })} disabled={busy}>
            <SelectOption value="none">No video</SelectOption>
            {videos.map((v) => (
              <SelectOption key={v.slug} value={v.slug}>
                {v.name}{v.link ? "" : " (not recorded)"}
              </SelectOption>
            ))}
          </Select>
        </Field>
      )}
      <Field label="Notes for you" className="md:col-span-2">
        <Input value={value.notes ?? ""} onChange={(e) => onChange({ ...value, notes: e.target.value })} disabled={busy} placeholder="No answer? Voice note, same words." />
      </Field>
      <div className="flex justify-end gap-2 md:col-span-4">
        <Button variant="outline" size="sm" onClick={onCancel} disabled={busy}>
          Cancel
        </Button>
        <Button size="sm" onClick={onSave} disabled={busy}>
          {busy ? "Saving…" : value.id ? "Save step" : "Add step"}
        </Button>
      </div>
    </div>
  );
}

const STATUS_VARIANT: Record<DripEnrollment["status"], "success" | "warning" | "secondary" | "outline"> = {
  active: "success",
  paused: "warning",
  completed: "secondary",
  stopped: "outline",
};

export function EnrollmentList({
  enrollments,
  busy,
  onPause,
  onResume,
  onStop,
  showCampaign = false,
}: {
  enrollments: DripEnrollment[];
  busy: boolean;
  onPause: (e: DripEnrollment) => void;
  onResume: (e: DripEnrollment) => void;
  onStop: (e: DripEnrollment) => void;
  showCampaign?: boolean;
}) {
  if (enrollments.length === 0) {
    return <p className="text-xs text-muted-foreground">Nobody yet.</p>;
  }
  return (
    <ul className="divide-y divide-border rounded-md border border-border">
      {enrollments.map((e) => {
        const live = e.status === "active" || e.status === "paused";
        return (
          <li key={e.id} className="flex flex-wrap items-center justify-between gap-2 px-3 py-2">
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-1.5">
                <span className="text-sm font-medium text-foreground">{showCampaign ? e.campaignName : e.contactName ?? "(no name)"}</span>
                <Badge variant={STATUS_VARIANT[e.status]}>{e.status}</Badge>
              </div>
              <div className="font-mono-ui text-[0.7rem] text-muted-foreground">
                day 1 {e.startDate}
                {e.nextDue ? ` · next ${e.nextDue}` : ""}
                {typeof e.doneCount === "number" ? ` · ${e.doneCount} done, ${e.scheduledCount ?? 0} to go` : ""}
                {e.stopReason ? ` · ${e.stopReason}` : ""}
              </div>
            </div>
            {live && (
              <div className="flex gap-1">
                {e.status === "active" ? (
                  <Button variant="ghost" size="sm" onClick={() => onPause(e)} disabled={busy}>
                    Pause
                  </Button>
                ) : (
                  <Button variant="ghost" size="sm" onClick={() => onResume(e)} disabled={busy}>
                    Resume
                  </Button>
                )}
                <Button variant="ghost" size="sm" className="text-destructive" onClick={() => onStop(e)} disabled={busy}>
                  Stop
                </Button>
              </div>
            )}
          </li>
        );
      })}
    </ul>
  );
}

export function TriggerSummary({ campaign, segments }: { campaign: DripCampaignDetail; segments: DripSegment[] }) {
  const trigger = campaign.triggerSegment ? segments.find((s) => s.key === campaign.triggerSegment) ?? null : null;
  if (!trigger) return <span className="text-xs text-muted-foreground">Starts by hand</span>;
  return (
    <span className="inline-flex items-center gap-1.5 text-xs text-muted-foreground">
      Starts when a contact becomes <SegmentChip segment={trigger} />
    </span>
  );
}
