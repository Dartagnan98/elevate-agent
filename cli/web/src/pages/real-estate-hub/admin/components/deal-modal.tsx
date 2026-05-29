
import React, { useState, useEffect } from "react";
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
import type { DealContext } from "@/lib/api-types";

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

  const guide = ctx?.provinceGuide ?? null;
  const conditionalDocs = ctx?.conditionalDocs ?? [];
  const provinceLabel =
    guide?.provinceLabel || (ctx?.deal?.province ?? "").toUpperCase() || "VANCOUVER";
  // Real province documents for a stage label like "S8" -> stageDocuments[8].
  const realStageDocs = (stageLabel: string) => {
    const n = Number((stageLabel || "").replace(/[^0-9]/g, ""));
    return ctx?.stageDocuments?.stages?.[String(n)] ?? [];
  };

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

  return (
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
        </header>

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
                  <div className="abm-actions">
                    <button className="abm-btn primary" type="button">
                      Advance phase
                    </button>
                    <button className="abm-btn ghost" type="button">
                      Force advance
                    </button>
                  </div>
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
                    <button className="abm-btn ghost">
                      <Calendar />
                      <span>Dates</span>
                    </button>
                    <button className="abm-btn ghost">
                      <Paperclip />
                      <span>Attach</span>
                    </button>
                    <button className="abm-btn ghost">
                      <Users />
                      <span>Co-contact</span>
                    </button>
                  </div>
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
                        0/{detail.checklist.length}
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
                          {detail.checklist.map((c, i) => (
                            <li key={i}>
                              <span className="abm-check-box" />
                              {c}
                            </li>
                          ))}
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
              {ADMIN_CONDITION_ENUMS.map((field) => (
                <div className="abm-enum-row" key={field.id}>
                  <span className="abm-enum-label">{field.label}</span>
                  <button className="abm-enum-select" type="button">
                    <span>Not set</span>
                    <ChevDown />
                  </button>
                </div>
              ))}
            </div>

            <div className="abm-conditions-sub mono">YES / NO</div>
            <div className="abm-toggles">
              {ADMIN_CONDITION_TOGGLES.map((t, i) => (
                <div className="abm-toggle-row" key={i}>
                  <label className="abm-toggle-check">
                    <span className="abm-check-box" />
                    <span>{t}</span>
                  </label>
                  <span className="abm-toggle-unset mono">UNSET</span>
                </div>
              ))}
            </div>
          </section>
        </div>
      </div>
    </div>
  );
}
