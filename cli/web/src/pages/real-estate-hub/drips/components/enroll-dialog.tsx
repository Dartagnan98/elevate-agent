import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Modal } from "@/components/ui/modal";
import { api } from "@/lib/api";
import type { DripCampaign, DripContact, DripEnrollment, DripSegment } from "@/lib/api";
import { errorMessage, isoToday } from "../drips-helpers";
import { ContactPicker } from "./contact-picker";
import { Field, Note, fieldClass } from "./shared";

export function EnrollDialog({
  campaign,
  segments,
  onClose,
  onEnrolled,
}: {
  campaign: DripCampaign;
  segments: DripSegment[];
  onClose: () => void;
  onEnrolled: (enrollment: DripEnrollment) => void | Promise<void>;
}) {
  const [contact, setContact] = useState<DripContact | null>(null);
  const [startDate, setStartDate] = useState(isoToday());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const enroll = async () => {
    if (!contact) return;
    setBusy(true);
    setError(null);
    try {
      const res = await api.enrollDripContact({ campaignId: campaign.id, contactId: contact.id, startDate });
      await onEnrolled(res.enrollment);
      onClose();
    } catch (err) {
      setError(errorMessage(err, "Could not start the campaign for this contact."));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal title={`Put someone on ${campaign.name}`} onClose={onClose} wide>
      <div className="flex flex-col gap-3">
        {!campaign.enabled && <Note tone="warning">This campaign is switched off. Turn it on before adding people.</Note>}
        {contact ? (
          <div className="flex items-center justify-between gap-3 rounded-md border border-border px-3 py-2">
            <div className="min-w-0">
              <div className="truncate text-sm font-medium text-foreground">{contact.name}</div>
              <div className="truncate text-[0.72rem] text-muted-foreground">
                {[contact.email, contact.phone].filter(Boolean).join(" · ")}
              </div>
            </div>
            <Button variant="ghost" size="sm" onClick={() => setContact(null)} disabled={busy}>
              Change
            </Button>
          </div>
        ) : (
          <ContactPicker segments={segments} onPick={setContact} autoFocus />
        )}
        <Field label="Day 1" hint="Day 1 is the day the campaign starts. Every step counts from here.">
          <input type="date" className={fieldClass} value={startDate} onChange={(e) => setStartDate(e.target.value)} disabled={busy} />
        </Field>
        {campaign.role === "primary" && (
          <Note>One nurture campaign at a time: starting this one ends any other nurture campaign they are on.</Note>
        )}
        {error && <Note tone="error">{error}</Note>}
        <div className="flex justify-end gap-2">
          <Button variant="outline" size="sm" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button size="sm" onClick={() => void enroll()} disabled={busy || !contact || !campaign.enabled}>
            {busy ? "Starting…" : "Start campaign"}
          </Button>
        </div>
      </div>
    </Modal>
  );
}
