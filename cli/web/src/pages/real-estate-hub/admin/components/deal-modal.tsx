
import React, { useState, useEffect, useCallback } from "react";
import { createPortal } from "react-dom";
// Self-contained styling: the modal is portaled to <body> and opened from
// multiple tabs (Admin + Today). Import the styles here so they always load
// with the modal, even when AdminDesignShell (which also imports this) never
// mounts — e.g. a fresh load straight into Today.
import "../admin.css";
import {
  Home,
  Clock,
  Database,
  FileText,
  Users,
  Paperclip,
  Chevron,
} from "../icons";
import {
  ADMIN_PIPELINE,
  ADMIN_BUYER_PIPELINE,
  ADMIN_PHASE_DETAILS,
  ADMIN_BUYER_PHASE_DETAILS,
  ADMIN_CONDITION_ENUMS,
  ADMIN_CONDITION_TOGGLES,
} from "../admin-data";
import { api } from "@/lib/api";
import type {
  DealContext,
  AdminDealToggleValue,
  DealAttachmentCreateRequest,
  DealContactCreateRequest,
} from "@/lib/api-types";

// A deal id is persisted (backed by a real saved file) when it's a 32-char hex.
// Seed/demo cards (d1, b2, local-...) are not persisted, so their action buttons
// stay inert rather than firing 404s at the backend.
function isPersistedDealId(id: string): boolean {
  return /^[a-f0-9]{32}$/i.test(id);
}

const MONTHS_ABBR = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

function fmtMoney(value: number): string {
  return "$" + Math.round(value).toLocaleString();
}

function fmtShortDate(value: string | null | undefined): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(value || "");
  if (!match) return value || "";
  return MONTHS_ABBR[parseInt(match[2], 10) - 1] + " " + parseInt(match[3], 10);
}

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface Deal {
  id: string;
  phase: string;
  addr: string;
  line2: string;
  badge: string;
  progress?: string;
  next: string;
  price?: string;
  mls?: string;
  blocked?: boolean;
  primary?: boolean;
  owner?: string;
  ownerInitial?: string;
  daysInStage?: string;
  side?: string;
}

