import { useState } from "react";
import { ArrowDown, ArrowUp, Plus } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { api } from "@/lib/api";
import type { DripContact, DripContactState, DripSegment } from "@/lib/api";
import { errorMessage, isoToday, segmentColor } from "../drips-helpers";
import { EnrollmentList } from "./campaign-detail";
import { ContactPicker } from "./contact-picker";
import { Field, Note, SegmentChip, Section, fieldClass } from "./shared";

type SegmentForm = { label: string; windowLabel: string; description: string; color: string };

export function SegmentsView({
  segments,
  onChanged,
}: {
  segments: DripSegment[];
  onChanged: () => Promise<void> | void;
}) {
  const [editing, setEditing] = useState<string | null>(null);
  const [form, setForm] = useState<SegmentForm>({ label: "", windowLabel: "", description: "", color: "#6B8EF2" });
  const [adding, setAdding] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<DripSegment | null>(null);

  const run = async (fn: () => Promise<unknown>) => {
    setBusy(true);
    setError(null);
    try {
      await fn();
      await onChanged();
      return true;
    } catch (err) {
      setError(errorMessage(err, "Could not update segments."));
      return false;
    } finally {
      setBusy(false);
    }
  };

  const startEdit = (seg: DripSegment) => {
    setAdding(false);
    setEditing(seg.key);
    setForm({ label: seg.label, windowLabel: seg.windowLabel ?? "", description: seg.description ?? "", color: segmentColor(seg) });
  };

  const save = async () => {
    if (!form.label.trim()) {
      setError("Give the segment a name.");
      return;
    }
    const ok = await run(() =>
      editing
        ? api.updateDripSegment(editing, { label: form.label, windowLabel: form.windowLabel, description: form.description, color: form.color })
        : api.createDripSegment({ label: form.label, windowLabel: form.windowLabel, description: form.description, color: form.color }),
    );
    if (ok) {
      setEditing(null);
      setAdding(false);
    }
  };

  const move = (index: number, dir: -1 | 1) => {
    const keys = segments.map((s) => s.key);
    const target = index + dir;
    if (target < 0 || target >= keys.length) return;
    [keys[index], keys[target]] = [keys[target], keys[index]];
    void run(() => api.reorderDripSegments(keys));
  };

  return (
    <div className="flex flex-col gap-4">
      <Section
        title="Your pipeline segments"
        hint="Rename them to match how you talk about your pipeline. Each segment can start a campaign the day a contact moves into it. The order here is the order everywhere."
        actions={
          <Button size="sm" onClick={() => { setEditing(null); setAdding(true); setForm({ label: "", windowLabel: "", description: "", color: "#6B8EF2" }); }} disabled={busy || adding}>
            <Plus className="h-3.5 w-3.5" aria-hidden="true" />
            Add segment
          </Button>
        }
      >
        {error && <Note tone="error" className="mb-3">{error}</Note>}
        <ul className="flex flex-col gap-2">
          {segments.map((seg, index) =>
            editing === seg.key ? (
              <li key={seg.key}>
                <SegmentEditor form={form} onChange={setForm} busy={busy} onSave={() => void save()} onCancel={() => setEditing(null)} />
              </li>
            ) : (
              <li key={seg.key} className={`grid gap-2 rounded-md border border-border px-3 py-2 md:grid-cols-[auto_1fr_auto] ${seg.enabled ? "" : "opacity-70"}`}>
                <div className="flex flex-col gap-0.5">
                  <Button variant="ghost" size="icon" className="h-6 w-6" onClick={() => move(index, -1)} disabled={busy || index === 0} aria-label={`Move ${seg.label} up`}>
                    <ArrowUp className="h-3 w-3" aria-hidden="true" />
                  </Button>
                  <Button variant="ghost" size="icon" className="h-6 w-6" onClick={() => move(index, 1)} disabled={busy || index === segments.length - 1} aria-label={`Move ${seg.label} down`}>
                    <ArrowDown className="h-3 w-3" aria-hidden="true" />
                  </Button>
                </div>
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <SegmentChip segment={seg} />
                    {seg.windowLabel && <span className="font-mono-ui text-[0.7rem] text-muted-foreground">{seg.windowLabel}</span>}
                    {!seg.enabled && <Badge variant="secondary">Off</Badge>}
                    {seg.builtin && <Badge variant="outline">Elevation</Badge>}
                  </div>
                  {seg.description && <p className="mt-1 text-xs leading-5 text-muted-foreground">{seg.description}</p>}
                  <div className="mt-1 flex flex-wrap gap-x-3 text-[0.7rem] text-muted-foreground">
                    <span>{seg.contactCount ?? 0} contacts</span>
                    <span>{seg.campaigns && seg.campaigns.length > 0 ? `starts ${seg.campaigns.join(", ")}` : "starts nothing automatically"}</span>
                  </div>
                </div>
                <div className="flex items-start gap-1">
                  <Switch checked={seg.enabled} onCheckedChange={(v) => void run(() => api.updateDripSegment(seg.key, { enabled: v }))} disabled={busy} aria-label={`${seg.enabled ? "Switch off" : "Switch on"} ${seg.label}`} />
                  <Button variant="ghost" size="sm" onClick={() => startEdit(seg)} disabled={busy}>
                    Edit
                  </Button>
                  <Button variant="ghost" size="sm" className="text-destructive" onClick={() => setDeleteTarget(seg)} disabled={busy}>
                    Delete
                  </Button>
                </div>
              </li>
            ),
          )}
          {adding && (
            <li>
              <SegmentEditor form={form} onChange={setForm} busy={busy} onSave={() => void save()} onCancel={() => setAdding(false)} />
            </li>
          )}
        </ul>
      </Section>

      <MoveContactPanel segments={segments} onChanged={onChanged} />

      <ConfirmDialog
        open={deleteTarget !== null}
        title={`Delete "${deleteTarget?.label ?? "segment"}"?`}
        description="Only an empty segment that starts no campaign can be deleted. Move the contacts out and change any campaign triggers first."
        confirmLabel="Delete"
        destructive
        loading={busy}
        onCancel={() => setDeleteTarget(null)}
        onConfirm={() => {
          const target = deleteTarget;
          setDeleteTarget(null);
          if (target) void run(() => api.deleteDripSegment(target.key));
        }}
      />
    </div>
  );
}

