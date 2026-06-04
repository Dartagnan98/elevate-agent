
import React, { useState, useMemo, useEffect } from "react";
import {
  Plus,
  Refresh,
  Sparkles,
  Search,
  FileText,
  Shield,
  ShieldAlert,
  AlertTriangle,
  Clock,
} from "../icons";
import {
  ADMIN_PIPELINE,
  ADMIN_BUYER_PIPELINE,
  ADMIN_DEALS,
  ADMIN_BUYER_DEALS,
  ADMIN_ACTIONS,
  ADMIN_AUTOMATIONS,
  ADMIN_SHOWINGS,
} from "../admin-data";
import type { BuyerDeal } from "../admin-data";
import type { AdminKpi } from "../compute-admin-kpis";
import type { AdminEvent } from "../compute-admin-events";
import DealDetailModal from "./deal-modal";
import { api } from "@/lib/api";
import type { AdminDealCreateRequest, AdminDealSide } from "@/lib/api-types";

export interface AdminBoardProps {
  deals?: Deal[];
  buyerDeals?: BuyerDeal[];
  kpis?: AdminKpi[];
  events?: AdminEvent[];
  loading?: boolean;
  error?: string | null;
  onRefresh?: () => void;
  onOpenDeal?: (dealId: string) => void;
  onMoveDeal?: (dealId: string, toStage: number) => void;
  onReRunOnboarding?: () => void;
}

/* ─────────────────────────────────────────────────────────────────
   StatusPill
   ───────────────────────────────────────────────────────────────── */

function StatusPill({ kind, children }: { kind: string; children: React.ReactNode }) {
  return <span className={"ab-pill " + kind}>{children}</span>;
}

/* ─────────────────────────────────────────────────────────────────
   CyclingShowings
   ───────────────────────────────────────────────────────────────── */

interface ShowingItem {
  id: string;
  time: string;
  address: string;
}

function CyclingShowings({ items }: { items: ShowingItem[] }) {
  const [idx, setIdx] = useState(0);
  const multiple = items.length > 1;

  useEffect(() => {
    if (!multiple) return;
    const t = setInterval(() => setIdx(i => (i + 1) % items.length), 4500);
    return () => clearInterval(t);
  }, [multiple, items.length]);

  if (!items.length) return null;
  const item = items[idx];

  return (
    <div className="ab-cycler" title={`${items.length} upcoming`}>
      <span className="ab-cycler-icon"><Clock /></span>
      <div className="ab-cycler-text" key={item.id}>
        <span className="ab-cycler-when">{item.time}</span>
        <span className="ab-cycler-sep">&middot;</span>
        <span className="ab-cycler-addr">{item.address}</span>
      </div>
      {multiple && (
        <div className="ab-cycler-dots" aria-hidden>
          {items.slice(0, Math.min(items.length, 5)).map((_, i) => (
            <span key={i} className={"ab-cycler-dot" + (i === idx % Math.min(items.length, 5) ? " active" : "")}></span>
          ))}
        </div>
      )}
    </div>
  );
}

/* ─────────────────────────────────────────────────────────────────
   Sparkline
   ───────────────────────────────────────────────────────────────── */

function Sparkline({ runs }: { runs: string[] }) {
  return (
    <div className="ab-spark" title={`Last ${runs.length} runs`}>
      {runs.map((r, i) => (
        <span key={i} className={"ab-spark-dot " + r}></span>
      ))}
    </div>
  );
}

/* ─────────────────────────────────────────────────────────────────
   KpiTile
   ───────────────────────────────────────────────────────────────── */

interface KpiTileProps {
  label: string;
  value: string;
  delta?: string;
  deltaTone?: string;
  breakdown?: string;
}

function KpiTile({ label, value, delta, deltaTone, breakdown }: KpiTileProps) {
  return (
    <div className="ab-kpi">
      <div className="ab-kpi-label">{label}</div>
      <div className="ab-kpi-value">{value}</div>
      {breakdown && <div className="ab-kpi-breakdown">{breakdown}</div>}
      {delta && <div className={"ab-kpi-delta " + (deltaTone || "")}>{delta}</div>}
    </div>
  );
}