interface DealDetailModalProps {
  deal: Deal;
  onClose: () => void;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function DealDetailModal({ deal, onClose }: DealDetailModalProps) {
  const [openPhases, setOpenPhases] = useState<Set<string>>(
    () => new Set([deal.phase || "pre-cma"])
  );

  // Real per-deal context from the backend (province guide, per-stage province
  // documents, conditional docs). Falls back to seed data when a deal has no
  // saved file yet (demo/placeholder cards), so this never regresses.
  const [ctx, setCtx] = useState<DealContext | null>(null);
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [actionMode, setActionMode] = useState<"dates" | "doc" | "contact" | null>(null);
  const persisted = isPersistedDealId(deal.id);

  useEffect(() => {
    if (!deal.id) return;
    let active = true;
    api
      .getDealContext(deal.id)
      .then((c) => {
        if (active) setCtx(c);
      })
      .catch(() => {
        /* no saved deal file — keep seed fallback */
      });
    return () => {
      active = false;
    };
  }, [deal.id]);

  // Refetch context after a successful mutation so the modal reflects new state.
  const refetch = useCallback(async () => {
    if (!deal.id) return;
    const c = await api.getDealContext(deal.id);
    setCtx(c);
  }, [deal.id]);

  // Wrap a mutation: gate on a persisted deal, track busy + surface errors,
  // then refetch so the panel updates in place.
  const runAction = useCallback(
    async (fn: () => Promise<unknown>) => {
      if (!persisted || busy) return;
      setBusy(true);
      setActionError(null);
      try {
        await fn();
        await refetch();
      } catch (err) {
        setActionError(err instanceof Error ? err.message : "Action failed");
      } finally {
        setBusy(false);
      }
    },
    [persisted, busy, refetch],
  );

  const handleAdvance = useCallback(
    (force = false) => runAction(() => api.advanceDeal(deal.id, force)),
    [runAction, deal.id],
  );

  const handleConditionChange = useCallback(
    (field: string, value: AdminDealToggleValue) =>
      runAction(() => api.setAdminDealToggle(deal.id, field, value)),
    [runAction, deal.id],
  );

  // Per-stage checklist items persist as free-form toggles in the deal's
  // extra_toggles bag (returned by getDealContext as `ctx.checklist`). Each
  // item gets a stable key derived from its phase id + label slug.
  const handleChecklistToggle = useCallback(
    (key: string, next: boolean) =>
      runAction(() => api.setAdminDealToggle(deal.id, key, next)),
    [runAction, deal.id],
  );

  // Current condition values come from the backend context (keyed by API field).
  const conditions = ctx?.conditions ?? {};
  // Current checklist completion bag (free-form toggles), keyed per item.
  const checklistState = ctx?.checklist ?? {};
  const contextDeal = ctx?.deal ?? null;
  const showMoneyStrip = Boolean(
    contextDeal &&
      (contextDeal.listPrice != null ||
        contextDeal.offerPrice != null ||
        contextDeal.depositAmount != null ||
        contextDeal.commissionPct != null ||
        contextDeal.completionDate),
  );

  // Inline add-form drafts (ported from the legacy AdminDealContextSection).
  const [fieldDraft, setFieldDraft] = useState({
    listingDate: "",
    offerDate: "",
    subjectRemovalDate: "",
    depositDueDate: "",
    completionDate: "",
    possessionDate: "",
    mlsNumber: "",
    listPrice: "",
    offerPrice: "",
  });
  const [docDraft, setDocDraft] = useState({ kind: "cma_report", filePath: "", summary: "" });
  const [contactDraft, setContactDraft] = useState({ role: "lawyer", contactId: "", notes: "" });

  const submitDates = (e: React.FormEvent) => {
    e.preventDefault();
    const fields = Object.fromEntries(
      Object.entries(fieldDraft).filter(([, value]) => value.trim()),
    );
    if (Object.keys(fields).length === 0) return;
    void runAction(() => api.updateDealFields(deal.id, fields)).then(() => {
      setFieldDraft({
        listingDate: "", offerDate: "", subjectRemovalDate: "", depositDueDate: "",
        completionDate: "", possessionDate: "", mlsNumber: "", listPrice: "", offerPrice: "",
      });
      setActionMode(null);
    });
  };

  const submitDoc = (e: React.FormEvent) => {
    e.preventDefault();
    const body: DealAttachmentCreateRequest = {
      kind: docDraft.kind,
      filePath: docDraft.filePath,
      summary: docDraft.summary || null,
    };
    void runAction(() => api.addDealAttachment(deal.id, body)).then(() => {
      setDocDraft({ kind: "cma_report", filePath: "", summary: "" });
      setActionMode(null);
    });
  };

  const submitContact = (e: React.FormEvent) => {
    e.preventDefault();
    const body: DealContactCreateRequest = {
      role: contactDraft.role,
      contactId: contactDraft.contactId,
      notes: contactDraft.notes || null,
    };
    void runAction(() => api.addDealContact(deal.id, body)).then(() => {
      setContactDraft({ role: "lawyer", contactId: "", notes: "" });
      setActionMode(null);
    });
  };

  const guide = ctx?.provinceGuide ?? null;
  const conditionalDocs = ctx?.conditionalDocs ?? [];
  const provinceLabel =
    guide?.provinceLabel || (ctx?.deal?.province ?? "").toUpperCase() || "VANCOUVER";
  // Real province documents for a stage label like "S8" -> stageDocuments[8].
  const realStageDocs = (stageLabel: string) => {
    const n = Number((stageLabel || "").replace(/[^0-9]/g, ""));
    return ctx?.stageDocuments?.stages?.[String(n)] ?? [];
  };
  // Stable persisted key for a per-phase checklist item.
  const checklistKey = (phaseId: string, label: string) =>
    "checklist:" +
    phaseId +
    ":" +
    label.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "");
  const isChecked = (phaseId: string, label: string) =>
    checklistState[checklistKey(phaseId, label)] === true;

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  const isBuyer      = deal.side === "buyer";
  const pipeline      = isBuyer ? ADMIN_BUYER_PIPELINE      : ADMIN_PIPELINE;
  const phaseDetails  = isBuyer ? ADMIN_BUYER_PHASE_DETAILS  : ADMIN_PHASE_DETAILS;
  const sideCrumb     = isBuyer ? "BUYER ADMIN ADMIN"        : "LISTING ADMIN ADMIN";