function SegmentEditor({
  form,
  onChange,
  busy,
  onSave,
  onCancel,
}: {
  form: SegmentForm;
  onChange: (next: SegmentForm) => void;
  busy: boolean;
  onSave: () => void;
  onCancel: () => void;
}) {
  return (
    <div className="grid gap-3 rounded-md border border-border bg-muted/20 p-3 md:grid-cols-[1fr_1fr_auto]">
      <Field label="Name">
        <Input value={form.label} onChange={(e) => onChange({ ...form, label: e.target.value })} disabled={busy} placeholder="Warm" />
      </Field>
      <Field label="Window" hint="How you describe it: 30 to 90 days, past clients, …">
        <Input value={form.windowLabel} onChange={(e) => onChange({ ...form, windowLabel: e.target.value })} disabled={busy} />
      </Field>
      <Field label="Colour">
        <input type="color" className="h-9 w-14 cursor-pointer rounded-sm border border-input bg-field" value={form.color} onChange={(e) => onChange({ ...form, color: e.target.value })} disabled={busy} aria-label="Segment colour" />
      </Field>
      <Field label="What it means" className="md:col-span-3">
        <textarea className={fieldClass} rows={2} value={form.description} onChange={(e) => onChange({ ...form, description: e.target.value })} disabled={busy} />
      </Field>
      <div className="flex justify-end gap-2 md:col-span-3">
        <Button variant="outline" size="sm" onClick={onCancel} disabled={busy}>
          Cancel
        </Button>
        <Button size="sm" onClick={onSave} disabled={busy}>
          {busy ? "Saving…" : "Save"}
        </Button>
      </div>
    </div>
  );
}

