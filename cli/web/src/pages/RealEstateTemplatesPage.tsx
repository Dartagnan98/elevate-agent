import { useCallback, useEffect, useLayoutEffect, useMemo, useState } from "react";
import {
  AlertCircle,
  Archive,
  CheckCircle2,
  Loader2,
  Pencil,
  RefreshCw,
  Sparkles,
  X,
} from "lucide-react";

import { fetchJSON } from "@/lib/api";
import { cn, isoTimeAgo } from "@/lib/utils";
import { usePageHeader } from "@/contexts/usePageHeader";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { useToast } from "@/hooks/useToast";

type TabKey = "live" | "proposed" | "retired";

interface LeaderboardEntry {
  lineageRootId: string;
  displayId: string;
  lane: string;
  name: string;
  body: string;
  channel: string;
  status: string;
  version: number;
  uses: number;
  replies: number;
  wins: number;
  replyRate: number;
  winRate: number;
  createdAt: string;
  versionCount: number;
}

interface Template {
  id: string;
  lane: string;
  name: string;
  body: string;
  channel: string;
  active: boolean;
  status: string;
  rationale: string | null;
  version: number;
  matchRules: unknown;
  origin: string;
  proposedByEventId: string | null;
  parentTemplateId: string | null;
  approvedAt: string | null;
  approvedBy: string | null;
  uses: number;
  replies: number;
  wins: number;
  replyRate: number;
  winRate: number;
  createdAt: string;
  updatedAt: string;
}

interface LiveResponse {
  tab: "live";
  authoritative: LeaderboardEntry[];
  trial: LeaderboardEntry[];
}

interface ListResponse {
  tab: "proposed" | "retired";
  items: Template[];
}

const TAB_LABELS: Record<TabKey, string> = {
  live: "Live",
  proposed: "Proposed",
  retired: "Retired",
};

const ORIGIN_LABEL: Record<string, string> = {
  ai_oneoff: "Freehand candidate",
  ai_pattern: "Pattern detection",
  ai_failure_analysis: "Failure analysis",
  human: "Hand-written",
};

function ratePct(n: number, digits = 1): string {
  if (!Number.isFinite(n) || n <= 0) return "0%";
  return `${(n * 100).toFixed(digits)}%`;
}

function templateApi(): {
  load: (tab: TabKey) => Promise<LiveResponse | ListResponse>;
  approve: (id: string) => Promise<Template>;
  reject: (id: string, reason: string) => Promise<Template>;
  edit: (id: string, body: string) => Promise<Template>;
  retire: (id: string) => Promise<Template>;
} {
  return {
    load: (tab) =>
      fetchJSON<LiveResponse | ListResponse>(`/api/admin/templates?tab=${tab}`),
    approve: (id) =>
      fetchJSON<Template>(`/api/admin/templates/${encodeURIComponent(id)}/approve`, {
        method: "POST",
      }),
    reject: (id, reason) =>
      fetchJSON<Template>(`/api/admin/templates/${encodeURIComponent(id)}/reject`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ reason }),
      }),
    edit: (id, body) =>
      fetchJSON<Template>(`/api/admin/templates/${encodeURIComponent(id)}/edit`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ body }),
      }),
    retire: (id) =>
      fetchJSON<Template>(`/api/admin/templates/${encodeURIComponent(id)}/retire`, {
        method: "POST",
      }),
  };
}

function TabPill({
  active,
  count,
  label,
  onClick,
}: {
  active: boolean;
  count: number | null;
  label: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "inline-flex h-8 items-center gap-2 rounded-full px-3 text-xs font-medium transition-colors cursor-pointer",
        "focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring/70",
        active
          ? "bg-primary text-primary-foreground"
          : "bg-card text-muted-foreground hover:text-foreground",
      )}
    >
      <span>{label}</span>
      {count !== null && (
        <span
          className={cn(
            "rounded-full px-1.5 font-mono text-[0.65rem] leading-4",
            active ? "bg-primary-foreground/20" : "bg-foreground/10",
          )}
        >
          {count}
        </span>
      )}
    </button>
  );
}