  const currentPhase = pipeline.find((p) => p.id === deal.phase) || pipeline[0];
  const currentIdx   = pipeline.indexOf(currentPhase);
  const nextPhase    = pipeline[currentIdx + 1];
  const phaseDetail  = phaseDetails[currentPhase.id] || { checklist: [], documents: [] };

  const togglePhase = (id: string) =>
    setOpenPhases((s) => {
      const n = new Set(s);
      if (n.has(id)) n.delete(id);
      else n.add(id);
      return n;
    });

  // Alias icons to match original variable names
  const Calendar  = Clock;
  const FileTxt   = FileText;
  const ChevDown  = Chevron;

  return createPortal(
    <div className="ab-modal-backdrop" onClick={onClose}>
      <div
        className="ab-modal"
        onClick={(e: React.MouseEvent) => e.stopPropagation()}
        role="dialog"
      >
        <button className="ab-modal-close" onClick={onClose} aria-label="Close">
          <span className="x">&times;</span>
        </button>

        {/* Header (flush, no card) */}
        <header className="abm-head">
          <div className="abm-crumbs mono">
            <span>{sideCrumb}</span>
            <span className="sep">&middot;</span>
            <span className="stage">{currentPhase.stage}</span>
            <span className="sep">&middot;</span>
            <span className="stage">{currentPhase.name.toUpperCase()}</span>
          </div>
          <h2 className="abm-title">{deal.addr}</h2>
          <div className="abm-meta">
            <span className="abm-meta-row">
              <Home />
              <span>{deal.line2}</span>
            </span>
            <span className="abm-meta-row">
              <Calendar />
              <span>{currentPhase.name}</span>
              <span className="dim">&middot;</span>
              <span className="dim">&mdash;</span>
            </span>
          </div>
          {contextDeal && showMoneyStrip && (
            <div className="abm-money" aria-label="Deal money summary">
              {contextDeal.listPrice != null && (
                <div className="abm-money-cell">
                  <span className="k mono">List</span>
                  <span className="v">{fmtMoney(contextDeal.listPrice)}</span>
                </div>
              )}
              {contextDeal.offerPrice != null && (
                <div className="abm-money-cell">
                  <span className="k mono">Accepted offer</span>
                  <span className="v o">{fmtMoney(contextDeal.offerPrice)}</span>
                  {contextDeal.listPrice ? (
                    <span className="n">{Math.round((contextDeal.offerPrice / contextDeal.listPrice) * 100)}% of ask</span>
                  ) : null}
                </div>
              )}
              {contextDeal.depositAmount != null && (
                <div className="abm-money-cell">
                  <span className="k mono">Deposit</span>
                  <span className="v b">{fmtMoney(contextDeal.depositAmount)}</span>
                </div>
              )}
              {contextDeal.commissionPct != null && (
                <div className="abm-money-cell">
                  <span className="k mono">Commission</span>
                  <span className="v">{contextDeal.commissionPct}%</span>
                </div>
              )}
              {contextDeal.completionDate && (
                <div className="abm-money-cell">
                  <span className="k mono">Completion</span>
                  <span className="v">{fmtShortDate(contextDeal.completionDate)}</span>
                  {contextDeal.possessionDate ? (
                    <span className="n">poss. {fmtShortDate(contextDeal.possessionDate)}</span>
                  ) : null}
                </div>
              )}
            </div>
          )}
        </header>

        <div className="abm-actionbar" aria-label="Deal actions">
          <button
            className="abm-btn primary"
            type="button"
            disabled={!persisted || busy}
            onClick={() => void handleAdvance(false)}
          >
            {busy ? "Working..." : "Advance phase"}
          </button>
          <button
            className="abm-btn ghost"
            type="button"
            disabled={!persisted || busy}
            onClick={() => void handleAdvance(true)}
          >
            Force advance
          </button>
          {actionError && (
            <span className="abm-actionbar-error" role="status">
              {actionError}
            </span>
          )}
        </div>

        <div className="ab-modal-scroll">
          <div className="abm-cols">
            {/* ─── Left column: Transaction file ─── */}
            <div className="abm-col abm-col-left">
              <section className="abm-card">
                <header className="abm-card-head">
                  <div className="abm-card-title">
                    <Database />
                    <span>Transaction file</span>
                  </div>
                  <div className="abm-card-pills">
                    <span className="abm-pill mono">{provinceLabel}</span>
                    <span className="abm-pill mono">{(ctx?.attachments?.length ?? 0)} DOCS</span>
                    <span className="abm-pill mono">{(ctx?.priorRuns?.length ?? 0)} RUNS</span>
                  </div>
                </header>

                {/* Phase gate */}
                <div className="abm-section">
                  <div className="abm-section-row">
                    <span className="abm-section-label mono">PHASE GATE</span>
                    {deal.blocked && <span className="abm-tag warn">BLOCKED</span>}
                  </div>
                  <div className="abm-phase-jump">
                    {currentPhase.name} <span className="dim">&rarr;</span>{" "}
                    {nextPhase ? nextPhase.name : "Closed"}
                  </div>
                  <div className="abm-kv-row">
                    <div>
                      <span className="dim">Checklist:</span>{" "}
                      <strong>0/{phaseDetail.checklist.length}</strong>
                    </div>
                    <div>
                      <span className="dim">Package:</span>{" "}
                      <strong>generic.real-estate</strong>
                    </div>
                  </div>
                  <ul className="abm-missing">
                    {phaseDetail.checklist.slice(0, 3).map((c, i) => (
                      <li key={i}>
                        <span className="dim">Missing checklist:</span> <span>{c}</span>
                      </li>
                    ))}
                    <li>
                      <span className="dim">Missing field:</span>{" "}
                      <span>Client 1 name</span>
                    </li>
                    <li>
                      <span className="dim">Missing field:</span>{" "}
                      <span>Client 1 email</span>
                    </li>
                    <li>
                      <span className="dim">Missing field:</span>{" "}
                      <span>Lead source</span>
                    </li>
                    <li>
                      <span className="dim">Missing field:</span>{" "}
                      <span>CMA date requested</span>
                    </li>
                  </ul>
                </div>

                {/* Background automations */}
                <div className="abm-section">
                  <div className="abm-section-row">
                    <span className="abm-section-label mono">BACKGROUND AUTOMATIONS</span>
                    <span className="abm-section-count mono">2</span>
                  </div>
                  <p className="abm-section-desc">
                    Cron skills feed evidence into this deal; phases consume the results.
                  </p>
                  <div className="abm-grid-2">
                    <div className="abm-auto-card">
                      <div className="abm-auto-head">
                        <span className="abm-auto-name">Gmail Doc Router</span>
                        <span className="abm-pill mono">CRON</span>
                      </div>
                      <div className="abm-auto-id mono">GMAIL-DOC-ROUTER</div>
                    </div>
                    <div className="abm-auto-card">
                      <div className="abm-auto-head">
                        <span className="abm-auto-name">Seller Update</span>
                        <span className="abm-pill mono">CRON</span>
                      </div>
                      <div className="abm-auto-id mono">SELLER-UPDATE</div>
                    </div>
                  </div>
                </div>

                {/* Primary contact + Important dates */}
                <div className="abm-grid-2 abm-padded">
                  <div className="abm-mini">
                    <div className="abm-mini-label mono">
                      <Users />
                      <span>PRIMARY CONTACT</span>
                    </div>
                    <div className="abm-mini-value">Not linked</div>
                  </div>
                  <div className="abm-mini">
                    <div className="abm-mini-label mono">
                      <Calendar />
                      <span>IMPORTANT DATES</span>
                    </div>
                    <div className="abm-mini-value">
                      Listing: <strong className="mono">2026-03-12</strong>
                    </div>
                  </div>
                </div>

                {/* File details */}
                <div className="abm-section abm-padded">
                  <div className="abm-section-label mono">FILE DETAILS</div>
                  <div className="abm-kv-row">
                    <div>
                      <span className="dim">List price:</span>{" "}
                      <strong>{deal.price || "$625,000"}</strong>
                    </div>
                    <div>
                      <span className="dim">MLS:</span>{" "}
                      <strong className="mono">{deal.mls || "BETA-161656"}</strong>
                    </div>
                  </div>
                </div>

                {/* Province playbook (real backend data) */}
                {guide && (
                  <div className="abm-section abm-padded">
                    <div className="abm-section-row">
                      <span className="abm-section-label mono">PROVINCE PLAYBOOK</span>
                      <span className="abm-section-count mono">{provinceLabel}</span>
                    </div>
                    <div className="abm-kv-row">
                      <div>
                        <span className="dim">Forms:</span>{" "}
                        <strong>{guide.coverage.forms}</strong>
                      </div>
                      <div>
                        <span className="dim">Guides:</span>{" "}
                        <strong>{guide.coverage.referencePages}</strong>
                      </div>
                      <div>
                        <span className="dim">Checklists:</span>{" "}
                        <strong>{guide.coverage.checklists}</strong>
                      </div>
                    </div>
                    {guide.pages.length > 0 && (
                      <ul className="abm-doc-list">
                        {guide.pages.slice(0, 6).map((pg) => (
                          <li key={pg.slug}>
                            <FileTxt />
                            {pg.sourceUrl ? (
                              <a href={pg.sourceUrl} target="_blank" rel="noopener noreferrer">
                                {pg.title}
                              </a>
                            ) : (
                              <span>{pg.title}</span>
                            )}
                          </li>
                        ))}
                      </ul>
                    )}
                    {conditionalDocs.length > 0 && (
                      <>
                        <div className="abm-section-label mono" style={{ marginTop: 8 }}>
                          CONDITIONAL DOCUMENTS
                        </div>
                        <ul className="abm-doc-list">
                          {conditionalDocs.slice(0, 6).map((d) => (
                            <li key={d.id}>
                              <FileTxt />
                              <strong className="mono">{d.docCode}</strong>
                              <span className="dim">&middot;</span>
                              <span>{d.docName}</span>
                              <span className="abm-tag warn mono">
                                if {d.fieldKey}={d.fieldValue}
                              </span>
                            </li>
                          ))}
                        </ul>
                      </>
                    )}
                  </div>
                )}

                {/* Co-contacts + Documents + Prior runs */}
                <div className="abm-grid-3 abm-padded">
                  <div className="abm-mini">
                    <div className="abm-mini-label mono">
                      <Users />
                      <span>CO-CONTACTS</span>
                    </div>
                    <div className="abm-mini-value">None linked</div>
                  </div>
                  <div className="abm-mini">
                    <div className="abm-mini-label mono">
                      <FileTxt />
                      <span>DOCUMENTS</span>
                    </div>
                    <div className="abm-mini-value">No docs attached</div>
                  </div>
                  <div className="abm-mini">
                    <div className="abm-mini-label mono">
                      <Calendar />
                      <span>PRIOR RUNS</span>
                    </div>
                    <div className="abm-mini-value">[BETA REVIEW] Human appro&hellip;</div>
                    <div className="abm-mini-extra">
                      <span className="abm-tag error mono">CANCELLED</span>
                      <span className="dim">13d ago</span>
                    </div>
                  </div>
                </div>

                {/* Source actions */}
                <div className="abm-source-actions">
                  <span className="abm-section-label mono">SOURCE ACTIONS</span>
                  <div className="abm-source-buttons">
                    <button
                      type="button"
                      className={"abm-btn " + (actionMode === "dates" ? "primary" : "ghost")}
                      disabled={!persisted}
                      onClick={() => setActionMode(actionMode === "dates" ? null : "dates")}
                    >
                      <Calendar />
                      <span>Dates</span>
                    </button>
                    <button
                      type="button"
                      className={"abm-btn " + (actionMode === "doc" ? "primary" : "ghost")}
                      disabled={!persisted}
                      onClick={() => setActionMode(actionMode === "doc" ? null : "doc")}
                    >
                      <Paperclip />
                      <span>Attach</span>
                    </button>
                    <button
                      type="button"
                      className={"abm-btn " + (actionMode === "contact" ? "primary" : "ghost")}
                      disabled={!persisted}
                      onClick={() => setActionMode(actionMode === "contact" ? null : "contact")}
                    >
                      <Users />
                      <span>Co-contact</span>
                    </button>
                  </div>

                  {actionMode === "dates" && (
                    <form className="abm-action-form abm-grid-2" onSubmit={submitDates}>
                      {(["listingDate", "offerDate", "subjectRemovalDate", "depositDueDate", "completionDate", "possessionDate", "mlsNumber", "listPrice", "offerPrice"] as const).map((field) => (
                        <label key={field} className="abm-field-label mono">
                          {field}
                          <input
                            className="abm-input"
                            value={fieldDraft[field]}
                            onChange={(ev) => setFieldDraft((prev) => ({ ...prev, [field]: ev.target.value }))}
                          />
                        </label>
                      ))}
                      <div style={{ gridColumn: "1 / -1" }}>
                        <button className="abm-btn primary" type="submit" disabled={busy}>
                          Update file fields
                        </button>
                      </div>
                    </form>
                  )}

                  {actionMode === "doc" && (
                    <form className="abm-action-form" onSubmit={submitDoc}>
                      <div className="abm-grid-2">
                        <input
                          className="abm-input"
                          value={docDraft.kind}
                          onChange={(ev) => setDocDraft((prev) => ({ ...prev, kind: ev.target.value }))}
                          placeholder="kind, e.g. cma_report"
                        />
                        <input
                          className="abm-input"
                          value={docDraft.filePath}
                          onChange={(ev) => setDocDraft((prev) => ({ ...prev, filePath: ev.target.value }))}
                          placeholder="/path/to/file.pdf"
                        />
                      </div>
                      <input
                        className="abm-input"
                        value={docDraft.summary}
                        onChange={(ev) => setDocDraft((prev) => ({ ...prev, summary: ev.target.value }))}
                        placeholder="summary"
                      />
                      <button
                        className="abm-btn primary"
                        type="submit"
                        disabled={busy || !docDraft.kind.trim() || !docDraft.filePath.trim()}
                      >
                        Attach document
                      </button>
                    </form>
                  )}

                  {actionMode === "contact" && (
                    <form className="abm-action-form" onSubmit={submitContact}>
                      <div className="abm-grid-2">
                        <input
                          className="abm-input"
                          value={contactDraft.role}
                          onChange={(ev) => setContactDraft((prev) => ({ ...prev, role: ev.target.value }))}
                          placeholder="role, e.g. lawyer"
                        />
                        <input
                          className="abm-input"
                          value={contactDraft.contactId}
                          onChange={(ev) => setContactDraft((prev) => ({ ...prev, contactId: ev.target.value }))}
                          placeholder="contact id"
                        />
                      </div>
                      <input
                        className="abm-input"
                        value={contactDraft.notes}
                        onChange={(ev) => setContactDraft((prev) => ({ ...prev, notes: ev.target.value }))}
                        placeholder="notes"
                      />
                      <button
                        className="abm-btn primary"
                        type="submit"
                        disabled={busy || !contactDraft.role.trim() || !contactDraft.contactId.trim()}
                      >
                        Add co-contact
                      </button>
                    </form>
                  )}
                </div>
              </section>
            </div>

            {/* ─── Right column: Phase accordion list ─── */}
            <div className="abm-col abm-col-right">
              {pipeline.map((p) => {
                const detail = phaseDetails[p.id] || {
                  checklist: [] as string[],
                  documents: [] as [string, string][],
                  motion: "",
                  movesOn: "",
                  gate: "",
                };
                const idx     = pipeline.indexOf(p);
                const done    = idx < currentIdx;
                const current = idx === currentIdx;
                const open    = openPhases.has(p.id);
                // Prefer this province's real per-stage documents (from its
                // transaction guide); fall back to seed docs when unavailable.
                const provDocs = realStageDocs(p.stage);
                const docsToShow: [string, string][] = provDocs.length
                  ? provDocs.map((d) => [d.code, d.name] as [string, string])
                  : detail.documents;

                return (
                  <div
                    key={p.id}
                    className={
                      "abm-phase" +
                      (current ? " current" : "") +
                      (done ? " done" : "")
                    }
                  >
                    <button
                      type="button"
                      className="abm-phase-head"
                      onClick={() => togglePhase(p.id)}
                      aria-expanded={open}
                    >
                      <span
                        className="abm-phase-radio"
                        data-state={current ? "current" : done ? "done" : "todo"}
                      />
                      <div className="abm-phase-title-block">
                        <div className="abm-phase-title">
                          <span>{p.name}</span>
                          {current && (
                            <span className="abm-tag current mono">CURRENT</span>
                          )}
                        </div>
                        <div className="abm-phase-sub mono">
                          {p.stage} &middot;{" "}
                          {p.name.toUpperCase().replace(/ \/ /g, " · ")}
                        </div>
                        <div className="abm-phase-trigger">
                          <span className="abm-bullet" />
                          {detail.movesOn}
                        </div>
                      </div>
                      <span className="abm-phase-count mono">
                        {detail.checklist.filter((c) => isChecked(p.id, c)).length}/
                        {detail.checklist.length}
                      </span>
                      <ChevDown
                        className={
                          "abm-phase-chev" + (open ? " open" : "")
                        }
                      />
                    </button>

                    {open && (
                      <div className="abm-phase-body">
                        <div className="abm-phase-motion">
                          <div className="abm-phase-motion-head">
                            <span>{detail.motion.split(" · ")[0]}</span>
                            <span className="sep">&middot;</span>
                            <span className="abm-phase-approval">
                              {detail.motion.split(" · ")[1] || "approval"}
                            </span>
                          </div>
                          <div className="abm-phase-motion-line">
                            Moves on {detail.movesOn}
                          </div>
                          <div className="abm-phase-motion-gate">
                            <span className="abm-shield">&#x26E8;</span> Gate:{" "}
                            {detail.gate}
                          </div>
                        </div>

                        <ul className="abm-checklist">
                          {detail.checklist.map((c, i) => {
                            const checked = isChecked(p.id, c);
                            return (
                              <li key={i}>
                                <button
                                  type="button"
                                  className="abm-checklist-item"
                                  aria-pressed={checked}
                                  disabled={!persisted || busy}
                                  onClick={() =>
                                    void handleChecklistToggle(
                                      checklistKey(p.id, c),
                                      !checked,
                                    )
                                  }
                                >
                                  <span
                                    className={
                                      "abm-check-box" + (checked ? " checked" : "")
                                    }
                                  />
                                  <span>{c}</span>
                                </button>
                              </li>
                            );
                          })}
                        </ul>

                        {docsToShow.length > 0 && (
                          <div className="abm-province">
                            <div className="abm-section-label mono">
                              PROVINCE DOCUMENTS &middot; {docsToShow.length}
                            </div>
                            <ul className="abm-doc-list">
                              {docsToShow.map(([key, name], i) => (
                                <li key={i}>
                                  <FileTxt />
                                  <strong className="mono">{key}</strong>
                                  <span className="dim">&middot;</span>
                                  <span>{name}</span>
                                </li>
                              ))}
                            </ul>
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </div>

          {/* ─── Conditions ─── */}
          <section className="abm-conditions">
            <h3 className="abm-conditions-title">Conditions</h3>
            <div className="abm-conditions-sub mono">ENUMS</div>

            <div className="abm-enums">
              {ADMIN_CONDITION_ENUMS.map((field) => {
                const current = conditions[field.field];
                const value = typeof current === "string" ? current : "";
                const hasCustomValue =
                  value !== "" && !field.options.some((o) => o.value === value);
                return (
                  <div className="abm-enum-row" key={field.id}>
                    <span className="abm-enum-label">{field.label}</span>
                    <select
                      className="abm-enum-select"
                      value={value}
                      disabled={!persisted || busy}
                      onChange={(e) =>
                        void handleConditionChange(field.field, e.currentTarget.value || null)
                      }
                    >
                      <option value="">Not set</option>
                      {hasCustomValue && <option value={value}>{value}</option>}
                      {field.options.map((o) => (
                        <option key={o.value} value={o.value}>
                          {o.label}
                        </option>
                      ))}
                    </select>
                  </div>
                );
              })}
            </div>

            <div className="abm-conditions-sub mono">YES / NO</div>
            <div className="abm-toggles">
              {ADMIN_CONDITION_TOGGLES.map((t) => {
                const current = conditions[t.field];
                const checked = current === true;
                const label = current == null ? "UNSET" : checked ? "YES" : "NO";
                return (
                  <div className="abm-toggle-row" key={t.field}>
                    <button
                      type="button"
                      className="abm-toggle-check"
                      aria-pressed={checked}
                      disabled={!persisted || busy}
                      onClick={() => void handleConditionChange(t.field, !checked)}
                    >
                      <span className={"abm-check-box" + (checked ? " checked" : "")} />
                      <span>{t.label}</span>
                    </button>
                    <span className="abm-toggle-unset mono">{label}</span>
                  </div>
                );
              })}
            </div>
          </section>
        </div>
      </div>
    </div>,
    document.body,
  );
}