/* ─────────────────────────────────────────────────────────────────
   PipelineVelocity (unused but kept)
   ───────────────────────────────────────────────────────────────── */

interface PipelinePhase {
  id: string;
  stage: string;
  name: string;
  next: string;
  note?: string;
  motion?: string;
  hint?: string;
}

function PipelineVelocity({ dealsByPhase }: { dealsByPhase: Record<string, Deal[]> }) {
  return (
    <div className="ab-velocity">
      {ADMIN_PIPELINE.map((p, i, arr) => {
        const count = (dealsByPhase[p.id] || []).length;
        const active = count > 0;
        return (
          <React.Fragment key={p.id}>
            <div className={"ab-vel-stage" + (active ? " active" : "")}>
              <span className="ab-vel-stage-tag mono">{p.stage}</span>
              <span className="ab-vel-stage-name">{p.name}</span>
              <span className="ab-vel-stage-count mono">{count}</span>
            </div>
            {i < arr.length - 1 && <div className="ab-vel-conn"></div>}
          </React.Fragment>
        );
      })}
    </div>
  );
}

/* ─────────────────────────────────────────────────────────────────
   DealCard
   ───────────────────────────────────────────────────────────────── */

interface Deal {
  id: string;
  phase: string;
  addr: string;
  line2: string;
  badge: string;
  progress?: string;
  next: string;
  owner?: string;
  ownerInitial?: string;
  daysInStage?: string;
  blocked?: boolean;
  primary?: boolean;
  top25Note?: string;
  price?: string;
  mls?: string;
  side?: string;
}

function DealCard({
  deal,
  onOpen,
  onDragStart,
  onDragEnd,
  dragging,
}: {
  deal: Deal;
  onOpen?: (deal: Deal) => void;
  onDragStart?: (id: string) => void;
  onDragEnd?: () => void;
  dragging?: boolean;
}) {
  return (
    <div
      className={"ab-deal" + (deal.blocked ? " blocked" : "") + (dragging ? " dragging" : "")}
      draggable
      onDragStart={(e) => {
        e.dataTransfer.effectAllowed = "move";
        e.dataTransfer.setData("text/plain", deal.id);
        onDragStart?.(deal.id);
      }}
      onDragEnd={() => onDragEnd?.()}
      onClick={() => onOpen?.(deal)}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onOpen?.(deal);
        }
      }}
      role="button"
      tabIndex={0}
    >
      <div className="ab-deal-addr" title={deal.addr}>{deal.addr}</div>
      <div className="ab-deal-line2">{deal.line2}</div>
      <div className="ab-deal-mid">
        <span className="ab-deal-badge">{deal.badge}</span>
        {deal.progress && <span className="ab-deal-progress mono">{deal.progress}</span>}
      </div>
      <div className="ab-deal-next">
        <span className="ab-deal-next-label mono">Next</span>
        <span className="ab-deal-next-text">{deal.next}</span>
      </div>
      <div className="ab-deal-foot">
        <span className="ab-deal-owner" title={deal.owner || "Demo Agent"}>
          {deal.ownerInitial || "A"}
        </span>
        <span className="ab-deal-time">{deal.daysInStage || "3d"} in stage</span>
        {deal.blocked && <span className="ab-deal-flag">Blocked</span>}
      </div>
    </div>
  );
}

/* ─────────────────────────────────────────────────────────────────
   PipelineColumn
   ───────────────────────────────────────────────────────────────── */