function LaneChannelBadges({ lane, channel }: { lane: string; channel: string }) {
  return (
    <div className="flex items-center gap-1.5">
      <Badge variant="outline" className="font-mono text-[0.6rem] uppercase tracking-wider">
        {lane}
      </Badge>
      <Badge variant="secondary" className="font-mono text-[0.6rem] uppercase tracking-wider">
        {channel}
      </Badge>
    </div>
  );
}

function MetricCell({
  label,
  value,
  sub,
  emphasize,
}: {
  label: string;
  value: string;
  sub?: string;
  emphasize?: boolean;
}) {
  return (
    <div className="flex flex-col gap-0.5">
      <span className="font-mono text-[0.6rem] uppercase tracking-wider text-muted-foreground">
        {label}
      </span>
      <span
        className={cn(
          "tabular-nums",
          emphasize ? "text-base font-semibold text-foreground" : "text-sm text-foreground",
        )}
      >
        {value}
      </span>
      {sub && <span className="text-[0.65rem] text-muted-foreground">{sub}</span>}
    </div>
  );
}

function LeaderboardCard({
  row,
  onRetire,
  onEdit,
  bucket,
}: {
  row: LeaderboardEntry;
  onRetire: (id: string) => void;
  onEdit: (id: string, body: string) => void;
  bucket: "authoritative" | "trial";
}) {
  return (
    <Card>
      <CardHeader className="flex flex-row items-start justify-between gap-3">
        <div className="flex flex-col gap-1.5">
          <div className="flex items-center gap-2">
            <CardTitle>{row.name}</CardTitle>
            <span className="font-mono text-[0.6rem] uppercase tracking-wider text-muted-foreground">
              v{row.version}
              {row.versionCount > 1 ? ` · ${row.versionCount} versions` : ""}
            </span>
          </div>
          <LaneChannelBadges lane={row.lane} channel={row.channel} />
        </div>
        <div className="flex items-center gap-1">
          {bucket === "trial" && (
            <Badge variant="warning" className="font-mono uppercase tracking-wider">
              Trial
            </Badge>
          )}
          <Button
            variant="ghost"
            size="sm"
            onClick={() => onEdit(row.displayId, row.body)}
            title="Edit body (bumps version)"
          >
            <Pencil className="h-3.5 w-3.5" />
            Edit
          </Button>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => onRetire(row.displayId)}
            title="Retire this template"
          >
            <Archive className="h-3.5 w-3.5" />
            Retire
          </Button>
        </div>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <p className="whitespace-pre-wrap text-sm leading-relaxed text-foreground/90">
          {row.body}
        </p>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <MetricCell
            label="Reply rate"
            value={ratePct(row.replyRate)}
            sub={`${row.replies}/${row.uses}`}
            emphasize
          />
          <MetricCell
            label="Win rate"
            value={ratePct(row.winRate)}
            sub={`${row.wins}/${row.uses}`}
            emphasize
          />
          <MetricCell label="Uses" value={String(row.uses)} />
          <MetricCell label="Created" value={isoTimeAgo(row.createdAt)} />
        </div>
      </CardContent>
    </Card>
  );
}