export function MoveContactPanel({
  segments,
  onChanged,
  title = "Move a contact",
}: {
  segments: DripSegment[];
  onChanged: () => Promise<void> | void;
  title?: string;
}) {
  const [picked, setPicked] = useState<DripContact | null>(null);
  const [state, setState] = useState<DripContactState | null>(null);
  const [buying, setBuying] = useState(false);
  const [selling, setSelling] = useState(false);
  const [note, setNote] = useState("");
  const [startDate, setStartDate] = useState(isoToday());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<string | null>(null);

  const pick = async (contact: DripContact) => {
    setPicked(contact);
    setResult(null);
    setError(null);
    try {
      const res = await api.getDripContact(contact.id);
      setState(res.contact);
      setBuying(res.contact.buying);
      setSelling(res.contact.selling);
    } catch (err) {
      setError(errorMessage(err, "Could not load this contact."));
    }
  };

  const move = async (segment: string | null) => {
    if (!picked) return;
    setBusy(true);
    setError(null);
    try {
      const res = await api.setDripContactSegment(picked.id, { segment, buying, selling, note: note || undefined, startDate });
      setState(res.contact);
      const started = res.contact.started ?? [];
      const stopped = res.contact.stopped ?? [];
      setResult(
        segment === null
          ? "Removed from every campaign."
          : `Now ${segments.find((s) => s.key === segment)?.label ?? segment}.${started.length ? ` Started ${started.map((s) => s.campaignName).join(", ")}.` : ""}${stopped.length ? ` Ended ${stopped.length} campaign${stopped.length === 1 ? "" : "s"}.` : ""}`,
      );
      await onChanged();
    } catch (err) {
      setError(errorMessage(err, "Could not move this contact."));
    } finally {
      setBusy(false);
    }
  };

  const current = state?.segment ? segments.find((s) => s.key === state.segment) ?? null : null;

  return (
    <Section
      title={title}
      hint="Pick a contact, tell the system whether they are buying or selling, and move them into the segment that matches what they told you. The campaigns start and stop on their own."
    >
      <div className="grid gap-4 lg:grid-cols-2">
        <ContactPicker segments={segments} onPick={(c) => void pick(c)} />
        <div className="flex flex-col gap-3">
          {!picked && <p className="text-xs text-muted-foreground">Search on the left to pick someone.</p>}
          {picked && (
            <>
              <div className="rounded-md border border-border px-3 py-2">
                <div className="text-sm font-medium text-foreground">{picked.name}</div>
                <div className="mt-1 flex flex-wrap items-center gap-2 text-[0.72rem] text-muted-foreground">
                  {state?.segment ? <SegmentChip segment={current} label={current?.label ?? state.segment} /> : <span>No segment yet</span>}
                  {state?.segmentSetAt && <span>since {state.segmentSetAt.slice(0, 10)}</span>}
                  {state?.segmentNote && <span>· {state.segmentNote}</span>}
                </div>
              </div>
              <div className="flex flex-wrap gap-4 text-xs text-foreground">
                <label className="flex items-center gap-2">
                  <Switch checked={buying} onCheckedChange={setBuying} disabled={busy} aria-label="Buying" />
                  Buying (layers the Buyer Course)
                </label>
                <label className="flex items-center gap-2">
                  <Switch checked={selling} onCheckedChange={setSelling} disabled={busy} aria-label="Selling" />
                  Selling (layers the Seller Course)
                </label>
              </div>
              <div className="grid gap-3 sm:grid-cols-2">
                <Field label="Why" hint="Goes on their contact card.">
                  <Input value={note} onChange={(e) => setNote(e.target.value)} disabled={busy} placeholder="said spring, pre-approved…" />
                </Field>
                <Field label="Day 1">
                  <input type="date" className={fieldClass} value={startDate} onChange={(e) => setStartDate(e.target.value)} disabled={busy} />
                </Field>
              </div>
              <div className="flex flex-wrap gap-1.5">
                {segments.filter((s) => s.enabled).map((s) => (
                  <Button
                    key={s.key}
                    size="sm"
                    variant={state?.segment === s.key ? "default" : "outline"}
                    disabled={busy}
                    onClick={() => void move(s.key)}
                  >
                    <span className="h-2 w-2 rounded-full" style={{ background: segmentColor(s) }} aria-hidden="true" />
                    {s.label}
                  </Button>
                ))}
                <Button size="sm" variant="ghost" className="text-destructive" disabled={busy || !state?.segment} onClick={() => void move(null)}>
                  Remove from all campaigns
                </Button>
              </div>
              {error && <Note tone="error">{error}</Note>}
              {result && <Note tone="success">{result}</Note>}
              {state && state.enrollments.length > 0 && (
                <EnrollmentList
                  enrollments={state.enrollments}
                  busy={busy}
                  showCampaign
                  onPause={(e) => void api.pauseDripEnrollment(e.id).then(() => pick(picked))}
                  onResume={(e) => void api.resumeDripEnrollment(e.id).then(() => pick(picked))}
                  onStop={(e) => void api.stopDripEnrollment(e.id).then(() => pick(picked))}
                />
              )}
            </>
          )}
        </div>
      </div>
    </Section>
  );
}
