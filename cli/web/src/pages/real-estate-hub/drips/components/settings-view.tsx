import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { api } from "@/lib/api";
import type { DripSettings } from "@/lib/api";
import { errorMessage } from "../drips-helpers";
import { Field, Note, Section } from "./shared";

export function SettingsView({ settings, onChanged }: { settings: DripSettings; onChanged: () => Promise<void> | void }) {
  const [form, setForm] = useState<DripSettings>(settings);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    setForm(settings);
  }, [settings]);

  const dirty = JSON.stringify(form) !== JSON.stringify(settings);

  const save = async () => {
    setBusy(true);
    setError(null);
    setSaved(false);
    try {
      await api.updateDripSettings({
        autoEnrollNewLeads: form.autoEnrollNewLeads,
        autoTagMoves: form.autoTagMoves,
        sendWindowStart: form.sendWindowStart,
        sendWindowEnd: form.sendWindowEnd,
        callsAsTasks: form.callsAsTasks,
        pauseAiDraftsInCampaigns: form.pauseAiDraftsInCampaigns,
        newsletterTool: form.newsletterTool,
      });
      await onChanged();
      setSaved(true);
    } catch (err) {
      setError(errorMessage(err, "Could not save settings."));
    } finally {
      setBusy(false);
    }
  };

  const toggle = (key: keyof DripSettings, label: string, hint: string) => (
    <label className="flex items-start justify-between gap-4 rounded-md border border-border px-3 py-2">
      <span className="min-w-0">
        <span className="block text-sm font-medium text-foreground">{label}</span>
        <span className="block text-xs leading-5 text-muted-foreground">{hint}</span>
      </span>
      <Switch checked={Boolean(form[key])} onCheckedChange={(v) => setForm({ ...form, [key]: v })} disabled={busy} aria-label={label} />
    </label>
  );

  return (
    <Section
      title="How the engine runs"
      hint="These are the Elevation defaults. Change any of them to fit how you work."
      actions={
        <Button size="sm" onClick={() => void save()} disabled={!dirty || busy}>
          {busy ? "Saving…" : "Save settings"}
        </Button>
      }
    >
      <div className="flex flex-col gap-3">
        {error && <Note tone="error">{error}</Note>}
        {saved && !dirty && <Note tone="success">Saved.</Note>}
        {toggle(
          "autoEnrollNewLeads",
          "Start new leads automatically",
          `Every new buyer or seller lead goes into the New segment the day it lands, which starts The First 14 Days. Only leads created after you switch this on${settings.autoEnrollSince ? ` (${settings.autoEnrollSince.slice(0, 10)})` : ""}; your existing book is never swept.`,
        )}
        {toggle(
          "autoTagMoves",
          "Automatic tag moves",
          "Day 15, day 92, day 187, day 101 and day 367 move the segment on their own and leave a note on the contact card. Off means every one of those shows up on the board as a decision for you.",
        )}
        {toggle(
          "callsAsTasks",
          "Calls become tasks",
          "A call touch lands on your Tasks board the day it is due, with the script attached.",
        )}
        {toggle(
          "pauseAiDraftsInCampaigns",
          "Pause AI first-touch drafts for people on a campaign",
          "The outreach agent leaves anyone running through a campaign alone, so the campaign is the only voice they hear.",
        )}
        <div className="grid gap-3 sm:grid-cols-3">
          <Field label="Send window starts" hint="Nothing goes out earlier than this.">
            <Input type="time" value={form.sendWindowStart} onChange={(e) => setForm({ ...form, sendWindowStart: e.target.value })} disabled={busy} />
          </Field>
          <Field label="Send window ends">
            <Input type="time" value={form.sendWindowEnd} onChange={(e) => setForm({ ...form, sendWindowEnd: e.target.value })} disabled={busy} />
          </Field>
          <Field label="Newsletter tool" hint="Your monthly newsletter stays where it is; the campaigns never replace it.">
            <Input value={form.newsletterTool ?? ""} onChange={(e) => setForm({ ...form, newsletterTool: e.target.value })} disabled={busy} placeholder="Mailjet" />
          </Field>
        </div>
      </div>
    </Section>
  );
}