function ProposedCard({
  template,
  onApprove,
  onReject,
  onEdit,
  busy,
}: {
  template: Template;
  onApprove: (id: string) => void;
  onReject: (id: string) => void;
  onEdit: (id: string, body: string) => void;
  busy: boolean;
}) {
  const [draftBody, setDraftBody] = useState(template.body);
  const dirty = draftBody !== template.body;

  return (
    <Card>
      <CardHeader className="flex flex-col gap-2">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex flex-col gap-1.5">
            <CardTitle>{template.name}</CardTitle>
            <LaneChannelBadges lane={template.lane} channel={template.channel} />
          </div>
          <Badge variant="outline" className="font-mono text-[0.6rem] uppercase tracking-wider">
            {ORIGIN_LABEL[template.origin] ?? template.origin}
          </Badge>
        </div>
        {template.rationale && (
          <CardDescription className="flex items-start gap-1.5 leading-snug">
            <Sparkles className="mt-0.5 h-3 w-3 shrink-0 text-primary" />
            <span>{template.rationale}</span>
          </CardDescription>
        )}
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <textarea
          value={draftBody}
          onChange={(e) => setDraftBody(e.target.value)}
          className={cn(
            "min-h-[7.5rem] w-full resize-y rounded-sm border border-border bg-card px-3 py-2",
            "text-sm leading-relaxed text-foreground placeholder:text-muted-foreground/70",
            "focus-visible:border-ring focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring",
          )}
          spellCheck
          rows={6}
        />
        <div className="flex flex-wrap items-center justify-between gap-2">
          <span className="font-mono text-[0.6rem] uppercase tracking-wider text-muted-foreground">
            Proposed {isoTimeAgo(template.createdAt)}
          </span>
          <div className="flex items-center gap-2">
            {dirty && (
              <Button
                variant="outline"
                size="sm"
                onClick={() => onEdit(template.id, draftBody)}
                disabled={busy || !draftBody.trim()}
              >
                <Pencil className="h-3.5 w-3.5" />
                Save edit
              </Button>
            )}
            <Button
              variant="ghost"
              size="sm"
              onClick={() => onReject(template.id)}
              disabled={busy}
            >
              <X className="h-3.5 w-3.5" />
              Reject
            </Button>
            <Button
              size="sm"
              onClick={() => onApprove(template.id)}
              disabled={busy || dirty}
              title={dirty ? "Save your edit before approving" : "Approve and go live"}
            >
              <CheckCircle2 className="h-3.5 w-3.5" />
              Approve
            </Button>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

function RetiredRow({ template }: { template: Template }) {
  return (
    <Card>
      <CardHeader className="flex flex-row items-start justify-between gap-3">
        <div className="flex flex-col gap-1.5">
          <CardTitle className="text-foreground/85">{template.name}</CardTitle>
          <LaneChannelBadges lane={template.lane} channel={template.channel} />
        </div>
        <Badge variant="destructive" className="font-mono uppercase tracking-wider">
          {template.status === "rejected" ? "Rejected" : "Retired"}
        </Badge>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <p className="whitespace-pre-wrap text-sm leading-relaxed text-foreground/70">
          {template.body}
        </p>
        {template.rationale && (
          <p className="border-l border-border/60 pl-3 text-xs italic text-muted-foreground">
            {template.rationale}
          </p>
        )}
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <MetricCell label="Final reply rate" value={ratePct(template.replyRate)} />
          <MetricCell label="Total uses" value={String(template.uses)} />
          <MetricCell label="Wins" value={String(template.wins)} />
          <MetricCell label="Closed" value={isoTimeAgo(template.updatedAt)} />
        </div>
      </CardContent>
    </Card>
  );
}

function EmptyState({ title, hint }: { title: string; hint: string }) {
  return (
    <div className="flex min-h-[16rem] flex-col items-center justify-center gap-2 rounded-md border border-dashed border-border bg-card px-6 py-10 text-center">
      <span className="font-mono text-xs uppercase tracking-wider text-muted-foreground">
        {title}
      </span>
      <p className="max-w-md text-sm text-muted-foreground/85">{hint}</p>
    </div>
  );
}

export default function RealEstateTemplatesPage() {
  const { setTitle, setAfterTitle, setEnd } = usePageHeader();
  const { showToast } = useToast();
  const api = useMemo(templateApi, []);

  const [tab, setTab] = useState<TabKey>("live");
  const [live, setLive] = useState<LiveResponse | null>(null);
  const [proposed, setProposed] = useState<Template[] | null>(null);
  const [retired, setRetired] = useState<Template[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  const refresh = useCallback(
    async (which: TabKey | "all" = "all") => {
      setLoading(true);
      setError(null);
      try {
        const targets: TabKey[] = which === "all" ? ["live", "proposed", "retired"] : [which];
        await Promise.all(
          targets.map(async (t) => {
            const resp = await api.load(t);
            if (resp.tab === "live") {
              setLive(resp);
            } else if (resp.tab === "proposed") {
              setProposed(resp.items);
            } else {
              setRetired(resp.items);
            }
          }),
        );
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      } finally {
        setLoading(false);
      }
    },
    [api],
  );

  useEffect(() => {
    void refresh("all");
  }, [refresh]);

  const proposedCount = proposed?.length ?? null;
  const retiredCount = retired?.length ?? null;
  const liveCount =
    live ? live.authoritative.length + live.trial.length : null;

  useLayoutEffect(() => {
    setTitle("Templates");
    setAfterTitle(
      <span className="font-mono text-[0.65rem] uppercase tracking-wider text-muted-foreground">
        Admin · Approval queue
      </span>,
    );
    setEnd(
      <Button
        variant="outline"
        size="sm"
        onClick={() => void refresh("all")}
        disabled={loading}
      >
        <RefreshCw className={cn("h-3.5 w-3.5", loading && "animate-spin")} />
        Refresh
      </Button>,
    );
    return () => {
      setTitle(null);
      setAfterTitle(null);
      setEnd(null);
    };
  }, [loading, refresh, setAfterTitle, setEnd, setTitle]);

  const handleApprove = useCallback(
    async (id: string) => {
      setBusyId(id);
      try {
        await api.approve(id);
        showToast("Template approved — now live.", "success");
        await refresh("all");
      } catch (e) {
        showToast(
          `Approve failed: ${e instanceof Error ? e.message : String(e)}`,
          "error",
        );
      } finally {
        setBusyId(null);
      }
    },
    [api, refresh, showToast],
  );

  const handleReject = useCallback(
    async (id: string) => {
      const reason = window.prompt("Reject reason? (kept on the template for learning)");
      if (!reason || !reason.trim()) return;
      setBusyId(id);
      try {
        await api.reject(id, reason.trim());
        showToast("Template rejected.", "success");
        await refresh("all");
      } catch (e) {
        showToast(
          `Reject failed: ${e instanceof Error ? e.message : String(e)}`,
          "error",
        );
      } finally {
        setBusyId(null);
      }
    },
    [api, refresh, showToast],
  );

  const handleEdit = useCallback(
    async (id: string, currentBody: string) => {
      const next = window.prompt("New body? (this bumps the version)", currentBody);
      if (!next || !next.trim() || next === currentBody) return;
      setBusyId(id);
      try {
        await api.edit(id, next.trim());
        showToast("Edit saved — version bumped.", "success");
        await refresh("all");
      } catch (e) {
        showToast(
          `Edit failed: ${e instanceof Error ? e.message : String(e)}`,
          "error",
        );
      } finally {
        setBusyId(null);
      }
    },
    [api, refresh, showToast],
  );

  const handleRetire = useCallback(
    async (id: string) => {
      if (!window.confirm("Retire this template? It stops being eligible for the picker.")) {
        return;
      }
      setBusyId(id);
      try {
        await api.retire(id);
        showToast("Template retired.", "success");
        await refresh("all");
      } catch (e) {
        showToast(
          `Retire failed: ${e instanceof Error ? e.message : String(e)}`,
          "error",
        );
      } finally {
        setBusyId(null);
      }
    },
    [api, refresh, showToast],
  );

  const handleEditFromProposed = useCallback(
    async (id: string, body: string) => {
      setBusyId(id);
      try {
        await api.edit(id, body);
        showToast("Body updated.", "success");
        await refresh("proposed");
      } catch (e) {
        showToast(
          `Save failed: ${e instanceof Error ? e.message : String(e)}`,
          "error",
        );
      } finally {
        setBusyId(null);
      }
    },
    [api, refresh, showToast],
  );

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-6 px-6 pb-12 pt-4">
      <div className="flex flex-wrap items-center gap-2">
        <TabPill
          active={tab === "live"}
          count={liveCount}
          label={TAB_LABELS.live}
          onClick={() => setTab("live")}
        />
        <TabPill
          active={tab === "proposed"}
          count={proposedCount}
          label={TAB_LABELS.proposed}
          onClick={() => setTab("proposed")}
        />
        <TabPill
          active={tab === "retired"}
          count={retiredCount}
          label={TAB_LABELS.retired}
          onClick={() => setTab("retired")}
        />
        {loading && (
          <span className="inline-flex items-center gap-1.5 text-xs text-muted-foreground">
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
            Loading
          </span>
        )}
      </div>

      {error && (
        <div className="flex items-start gap-2 rounded-md border border-border border-l-2 border-l-destructive bg-card px-4 py-3 text-sm text-destructive">
          <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {tab === "live" && (
        <LiveTabContent
          data={live}
          onEdit={handleEdit}
          onRetire={handleRetire}
        />
      )}

      {tab === "proposed" && (
        <ProposedTabContent
          items={proposed}
          busyId={busyId}
          onApprove={handleApprove}
          onReject={handleReject}
          onEdit={handleEditFromProposed}
        />
      )}

      {tab === "retired" && <RetiredTabContent items={retired} />}
    </div>
  );
}

function LiveTabContent({
  data,
  onEdit,
  onRetire,
}: {
  data: LiveResponse | null;
  onEdit: (id: string, body: string) => void;
  onRetire: (id: string) => void;
}) {
  if (!data) {
    return null;
  }
  if (!data.authoritative.length && !data.trial.length) {
    return (
      <EmptyState
        title="No live templates yet"
        hint="Approve a proposed candidate to seed the picker pool. Until you do, replies fall back to plain freehand drafts."
      />
    );
  }
  return (
    <div className="flex flex-col gap-6">
      {data.authoritative.length > 0 && (
        <section className="flex flex-col gap-3">
          <SectionHead
            label="Authoritative"
            hint="Cleared the min-sample window (50+ uses or 30+ days). Stats are real."
          />
          <div className="flex flex-col gap-3">
            {data.authoritative.map((row) => (
              <LeaderboardCard
                key={row.lineageRootId}
                row={row}
                bucket="authoritative"
                onEdit={onEdit}
                onRetire={onRetire}
              />
            ))}
          </div>
        </section>
      )}

      {data.trial.length > 0 && (
        <section className="flex flex-col gap-3">
          <SectionHead
            label="Trial"
            hint="Eligible for the picker but sample is still thin. Don't kill these on early numbers."
          />
          <div className="flex flex-col gap-3">
            {data.trial.map((row) => (
              <LeaderboardCard
                key={row.lineageRootId}
                row={row}
                bucket="trial"
                onEdit={onEdit}
                onRetire={onRetire}
              />
            ))}
          </div>
        </section>
      )}
    </div>
  );
}

function ProposedTabContent({
  items,
  busyId,
  onApprove,
  onReject,
  onEdit,
}: {
  items: Template[] | null;
  busyId: string | null;
  onApprove: (id: string) => void;
  onReject: (id: string) => void;
  onEdit: (id: string, body: string) => void;
}) {
  if (!items) return null;
  if (items.length === 0) {
    return (
      <EmptyState
        title="Approval queue is empty"
        hint="The one-off detector seeds candidates whenever a freehand reply lands, and the weekly gap analysis seeds more from low-reply lanes."
      />
    );
  }
  return (
    <div className="flex flex-col gap-3">
      {items.map((tpl) => (
        <ProposedCard
          key={tpl.id}
          template={tpl}
          busy={busyId === tpl.id}
          onApprove={onApprove}
          onReject={onReject}
          onEdit={onEdit}
        />
      ))}
    </div>
  );
}

function RetiredTabContent({ items }: { items: Template[] | null }) {
  if (!items) return null;
  if (items.length === 0) {
    return (
      <EmptyState
        title="Nothing retired yet"
        hint="Retire low performers from the Live tab. They stay here with full history so you can see what didn't work."
      />
    );
  }
  return (
    <div className="flex flex-col gap-3">
      {items.map((tpl) => (
        <RetiredRow key={tpl.id} template={tpl} />
      ))}
    </div>
  );
}

function SectionHead({ label, hint }: { label: string; hint: string }) {
  return (
    <header className="flex flex-col gap-0.5 border-b border-border/40 pb-2">
      <span className="font-mono text-[0.62rem] uppercase tracking-wider text-muted-foreground">
        {label}
      </span>
      <span className="text-xs text-muted-foreground/85">{hint}</span>
    </header>
  );
}