function PipelineColumn({
  phase,
  deals,
  onOpenDeal,
  onDropDeal,
  onCardDragStart,
  onCardDragEnd,
  draggingId,
  canDrop,
}: {
  phase: PipelinePhase;
  deals: Deal[];
  onOpenDeal: (deal: Deal) => void;
  onDropDeal?: (dealId: string, toStage: number) => void;
  onCardDragStart?: (id: string) => void;
  onCardDragEnd?: () => void;
  draggingId?: string | null;
  canDrop?: boolean;
}) {
  const motion = phase.motion || phase.note;
  const [isOver, setIsOver] = useState(false);
  // phase.stage is "S<n>" — the numeric stage the move endpoint expects.
  const stageNum = Number.parseInt(String(phase.stage).replace(/^S/i, ""), 10);
  const dndEnabled = Boolean(onDropDeal) && Number.isFinite(stageNum);
  return (
    <div
      className={"ab-col" + (isOver && canDrop ? " drop-over" : "")}
      onDragOver={(e) => {
        if (!dndEnabled || !draggingId) return;
        e.preventDefault();
        e.dataTransfer.dropEffect = "move";
        if (!isOver) setIsOver(true);
      }}
      onDragLeave={(e) => {
        if (!e.currentTarget.contains(e.relatedTarget as Node)) setIsOver(false);
      }}
      onDrop={(e) => {
        if (!dndEnabled) return;
        e.preventDefault();
        setIsOver(false);
        const id = e.dataTransfer.getData("text/plain") || draggingId;
        if (id) onDropDeal?.(id, stageNum);
      }}
    >
      <header className="ab-col-head">
        <span className="ab-col-stage mono">{phase.stage}</span>
        <span className="ab-col-name">{phase.name}</span>
        <span className="ab-col-count mono">{deals.length}</span>
      </header>
      {motion && <div className="ab-col-motion mono">{motion}</div>}
      <div className="ab-col-next">{phase.next}</div>
      {phase.hint && <div className="ab-col-hint">{phase.hint}</div>}
      <div className="ab-col-deals">
        {deals.length === 0 ? (
          <div className="ab-col-empty">
            {isOver && canDrop ? "Drop to move here" : "No deals in this stage"}
          </div>
        ) : (
          deals.map(d => (
            <DealCard
              key={d.id}
              deal={d}
              onOpen={onOpenDeal}
              onDragStart={onCardDragStart}
              onDragEnd={onCardDragEnd}
              dragging={draggingId === d.id}
            />
          ))
        )}
      </div>
    </div>
  );
}

/* ─────────────────────────────────────────────────────────────────
   Top25Deals
   ───────────────────────────────────────────────────────────────── */

function Top25Deals({
  deals,
  mode,
  onOpenDeal,
}: {
  deals: Deal[];
  mode: string;
  onOpenDeal: (deal: Deal) => void;
}) {
  const ranked = useMemo(() => {
    const listingOrder = [
      "pre-cma", "cma", "intake", "skyslope", "go", "live",
      "offer", "conditions", "closing", "closed",
    ];
    const buyerOrder = [
      "offer", "accepted", "conditions", "closed",
    ];
    const order = mode === "buyer" ? buyerOrder : listingOrder;
    const score = (d: Deal) => {
      const stage = order.indexOf(d.phase);
      return (d.blocked ? 1000 : 0) + stage * 10 + (d.primary ? 5 : 0);
    };
    return [...deals].sort((a, b) => score(b) - score(a)).slice(0, 25);
  }, [deals, mode]);

  const label = mode === "buyer" ? "Top 25 buyers" : "Top 25 sellers";
  const subEmpty = mode === "buyer"
    ? "No buyer-side deals tracked yet. Buyer deals show here when you start working a buyer."
    : "No seller-side deals yet.";

  return (
    <section className="ab-top25">
      <header className="ab-top25-head">
        <div className="ab-top25-title-block">
          <span className="ab-top25-title">{label}</span>
          <span className="ab-top25-sub mono">
            {ranked.length > 0
              ? `${ranked.length} ranked · later-stage first · blocked surface to the top`
              : "—"}
          </span>
        </div>
        <div className="ab-top25-legend mono">
          <span className="ab-top25-legend-item"><span className="ab-top25-legend-dot blocked"></span>blocked</span>
          <span className="ab-top25-legend-item"><span className="ab-top25-legend-dot primary"></span>primary</span>
        </div>
      </header>
      {ranked.length === 0 ? (
        <div className="ab-top25-empty">{subEmpty}</div>
      ) : (
        <div className="ab-top25-strip">
          {ranked.map((d, i) => (
            <button
              key={d.id}
              type="button"
              className={"ab-top25-card" + (d.blocked ? " blocked" : "") + (d.primary ? " primary" : "")}
              onClick={() => onOpenDeal && onOpenDeal(d)}
            >
              <div className="ab-top25-rank mono">{(i + 1).toString().padStart(2, "0")}</div>
              <div className="ab-top25-card-body">
                <div className="ab-top25-card-head">
                  <span className="ab-top25-card-addr">{d.addr}</span>
                  {d.blocked && <span className="ab-top25-card-flag">&bull;</span>}
                </div>
                <div className="ab-top25-card-badge mono">{d.badge}</div>
                {d.primary && d.top25Note && (
                  <div className="ab-top25-card-note">
                    <span className="ab-top25-card-note-label mono">Looking</span>
                    <span className="ab-top25-card-note-text">{d.top25Note}</span>
                  </div>
                )}
                <div className="ab-top25-card-foot">
                  {d.price && <span className="ab-top25-card-price mono">{d.price}</span>}
                  {d.progress && <span className="ab-top25-card-progress mono">{d.progress}</span>}
                </div>
              </div>
            </button>
          ))}
        </div>
      )}
    </section>
  );
}

