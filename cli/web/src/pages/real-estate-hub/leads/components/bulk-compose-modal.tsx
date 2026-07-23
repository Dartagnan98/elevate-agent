import { useCallback, useEffect, useMemo, useState } from "react";

import { api } from "@/lib/api";
import type { LeadsProfile } from "../leads-data";

interface ComposeSkip {
  contactId: string;
  reason: string;
}

interface ComposeResult {
  created: number;
  skipped: ComposeSkip[];
}

/**
 * Mass Text / Mass Email composer for the bulk bar. Creates one
 * pending-approval draft per selected lead via /api/source-inbox/compose —
 * nothing sends until each draft is approved in the queue.
 */
export function BulkComposeModal({
  channel,
  profiles,
  onClose,
  onDone,
}: {
  channel: "sms" | "email";
  profiles: LeadsProfile[];
  /** Close without having created drafts — selection is kept. */
  onClose: () => void;
  /** Close after drafts were created — parent clears the selection. */
  onDone: (summary: string) => void;
}) {
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<ComposeResult | null>(null);

  // Only leads with a linked contact record can receive a composed draft;
  // the rest are counted and reported as skipped up front.
  const recipients = useMemo(
    () => profiles.filter((profile) => (profile.contactIds?.[0] || "").trim()),
    [profiles],
  );
  const missingContact = profiles.length - recipients.length;
  const nameByContactId = useMemo(() => {
    const map = new Map<string, string>();
    for (const profile of recipients) map.set(profile.contactIds![0], profile.name);
    return map;
  }, [recipients]);

  const title = channel === "sms" ? "Mass Text" : "Mass Email";

  const summaryFor = (res: ComposeResult) => {
    const skippedTotal = res.skipped.length + missingContact;
    const skippedNote = skippedTotal > 0 ? ` ${skippedTotal} skipped.` : "";
    return `${res.created} draft${res.created === 1 ? "" : "s"} created — review them in the approval queue.${skippedNote}`;
  };

  const close = useCallback(() => {
    if (busy) return;
    if (result) onDone(summaryFor(result));
    else onClose();
  }, [busy, result, missingContact, onClose, onDone]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") close();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [close]);

  const handleCreate = async () => {
    const text = body.trim();
    if (!text || busy || recipients.length === 0) return;
    setBusy(true);
    setError(null);
    try {
      const res = await api.composeSourceInboxDrafts({
        contactIds: recipients.map((profile) => profile.contactIds![0]),
        channel,
        body: text,
        subject: channel === "email" && subject.trim() ? subject.trim() : undefined,
      });
      setResult({ created: res.created, skipped: res.skipped ?? [] });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not create the drafts.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div
      className="crm-tagpicker-backdrop"
      onMouseDown={(event) => { if (event.target === event.currentTarget) close(); }}
    >
      <div className="crm-tagpicker crm-add-lead-modal" role="dialog" aria-modal="true" aria-label={title}>
        <div className="crm-tagpicker-head">
          <h3>{title}</h3>
          <button type="button" aria-label={`Close ${title.toLowerCase()} form`} disabled={busy} onClick={close}>×</button>
        </div>
        <p className="crm-tagpicker-sub">
          <strong className="mono">{recipients.length}</strong> recipient{recipients.length === 1 ? "" : "s"} selected
          {missingContact > 0
            ? ` · ${missingContact} without a linked contact record will be skipped`
            : ""}.
        </p>
        <p className="crm-tagpicker-sub">
          Creates a draft per lead in the approval queue — nothing sends until each is approved.
        </p>
        {recipients.length === 0 && (
          <div className="crm-contact-error" role="alert">
            None of the selected leads have a linked contact record, so no drafts can be created.
          </div>
        )}
        {error && <div className="crm-contact-error" role="alert">{error}</div>}
        {result === null ? (
          <>
            {channel === "email" && (
              <label className="crm-criteria-field">
                <span>Subject</span>
                <input
                  type="text"
                  value={subject}
                  placeholder="e.g. Quick market update"
                  onChange={(event) => setSubject(event.target.value)}
                />
              </label>
            )}
            <label className="crm-criteria-field">
              <span>Message</span>
              <textarea
                value={body}
                rows={5}
                placeholder={channel === "sms" ? "Text to draft for each selected lead…" : "Email to draft for each selected lead…"}
                onChange={(event) => setBody(event.target.value)}
              />
            </label>
            <div className="crm-tagpicker-foot">
              <button
                type="button"
                disabled={busy || !body.trim() || recipients.length === 0}
                onClick={() => void handleCreate()}
              >
                {busy
                  ? "Creating drafts…"
                  : `Create ${recipients.length} draft${recipients.length === 1 ? "" : "s"}`}
              </button>
            </div>
          </>
        ) : (
          <>
            <p className="crm-tagpicker-sub" role="status">
              <strong>{result.created} draft{result.created === 1 ? "" : "s"} created.</strong>{" "}
              Review and approve them in the queue — nothing has been sent.
            </p>
            {result.skipped.length > 0 && (
              <ul className="crm-tagpicker-sub">
                {result.skipped.map((skip) => (
                  <li key={skip.contactId}>
                    {nameByContactId.get(skip.contactId) || skip.contactId} — {skip.reason}
                  </li>
                ))}
              </ul>
            )}
            {missingContact > 0 && (
              <p className="crm-tagpicker-sub">
                {missingContact} selected lead{missingContact === 1 ? " was" : "s were"} not included
                (no linked contact record).
              </p>
            )}
            <div className="crm-tagpicker-foot">
              <button type="button" onClick={close}>Done</button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
