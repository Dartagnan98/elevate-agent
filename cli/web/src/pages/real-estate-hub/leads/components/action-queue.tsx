import { useMemo, useState } from "react";

import type {
  LeadsDraft,
  LeadsDraftAction,
  LeadsHotEntry,
  LeadsPipeline,
  LeadsSkippedEntry,
} from "../leads-data";
import { matchesLeadsSourceFilter } from "./action-queue-helpers";
import { DraftRow } from "./draft-row";

type QueueTab = "approve" | "hot" | "followups" | "skipped";

export function ActionQueue({
  drafts, pipeline, sourceFilter, onDraftAction, onDraftActionComplete, onEditTemplate, onOpenHotLead, canOpenHotLead,
}: {
  drafts: LeadsDraft[];
  pipeline: LeadsPipeline;
  sourceFilter: string;
  onDraftAction?: (action: LeadsDraftAction, draft: LeadsDraft, scheduledAt?: string) => void | Promise<void>;
  onDraftActionComplete?: (action: LeadsDraftAction) => void | Promise<void>;
  onEditTemplate?: () => void;
  onOpenHotLead?: (entry: LeadsHotEntry) => void;
  canOpenHotLead?: (entry: LeadsHotEntry) => boolean;
}) {
  const [tab, setTab] = useState<QueueTab>("approve");
  const [page, setPage] = useState(0);
  const [showAll, setShowAll] = useState(false);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [busy, setBusy] = useState<Set<string>>(() => new Set());
  const [actionError, setActionError] = useState<string | null>(null);
  const PAGE = 5;

  const handleDraftAction = async (
    action: LeadsDraftAction,
    draft: LeadsDraft,
    options: { notifyComplete?: boolean; scheduledAt?: string } = {},
  ) => {
    if (!onDraftAction) return;
    const notifyComplete = options.notifyComplete ?? true;
    setActionError(null);
    setBusy((b) => { const n = new Set(b); n.add(draft.id); return n; });
    try {
      await onDraftAction(action, draft, options.scheduledAt);
      if (notifyComplete) await onDraftActionComplete?.(action);
    } catch (err) {
      setActionError(err instanceof Error ? err.message : `Could not ${action} draft.`);
    } finally {
      setBusy((b) => { const n = new Set(b); n.delete(draft.id); return n; });
    }
  };

  const filteredDrafts = useMemo(() => {
    return drafts.filter((draft) => matchesLeadsSourceFilter(draft, sourceFilter));
  }, [drafts, sourceFilter]);

  const tabs: Array<{ id: QueueTab; label: string; count: number; urgent: boolean }> = [
    { id: "approve", label: "Approve", count: filteredDrafts.length, urgent: filteredDrafts.length > 0 },
    { id: "hot", label: "Hot leads", count: pipeline.hot.length, urgent: false },
    { id: "followups", label: "Follow-ups", count: pipeline.followups.length, urgent: false },
    { id: "skipped", label: "Skipped", count: pipeline.skipped.length, urgent: false },
  ];

  const activeList: Array<LeadsDraft | LeadsHotEntry | LeadsSkippedEntry> =
    tab === "approve" ? filteredDrafts :
    tab === "hot" ? pipeline.hot :
    tab === "followups" ? pipeline.followups :
    tab === "skipped" ? pipeline.skipped : [];

  const totalPages = Math.max(1, Math.ceil(activeList.length / PAGE));
  const safePage = Math.min(page, totalPages - 1);
  const visible = showAll ? activeList : activeList.slice(safePage * PAGE, safePage * PAGE + PAGE);
  const rangeStart = activeList.length === 0 ? 0 : safePage * PAGE + 1;
  const rangeEnd = Math.min(activeList.length, safePage * PAGE + PAGE);

  return (
    <section className="ab-card lb-queue">
      <header className="lb-queue-head">
        <div className="lb-queue-tabs">
          {tabs.map(t => (
            <button
              key={t.id}
              type="button"
              className={"lb-queue-tab" + (tab === t.id ? " active" : "")}
              onClick={() => { setTab(t.id); setPage(0); setExpanded(null); }}
            >
              {t.urgent && t.count > 0 && <span className="lb-queue-pulse"></span>}
              <span>{t.label}</span>
              <span className="lb-queue-tab-count mono">{t.count}</span>
            </button>
          ))}
        </div>

        {tab === "approve" && filteredDrafts.length > 0 && (
          <div className="lb-queue-actions">
            <span className="lb-replies-hint">Review each recipient separately. Nothing sends until that draft is approved.</span>
          </div>
        )}
      </header>

      {actionError && (
        <div className="lb-replies-empty" style={{ color: "var(--accent-warn, #e0a44c)" }}>{actionError}</div>
      )}

      <div className="lb-queue-list">
        {tab === "approve" && (
          visible.length === 0
            ? <div className="lb-replies-empty">No drafts are waiting for approval.</div>
            : (visible as LeadsDraft[]).map(d => (
                <DraftRow
                  key={d.id}
                  draft={d}
                  selected={false}
                  expanded={expanded === d.id}
                  onExpand={() => setExpanded(e => e === d.id ? null : d.id)}
                  onAction={onDraftAction ? (a, d2, scheduledAt) => handleDraftAction(a, d2, { scheduledAt }) : undefined}
                  busy={busy.has(d.id)}
                  onEditTemplate={onEditTemplate}
                  hideSelection
                />
              ))
        )}
        {(tab === "hot" || tab === "followups") && (
          visible.length === 0
            ? (
                <div className="lb-replies-empty">
                  {tab === "hot" ? "No hot leads right now." : "No follow-ups queued."}
                </div>
              )
            : (visible as LeadsHotEntry[]).map(p => {
                const canOpen = Boolean(onOpenHotLead && (!canOpenHotLead || canOpenHotLead(p)));
                return (
                <div key={p.id} className="lb-q-row">
                  <span className={tab === "hot" ? "lb-heat-dot" : "lb-q-mute-dot"}></span>
                  <div className="lb-q-body">
                    <div className="lb-q-name">{p.name}</div>
                    <div className="lb-q-meta">{p.signal} · {p.age}</div>
                  </div>
                  <button
                    type="button"
                    className="lb-btn ghost sm"
                    disabled={!canOpen}
                    title={!canOpen
                      ? "This queue item is not linked to a stable source thread, so Elevate will not open or mutate a guessed contact."
                      : "Open the linked source thread"}
                    onClick={() => onOpenHotLead?.(p)}
                  >
                    {canOpen ? "Open thread" : "Thread unavailable"}
                  </button>
                </div>
                );
              })
        )}
        {tab === "skipped" && (
          visible.length === 0
            ? <div className="lb-replies-empty">Nothing skipped recently.</div>
            : (visible as LeadsSkippedEntry[]).map(p => (
                <div key={p.id} className="lb-q-row">
                  <span className="lb-q-mute-dot"></span>
                  <div className="lb-q-body">
                    <div className="lb-q-name">{p.name}</div>
                    <div className="lb-q-meta">{p.reason}</div>
                  </div>
                  <button
                    type="button"
                    className="lb-btn ghost sm"
                    disabled={busy.has(p.id) || !onDraftAction || !p.sourceId || !p.taskId}
                    onClick={() => void handleDraftAction("restore", {
                      id: p.id,
                      name: p.name,
                      source: "",
                      channel: "",
                      age: "",
                      body: "",
                      heat: "warm",
                      sourceId: p.sourceId,
                      taskId: p.taskId,
                    })}
                  >
                    {busy.has(p.id) ? "…" : "Undo"}
                  </button>
                </div>
              ))
        )}
      </div>

      {activeList.length > PAGE && (
        <footer className="ab-inbox-foot">
          <span className="ab-inbox-range mono">
            {showAll ? `Showing all ${activeList.length}` : `${rangeStart}–${rangeEnd} of ${activeList.length}`}
          </span>
          <div className="ab-inbox-pager">
            {!showAll && (
              <>
                <button
                  type="button"
                  className="ab-inbox-page-btn"
                  onClick={() => setPage(p => Math.max(0, p - 1))}
                  disabled={safePage === 0}
                  aria-label="Previous"
                >‹</button>
                <span className="ab-inbox-page-num mono">{safePage + 1} / {totalPages}</span>
                <button
                  type="button"
                  className="ab-inbox-page-btn"
                  onClick={() => setPage(p => Math.min(totalPages - 1, p + 1))}
                  disabled={safePage === totalPages - 1}
                  aria-label="Next"
                >›</button>
              </>
            )}
            <button
              type="button"
              className="ab-inbox-page-toggle"
              onClick={() => { setShowAll(s => !s); setPage(0); }}
            >
              {showAll ? "Paginate" : "Show all"}
            </button>
          </div>
        </footer>
      )}
    </section>
  );
}