/* ─────────────────────────────────────────────────────────────────
   UnifiedInbox
   ───────────────────────────────────────────────────────────────── */

interface ActionItem {
  id: string;
  title: string;
  desc: string;
  kind: string;
  schedule?: string;
  session?: string;
  next?: string;
}

interface AutomationItem {
  id: string;
  name: string;
  status: string;
  schedule: string;
  nextRun: string;
  detail?: string;
}

interface InboxItem {
  id: string;
  kind: string;
  kindLabel: string;
  sev: string;
  icon: React.ComponentType;
  title: string;
  desc: string;
  meta: string;
}

function UnifiedInbox() {
  const [filter, setFilter] = useState("all");
  const [page, setPage] = useState(0);
  const [showAll, setShowAll] = useState(false);
  const PAGE = 3;

  // Reset paging when filter changes
  useEffect(() => { setPage(0); }, [filter]);

  // Merge automations + actions into one prioritized list
  const items = useMemo<InboxItem[]>(() => {
    const out: InboxItem[] = [];

    // 1. Broken automations -- top priority
    for (const a of ADMIN_AUTOMATIONS) {
      if (a.status === "error") {
        out.push({
          id: "auto:" + a.id,
          kind: "broken",
          kindLabel: "Broken",
          sev: "high",
          icon: AlertTriangle,
          title: a.name + " is failing",
          desc: a.detail || "Automation failed on last run.",
          meta: a.nextRun || a.schedule,
        });
      }
    }

    // 2. Items needing human review
    for (const a of ADMIN_ACTIONS) {
      if (a.kind === "review") {
        out.push({
          id: "act:" + a.id,
          kind: "review",
          kindLabel: "Review",
          sev: "warn",
          icon: Shield,
          title: a.title.replace(/^Admin review:\s*/i, ""),
          desc: a.desc,
          meta: a.schedule || a.next || "",
        });
      }
    }

    // 3. Paused workflows to resume
    for (const a of ADMIN_ACTIONS) {
      if (a.kind === "resume") {
        out.push({
          id: "act:" + a.id,
          kind: "resume",
          kindLabel: "Resume",
          sev: "normal",
          icon: FileText,
          title: a.title.replace(/^Admin workflow:\s*/i, ""),
          desc: a.desc,
          meta: a.session || "",
        });
      }
    }

    // 4. Setup-incomplete automations
    for (const a of ADMIN_AUTOMATIONS) {
      if (a.status === "blocked") {
        out.push({
          id: "auto:" + a.id,
          kind: "setup",
          kindLabel: "Setup",
          sev: "normal",
          icon: ShieldAlert,
          title: a.name + " — finish setup",
          desc: a.detail || "Setup steps remain before this automation can run.",
          meta: a.nextRun || a.schedule,
        });
      }
    }

    // 5. Optional automations (lowest)
    for (const a of ADMIN_AUTOMATIONS) {
      if (a.status === "optional") {
        out.push({
          id: "auto:" + a.id,
          kind: "optional",
          kindLabel: "Optional",
          sev: "low",
          icon: Sparkles,
          title: a.name,
          desc: a.detail || "Optional automation, not enabled.",
          meta: a.schedule,
        });
      }
    }

    return out;
  }, []);

  const counts = useMemo(() => {
    const c: Record<string, number> = { all: items.length, broken: 0, review: 0, resume: 0, setup: 0, optional: 0 };
    for (const it of items) c[it.kind]++;
    return c;
  }, [items]);

  const filtered = filter === "all" ? items : items.filter(it => it.kind === filter);
  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE));
  const safePage = Math.min(page, totalPages - 1);
  const visible = showAll ? filtered : filtered.slice(safePage * PAGE, safePage * PAGE + PAGE);
  const rangeStart = filtered.length === 0 ? 0 : safePage * PAGE + 1;
  const rangeEnd = Math.min(filtered.length, safePage * PAGE + PAGE);

  const chips = [
    { id: "all",      label: "All" },
    { id: "broken",   label: "Broken",   showPulse: counts.broken > 0 },
    { id: "review",   label: "Review" },
    { id: "resume",   label: "Resume" },
    { id: "setup",    label: "Setup" },
    { id: "optional", label: "Optional" },
  ];

  return (
    <section className="ab-card">
      <header className="ab-inbox-head">
        <div className="ab-inbox-title-block">
          <span className="ab-inbox-title">Needs you</span>
          <span className="ab-inbox-sub mono">{items.length} items</span>
        </div>
        <div className="ab-inbox-filters">
          {chips.map(c => {
            const n = counts[c.id];
            if (c.id !== "all" && n === 0) return null;
            return (
              <button
                key={c.id}
                type="button"
                className={"ab-inbox-chip" + (filter === c.id ? " active" : "")}
                onClick={() => setFilter(c.id)}
              >
                <span>{c.label}</span>
                <span className="count mono">{n}</span>
              </button>
            );
          })}
        </div>
      </header>

      <div className="ab-inbox-list">
        {filtered.length === 0 ? (
          <div className="ab-inbox-empty">Nothing in this view. Nice.</div>
        ) : (
          visible.map(it => {
            return (
              <div key={it.id} className="ab-inbox-row" data-kind={it.kind} data-sev={it.sev}>
                <span className="ab-inbox-kind">
                  {it.kind === "broken" && <span className="ab-inbox-pulse"></span>}
                  {it.kindLabel}
                </span>
                <div className="ab-inbox-body">
                  <div className="ab-inbox-title-row">{it.title}</div>
                  {it.desc && <div className="ab-inbox-desc">{it.desc}</div>}
                </div>
                <span className="ab-inbox-meta mono">{it.meta}</span>
                <button type="button" className="ab-inbox-open">Open</button>
              </div>
            );
          })
        )}
      </div>

      {filtered.length > PAGE && (
        <footer className="ab-inbox-foot">
          <span className="ab-inbox-range mono">
            {showAll
              ? `Showing all ${filtered.length}`
              : `${rangeStart}–${rangeEnd} of ${filtered.length}`}
          </span>
          <div className="ab-inbox-pager">
            {!showAll && (
              <>
                <button
                  type="button"
                  className="ab-inbox-page-btn"
                  onClick={() => setPage(p => Math.max(0, p - 1))}
                  disabled={safePage === 0}
                  aria-label="Previous page"
                >&lsaquo;</button>
                <span className="ab-inbox-page-num mono">{safePage + 1} / {totalPages}</span>
                <button
                  type="button"
                  className="ab-inbox-page-btn"
                  onClick={() => setPage(p => Math.min(totalPages - 1, p + 1))}
                  disabled={safePage === totalPages - 1}
                  aria-label="Next page"
                >&rsaquo;</button>
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

/* ─────────────────────────────────────────────────────────────────
   FilterChip
   ───────────────────────────────────────────────────────────────── */

function FilterChip({
  label,
  count,
  active,
  onClick,
}: {
  label: string;
  count?: number | null;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button type="button" className={"ab-chip" + (active ? " active" : "")} onClick={onClick}>
      <span>{label}</span>
      {count != null && <span className="ab-chip-count mono">{count}</span>}
    </button>
  );
}

/* ─────────────────────────────────────────────────────────────────
   ActionRow (legacy, kept)
   ───────────────────────────────────────────────────────────────── */

function ActionRow({ action }: { action: ActionItem }) {
  const Icon = action.kind === "review" ? Shield : FileText;
  return (
    <div className="ab-action-row">
      <div className="ab-action-icon"><Icon /></div>
      <div className="ab-action-body">
        <div className="ab-action-head">
          <span className="ab-action-title">{action.title}</span>
          <span className={"ab-action-tag " + (action.kind === "review" ? "review" : "resume")}>
            {action.kind === "review" ? "Review" : "Resume"}
          </span>
        </div>
        <p className="ab-action-desc">{action.desc}</p>
        <div className="ab-action-meta">
          {action.schedule && <span className="mono">{action.schedule}</span>}
          {action.session && <span>{action.session}</span>}
          {action.next && <span>{action.next}</span>}
        </div>
      </div>
      <button className="ab-action-open" type="button">Open</button>
    </div>
  );
}

/* ─────────────────────────────────────────────────────────────────
   AutomationCard
   ───────────────────────────────────────────────────────────────── */

function AutomationCard({ auto }: { auto: AutomationItem }) {
  const runs = useMemo(() => {
    const base = ["ok","ok","ok","ok","ok","ok","ok"];
    if (auto.status === "error")   return ["ok","ok","ok","ok","ok","err","err"];
    if (auto.status === "blocked") return ["ok","ok","ok","skip","skip","skip","skip"];
    if (auto.status === "optional")return ["skip","skip","skip","skip","skip","skip","skip"];
    return base;
  }, [auto.status]);

  return (
    <div className="ab-auto-card" data-status={auto.status}>
      <div className="ab-auto-head">
        <span className="ab-auto-name">{auto.name}</span>
        <span className={"ab-auto-status " + auto.status}>{auto.status[0].toUpperCase() + auto.status.slice(1)}</span>
      </div>
      <div className="ab-auto-meta">
        <span className="ab-auto-schedule mono">{auto.schedule}</span>
        <Sparkline runs={runs} />
      </div>
      <div className="ab-auto-next">local &middot; {auto.nextRun}</div>
      {auto.detail && <div className="ab-auto-detail">{auto.detail}</div>}
    </div>
  );
}

/* ─────────────────────────────────────────────────────────────────
   WorkRow
   ───────────────────────────────────────────────────────────────── */

interface WorkItem {
  title: string;
  session: string;
  tools: number;
}

function WorkRow({ item }: { item: WorkItem }) {
  return (
    <div className="ab-work-row">
      <span className="ab-work-dot"></span>
      <div className="ab-work-body">
        <div className="ab-work-title">{item.title}</div>
        <div className="ab-work-sub mono">{item.session}</div>
      </div>
      <span className="ab-work-tools mono">{item.tools} tools</span>
    </div>
  );
}

/* ─────────────────────────────────────────────────────────────────
   NewDealModal — minimal create form wired to api.createAdminDeal
   ───────────────────────────────────────────────────────────────── */

function NewDealModal({
  onClose,
  onCreated,
}: {
  onClose: () => void;
  onCreated: () => void;
}) {
  const [side, setSide] = useState<AdminDealSide>("listing");
  const [title, setTitle] = useState("");
  const [province, setProvince] = useState("");
  const [listingAddress, setListingAddress] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const canSubmit = title.trim().length > 0 && province.trim().length > 0 && !submitting;

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!canSubmit) return;
    setSubmitting(true);
    setError(null);
    const cleanAddress = listingAddress.trim();
    const request: AdminDealCreateRequest = {
      title: title.trim(),
      side,
      province: province.trim().toUpperCase(),
      currentStage: 0,
      listingAddress: side === "listing" ? cleanAddress || null : null,
    };
    try {
      await api.createAdminDeal(request);
      onCreated();
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not create deal");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="ab-modal-backdrop" onClick={onClose}>
      <div
        className="ab-modal"
        onClick={(e: React.MouseEvent) => e.stopPropagation()}
        role="dialog"
        style={{ maxWidth: "30rem" }}
      >
        <button className="ab-modal-close" onClick={onClose} aria-label="Close">
          <span className="x">&times;</span>
        </button>
        <header className="abm-head">
          <div className="abm-crumbs mono">
            <span>NEW DEAL</span>
          </div>
          <h2 className="abm-title">Add a card to the board</h2>
        </header>
        <div className="ab-modal-scroll">
          <form onSubmit={handleSubmit} className="abm-newdeal-form">
            <div className="abm-section">
              <span className="abm-section-label mono">SIDE</span>
              <div className="ab-tabs" style={{ marginTop: 6 }}>
                <button
                  type="button"
                  className={"ab-tab" + (side === "listing" ? " active" : "")}
                  onClick={() => setSide("listing")}
                >
                  <span>Listing</span>
                </button>
                <button
                  type="button"
                  className={"ab-tab" + (side === "buyer" ? " active" : "")}
                  onClick={() => setSide("buyer")}
                >
                  <span>Buyer</span>
                </button>
              </div>
            </div>

            <div className="abm-section">
              <label className="abm-section-label mono" htmlFor="nd-title">
                CLIENT / TITLE
              </label>
              <input
                id="nd-title"
                className="abm-input"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                placeholder="Client name or deal title"
                autoFocus
              />
            </div>

            <div className="abm-section">
              <label className="abm-section-label mono" htmlFor="nd-province">
                PROVINCE
              </label>
              <input
                id="nd-province"
                className="abm-input"
                value={province}
                onChange={(e) => setProvince(e.target.value)}
                placeholder="e.g. BC"
              />
            </div>

            {side === "listing" && (
              <div className="abm-section">
                <label className="abm-section-label mono" htmlFor="nd-address">
                  LISTING ADDRESS
                </label>
                <input
                  id="nd-address"
                  className="abm-input"
                  value={listingAddress}
                  onChange={(e) => setListingAddress(e.target.value)}
                  placeholder="123 Sample Lane, Vancouver, BC"
                />
              </div>
            )}

            {error && (
              <div className="abm-tag warn" style={{ display: "block", padding: "6px 8px" }}>
                {error}
              </div>
            )}

            <div className="abm-actions">
              <button className="abm-btn primary" type="submit" disabled={!canSubmit}>
                {submitting ? "Creating..." : "Create deal"}
              </button>
              <button className="abm-btn ghost" type="button" onClick={onClose}>
                Cancel
              </button>
            </div>
          </form>
        </div>
      </div>
    </div>
  );
}

/* ─────────────────────────────────────────────────────────────────
   AdminBoard (main)
   ───────────────────────────────────────────────────────────────── */

function AdminBoard({ deals, buyerDeals, kpis, events, loading, error, onRefresh, onOpenDeal, onMoveDeal, onReRunOnboarding }: AdminBoardProps = {}) {
  const [tab, setTab] = useState("listing");
  const [query, setQuery] = useState("");
  const [activeDeal, setActiveDeal] = useState<Deal | null>(null);
  const [showNewDeal, setShowNewDeal] = useState(false);
  const [draggingId, setDraggingId] = useState<string | null>(null);

  const listingDeals = deals ?? ADMIN_DEALS;
  const buyerDealsResolved = buyerDeals ?? ADMIN_BUYER_DEALS;

  const isBuyer = tab === "buyer";
  const activePipeline = isBuyer ? ADMIN_BUYER_PIPELINE : ADMIN_PIPELINE;
  const allDeals       = isBuyer ? buyerDealsResolved   : listingDeals;

  // FIX 1: filter rendered deals by the search query (addr / line2 / mls)
  // before they get grouped into the kanban columns.
  const activeDeals = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return allDeals;
    return allDeals.filter((d) => {
      const haystack = [d.addr, d.line2, (d as Deal).mls]
        .filter(Boolean)
        .join(" ")
        .toLowerCase();
      return haystack.includes(q);
    });
  }, [allDeals, query]);

  const handleOpenDeal = (deal: Deal) => {
    setActiveDeal(deal);
    onOpenDeal?.(deal.id);
  };

  const dealsByPhase = useMemo(() => {
    const m: Record<string, Deal[]> = {};
    for (const d of activeDeals) (m[d.phase] = m[d.phase] || []).push(d);
    return m;
  }, [activeDeals]);

  return (
    <main className="admin-board">
      <header className="ab-top">
        <div className="ab-crumb">
          <span className="crumb">Admin desk</span>
          <span className="sep">&middot;</span>
          <span className="ab-live"><span className="ab-live-dot"></span>Local gateway online</span>
        </div>
        <div className="ab-top-actions">
          <button className="ab-btn ghost" type="button" onClick={onRefresh} disabled={loading}>
            <Refresh /><span>{loading ? "Refreshing..." : "Refresh"}</span>
          </button>
          <button className="ab-btn ghost" type="button" onClick={onReRunOnboarding}><Sparkles /><span>Re-run onboarding</span></button>
          <button className="ab-btn primary" type="button" onClick={() => setShowNewDeal(true)}><Plus /><span>New deal</span></button>
        </div>
      </header>

      <div className="ab-scroll">
        {error ? (
          <div style={{ padding: "8px 12px", margin: "0 0 12px", background: "color-mix(in srgb, #b85a3f 12%, transparent)", border: "1px solid color-mix(in srgb, #b85a3f 30%, transparent)", borderRadius: 6, fontSize: 12 }}>
            {error}
          </div>
        ) : null}

        {/* Top 25 deals strip */}
        <Top25Deals deals={activeDeals} mode={tab} onOpenDeal={handleOpenDeal} />

        {/* KPI tiles */}
        <section className="ab-kpis">
          {kpis && kpis.length > 0 ? (
            kpis.map((k, i) => (
              <KpiTile
                key={`${k.label}-${i}`}
                label={k.label}
                value={k.value}
                breakdown={k.breakdown}
                delta={k.delta}
                deltaTone={k.deltaTone}
              />
            ))
          ) : (
            <>
              <KpiTile label="Pipeline value"        value="—" breakdown="loading" />
              <KpiTile label="GCI pending"           value="—" breakdown="loading" />
              <KpiTile label="GCI YTD"               value="—" breakdown="loading" />
              <KpiTile label="Active deals"          value="—" breakdown="loading" />
              <KpiTile label="In offer / conditions" value="—" breakdown="loading" />
              <KpiTile label="Closed YTD units"      value="—" breakdown="loading" />
              <KpiTile label="Closed YTD volume"     value="—" breakdown="loading" />
              <KpiTile label="Key dates this week"   value="—" breakdown="loading" />
            </>
          )}
        </section>

        {/* Kanban with tabs + search */}
        <section className="ab-card">
          <header className="ab-card-head">
            <div className="ab-tabs">
              <button className={"ab-tab" + (tab === "listing" ? " active" : "")} onClick={() => setTab("listing")}>
                <span>Listing admin</span><span className="count mono">{listingDeals.length}</span>
              </button>
              <button className={"ab-tab" + (tab === "buyer" ? " active" : "")} onClick={() => setTab("buyer")}>
                <span>Buyer admin</span><span className="count mono">{buyerDealsResolved.length}</span>
              </button>
              <CyclingShowings items={events && events.length > 0 ? events : (ADMIN_SHOWINGS || [])} />
            </div>
            <div className="ab-card-actions">
              <div className="ab-search">
                <Search />
                <input
                  type="text"
                  placeholder="Search deals"
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                />
              </div>
            </div>
          </header>

          {/* Kanban */}
          <div className="ab-kanban">
            {activePipeline.map((p) => (
              <PipelineColumn
                key={p.id}
                phase={p}
                deals={dealsByPhase[p.id] || []}
                onOpenDeal={handleOpenDeal}
                onDropDeal={onMoveDeal}
                onCardDragStart={(id) => setDraggingId(id)}
                onCardDragEnd={() => setDraggingId(null)}
                draggingId={draggingId}
                canDrop={Boolean(draggingId)}
              />
            ))}
          </div>
        </section>
      </div>
      {activeDeal && <DealDetailModal deal={activeDeal} onClose={() => setActiveDeal(null)} />}
      {showNewDeal && (
        <NewDealModal
          onClose={() => setShowNewDeal(false)}
          onCreated={() => { onRefresh?.(); }}
        />
      )}
    </main>
  );
}

export default AdminBoard;

// Components defined above for future live-data wiring; reference them here
// so noUnusedLocals stays quiet until they're rendered.
void StatusPill;
void PipelineVelocity;
void UnifiedInbox;
void FilterChip;
void ActionRow;
void AutomationCard;
void WorkRow;
