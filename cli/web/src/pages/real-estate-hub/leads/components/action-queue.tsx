import { useEffect, useMemo, useState } from "react";

import type {
  LeadsDraft,
  LeadsDraftAction,
  LeadsHotEntry,
  LeadsPipeline,
  LeadsSkippedEntry,
} from "../leads-data";

export function matchesLeadsSourceFilter(
  item: { source?: string; sourceId?: string },
  sourceFilter: string,
): boolean {
  if (!sourceFilter || sourceFilter === "all") return true;
  if (item.sourceId === sourceFilter) return true;
  const source = (item.source || "").toLowerCase();
  if (sourceFilter === "lofty") return source === "lofty crm";
  if (sourceFilter === "composio-insta") return source.includes("composio") || source.includes("instagram");
  return false;
}

export function nextDraftQueueSelection(
  current: ReadonlySet<string>,
  drafts: Array<Pick<LeadsDraft, "id">>,
): Set<string> {
  const ids = drafts.map((draft) => draft.id).filter(Boolean);
  const allSelected = ids.length > 0 && ids.every((id) => current.has(id));
  const next = new Set(current);
  for (const id of ids) {
    if (allSelected) next.delete(id);
    else next.add(id);
  }
  return next;
}

function DraftRow({
  draft, selected, expanded, onToggle, onExpand, onAction, busy, onEditTemplate,
}: {
  draft: LeadsDraft;
  selected: boolean;
  expanded: boolean;
  onToggle: () => void;
  onExpand: () => void;
  onAction?: (action: LeadsDraftAction, draft: LeadsDraft) => void;
  busy?: boolean;
  onEditTemplate?: () => void;
}) {
  const [editText, setEditText] = useState(draft.body);
  useEffect(() => { setEditText(draft.body); }, [draft.id, draft.body]);
  const dirty = editText.trim() !== draft.body.trim();
  // Always act on the CURRENT edited text — approving with the original body was
  // dropping every edit. Saving persists the edit (action "edit") without sending.
  const editedDraft = { ...draft, body: editText };
  return (
    <div className={"lb-draft" + (selected ? " selected" : "") + (expanded ? " expanded" : "")}>
      <button type="button" className="lb-draft-check" onClick={onToggle} aria-label="Select draft">
        <span className={"lb-checkbox" + (selected ? " checked" : "")}>
          {selected && <span className="lb-check">✓</span>}
        </span>
      </button>
      <div className="lb-draft-body">
        <button type="button" className="lb-draft-summary" onClick={onExpand}>
          <div className="lb-draft-head">
            <span className="lb-draft-name">{draft.name}</span>
            <span className="lb-draft-meta mono">{draft.source} · {draft.channel}</span>
            {draft.heat === "hot" && <span className="lb-heat">Hot</span>}
            <span className="lb-draft-age">{draft.age} ago</span>
          </div>
          {!expanded && <p className="lb-draft-text">{draft.body}</p>}
        </button>
        {expanded ? (
          <div className="lb-draft-expand">
            <div className="lb-draft-recipient mono">To · {draft.name} · {draft.source}</div>
            <textarea
              className="lb-draft-edit"
              value={editText}
              onChange={(e) => setEditText(e.target.value)}
              rows={Math.max(3, Math.ceil(editText.length / 70))}
              onClick={(e) => e.stopPropagation()}
              onBlur={(e) => { e.stopPropagation(); if (dirty && onAction) onAction("edit", editedDraft); }}
            />
            <div className="lb-draft-expand-foot">
              <span className="lb-draft-template-link">
                Generated from <strong>Warm intro</strong> template · <button type="button" className="lb-link" onClick={(e) => { e.stopPropagation(); onEditTemplate?.(); }}>edit template</button>
              </span>
              {dirty && (
                <button
                  type="button"
                  className="lb-btn ghost sm lb-draft-save"
                  disabled={busy || !onAction}
                  onClick={(e) => { e.stopPropagation(); onAction?.("edit", editedDraft); }}
                >
                  {busy ? "…" : "Save"}
                </button>
              )}
            </div>
          </div>
        ) : null}
      </div>
      <div className="lb-draft-actions">
        <button
          type="button"
          className="lb-btn ghost sm"
          disabled={busy || !onAction}
          onClick={(e) => { e.stopPropagation(); onAction?.("skip", draft); }}
        >
          {busy ? "…" : "Skip"}
        </button>
        <button
          type="button"
          className="lb-btn primary sm"
          disabled={busy || !onAction}
          onClick={(e) => { e.stopPropagation(); onAction?.("approve", editedDraft); }}
        >
          {busy ? "…" : "Approve"}
        </button>
      </div>
    </div>
  );
}

type QueueTab = "approve" | "hot" | "followups" | "skipped";

export function ActionQueue({
  drafts, pipeline, sourceFilter, onDraftAction, onEditTemplate, onOpenHotLead,
}: {
  drafts: LeadsDraft[];
  pipeline: LeadsPipeline;
  sourceFilter: string;
  onDraftAction?: (action: LeadsDraftAction, draft: LeadsDraft) => void | Promise<void>;
  onEditTemplate?: () => void;
  onOpenHotLead?: (entry: LeadsHotEntry) => void;
}) {
  const [tab, setTab] = useState<QueueTab>("approve");
  const [page, setPage] = useState(0);
  const [showAll, setShowAll] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(() => new Set());
  const [expanded, setExpanded] = useState<string | null>(null);
  const [busy, setBusy] = useState<Set<string>>(() => new Set());
  const [actionError, setActionError] = useState<string | null>(null);
  const PAGE = 5;

  const handleDraftAction = async (action: LeadsDraftAction, draft: LeadsDraft) => {
    if (!onDraftAction) return;
    setActionError(null);
    setBusy((b) => { const n = new Set(b); n.add(draft.id); return n; });
    try {
      await onDraftAction(action, draft);
    } catch (err) {
      setActionError(err instanceof Error ? err.message : `Could not ${action} draft.`);
    } finally {
      setBusy((b) => { const n = new Set(b); n.delete(draft.id); return n; });
    }
  };

  const handleBulkAction = async (action: LeadsDraftAction) => {
    if (!onDraftAction) return;
    const targets = filteredDrafts.filter((d) => selected.has(d.id));
    setSelected(new Set());
    for (const draft of targets) {
      await handleDraftAction(action, draft);
    }
  };

  useEffect(() => { setPage(0); setSelected(new Set()); setExpanded(null); }, [tab, sourceFilter]);

  const filteredDrafts = useMemo(() => {
    return drafts.filter((draft) => matchesLeadsSourceFilter(draft, sourceFilter));
  }, [drafts, sourceFilter]);

  useEffect(() => {
    setSelected((prev) => {
      if (prev.size === 0) return prev;
      const allowed = new Set(filteredDrafts.map((draft) => draft.id));
      let changed = false;
      const next = new Set<string>();
      for (const id of prev) {
        if (allowed.has(id)) next.add(id);
        else changed = true;
      }
      return changed ? next : prev;
    });
  }, [filteredDrafts]);

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

  function toggle(id: string) {
    setSelected(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }
  function toggleAllDrafts() {
    setSelected(prev => nextDraftQueueSelection(prev, filteredDrafts));
  }

  return (
    <section className="ab-card lb-queue">
      <header className="lb-queue-head">
        <div className="lb-queue-tabs">
          {tabs.map(t => (
            <button
              key={t.id}
              type="button"
              className={"lb-queue-tab" + (tab === t.id ? " active" : "")}
              onClick={() => setTab(t.id)}
            >
              {t.urgent && t.count > 0 && <span className="lb-queue-pulse"></span>}
              <span>{t.label}</span>
              <span className="lb-queue-tab-count mono">{t.count}</span>
            </button>
          ))}
        </div>

        {tab === "approve" && filteredDrafts.length > 0 && (
          <div className="lb-queue-actions">
            {selected.size > 0 ? (
              <>
                <span className="lb-replies-selected mono">{selected.size} selected</span>
                <button type="button" className="lb-btn ghost sm" onClick={() => setSelected(new Set())}>Clear</button>
                <button type="button" className="lb-btn ghost sm" disabled={!onDraftAction} onClick={() => void handleBulkAction("skip")}>Skip</button>
                <button type="button" className="lb-btn primary sm" disabled={!onDraftAction} onClick={() => void handleBulkAction("approve")}>Approve {selected.size}</button>
              </>
            ) : (
              <>
                <button
                  type="button"
                  className="lb-replies-selectall"
                  onClick={toggleAllDrafts}
                  aria-label={`Select all ${filteredDrafts.length} drafts`}
                >
                  <span className="lb-checkbox" aria-hidden="true"></span>
                  <span>Select all {filteredDrafts.length}</span>
                </button>
                <span className="lb-replies-hint">Nothing sends until you click Approve.</span>
              </>
            )}
          </div>
        )}
      </header>

      {actionError && (
        <div className="lb-replies-empty" style={{ color: "var(--accent-warn, #e0a44c)" }}>{actionError}</div>
      )}

      <div className="lb-queue-list">
        {tab === "approve" && (
          visible.length === 0
            ? <div className="lb-replies-empty">Inbox zero on drafts. Next outreach run lands in ~1h.</div>
            : (visible as LeadsDraft[]).map(d => (
                <DraftRow
                  key={d.id}
                  draft={d}
                  selected={selected.has(d.id)}
                  expanded={expanded === d.id}
                  onToggle={() => toggle(d.id)}
                  onExpand={() => setExpanded(e => e === d.id ? null : d.id)}
                  onAction={onDraftAction ? handleDraftAction : undefined}
                  busy={busy.has(d.id)}
                  onEditTemplate={onEditTemplate}
                />
              ))
        )}
        {(tab === "hot" || tab === "followups") && (
          visible.length === 0
            ? (
                <div className="lb-replies-empty">
                  {tab === "hot" ? "No hot leads right now." : "No follow-ups queued."}
                  {tab === "followups" && (
                    <>
                      <br />
                      <span className="lb-replies-hint-2">Threads that go cold 7+ days re-enter this queue automatically.</span>
                    </>
                  )}
                </div>
              )
            : (visible as LeadsHotEntry[]).map(p => (
                <div key={p.id} className="lb-q-row">
                  <span className={tab === "hot" ? "lb-heat-dot" : "lb-q-mute-dot"}></span>
                  <div className="lb-q-body">
                    <div className="lb-q-name">{p.name}</div>
                    <div className="lb-q-meta">{p.signal} · {p.age}</div>
                  </div>
                  <button type="button" className="lb-btn ghost sm" disabled={!onOpenHotLead} onClick={() => onOpenHotLead?.(p)}>Draft reply</button>
                  <button type="button" className="lb-btn ghost sm" disabled={!onOpenHotLead} onClick={() => onOpenHotLead?.(p)}>Open thread</button>
                </div>
              ))
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
