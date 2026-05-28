# Elevate: Real Estate Hub Pages
Today, Leads, Admin, Memory, Social Media, Tasks, Templates.

---
## `src/pages/RealEstateHubPages.tsx`
```tsx
import {
  createElement,
  memo,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ComponentType,
} from "react";
import {
  Activity,
  AlertTriangle,
  BookText,
  BriefcaseBusiness,
  Check,
  CheckCircle2,
  CheckSquare,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  Database as DatabaseIcon,
  ExternalLink,
  FileCheck2,
  FileText,
  Flame,
  Filter,
  Inbox,
  Loader2,
  HelpCircle,
  Mail,
  MessageSquare,
  Phone,
  Square as SquareIcon,
  Share2,
  Smartphone,
  Network,
  Pause,
  PencilLine,
  Play,
  Plug,
  Plus,
  Radar,
  Repeat,
  RotateCcw,
  Send,
  Sparkles,
  Trash2,
  TrendingDown,
  Award,
  ThumbsUp,
  ThumbsDown,
  Users,
  XCircle,
  Zap,
} from "lucide-react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "@/lib/api";
import type {
  BuyerWatchlistEntry,
  ComposioConnectedAccount,
  ComposioStatus,
  CronJob,
  OutreachLane,
  OutreachLaneOverview,
  OutreachOverview,
  OutreachTemplate,
  SourceConnectorStatus,
  SourceInboxDraft,
  SourceInboxProfile,
  SourceInboxResponse,
  SourceInboxSentItem,
  SourceInboxThread,
} from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button, buttonVariants } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Select, SelectOption } from "@/components/ui/select";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { cn, isoTimeAgo } from "@/lib/utils";
import { ThreadDrawerProvider, useThreadDrawer } from "@/pages/real-estate-hub/thread-drawer";
import {
  computeResponsePulse,
  formatMinutes,
  heatStyles,
  inboundWaitMinutes,
  leadSectionCount,
  leadSectionThreads,
  leadThreadBuckets,
  profileWhen,
  threadWhen,
  type ResponsePulse,
} from "@/pages/real-estate-hub/utils";
import {
  PROFILE_ACTION_BUCKETS,
  PROFILE_ADMIN_SIDE_COPY,
  isActiveProfileThread,
  profileActionBucket,
  profileActionSort,
  profileContactLine,
  profileConversationSort,
  profileHasActiveConversation,
  profileHasVerifier,
  profilePrimaryContactId,
  profileSourceMeta,
  profileVerifierSummary,
  threadSortTime,
  type ProfileActionBucketId,
  type ProfileAdminDealIds,
} from "@/pages/real-estate-hub/profile-workflow";
import {
  HubShell,
  jobMatches,
  LeadStatusBadge,
  LeadStatusControl,
  parseIdentity,
  provenanceLine,
  RecentSessions,
  sessionMatches,
  TimedTasks,
  useHubHeader,
  useRealEstateHubData,
  type BoardAction,
  type HubData,
} from "@/pages/real-estate-hub/_shared";
import { LeadsSetupLaunch, useLeadsSetup } from "@/pages/real-estate-hub/leads/onboarding";

export type { BoardAction, HubData };

const PROFILE_PAGE_SIZE_OPTIONS = [20, 50, 100] as const;
type ProfilePageSize = (typeof PROFILE_PAGE_SIZE_OPTIONS)[number];

function compactPageNumbers(current: number, total: number): (number | "…")[] {
  if (total <= 7) {
    return Array.from({ length: total }, (_, i) => i + 1);
  }
  const pages: (number | "…")[] = [1];
  const start = Math.max(2, current - 1);
  const end = Math.min(total - 1, current + 1);
  if (start > 2) pages.push("…");
  for (let i = start; i <= end; i++) pages.push(i);
  if (end < total - 1) pages.push("…");
  pages.push(total);
  return pages;
}

function PaginationBar({
  page,
  totalPages,
  onPageChange,
  label,
}: {
  page: number;
  totalPages: number;
  onPageChange: (next: number) => void;
  label: string;
}) {
  if (totalPages <= 1) return null;
  const pages = compactPageNumbers(page, totalPages);
  return (
    <nav
      aria-label={label}
      className="flex flex-wrap items-center justify-end gap-1 px-4 py-2.5"
    >
      <Button
        type="button"
        size="sm"
        variant="outline"
        className="h-8 px-2"
        disabled={page <= 1}
        onClick={() => onPageChange(page - 1)}
        aria-label="Previous page"
      >
        <ChevronLeft className="h-3.5 w-3.5" />
      </Button>
      {pages.map((p, idx) =>
        p === "…" ? (
          <span
            key={`gap-${idx}`}
            className="px-1 text-xs text-muted-foreground"
            aria-hidden
          >
            …
          </span>
        ) : (
          <Button
            key={p}
            type="button"
            size="sm"
            variant={p === page ? "default" : "outline"}
            className="h-8 min-w-[2rem] px-2 text-xs"
            onClick={() => onPageChange(p)}
            aria-current={p === page ? "page" : undefined}
          >
            {p}
          </Button>
        ),
      )}
      <Button
        type="button"
        size="sm"
        variant="outline"
        className="h-8 px-2"
        disabled={page >= totalPages}
        onClick={() => onPageChange(page + 1)}
        aria-label="Next page"
      >
        <ChevronRight className="h-3.5 w-3.5" />
      </Button>
    </nav>
  );
}

function LeadProfilesWorkbench({
  onChanged,
  showHeader = true,
  profiles,
  threads,
}: {
  onChanged: (nextInbox?: SourceInboxResponse) => void | Promise<void>;
  showHeader?: boolean;
  profiles: SourceInboxProfile[];
  threads: SourceInboxThread[];
}) {
  const drawer = useThreadDrawer();
  const navigate = useNavigate();
  const [dealIdsByProfile, setDealIdsByProfile] = useState<Record<string, ProfileAdminDealIds>>({});
  const [pageSize, setPageSize] = useState<ProfilePageSize>(20);
  const [pageBySection, setPageBySection] = useState<Record<string, number>>({});

  useEffect(() => {
    let live = true;
    api
      .getAdminDeals({ status: "active", limit: 200 })
      .then((dealsResponse) => {
        if (!live) return;
        const next: Record<string, ProfileAdminDealIds> = {};
        for (const deal of dealsResponse.items) {
          const sourceProfileId = deal.extraToggles?.sourceProfileId;
          if (typeof sourceProfileId === "string" && (deal.side === "listing" || deal.side === "buyer")) {
            next[sourceProfileId] = {
              ...next[sourceProfileId],
              [deal.side]: deal.id,
            };
          }
        }
        setDealIdsByProfile(next);
      })
      .catch(() => {
        if (live) setDealIdsByProfile({});
      });
    return () => {
      live = false;
    };
  }, []);

  const threadsByProfileId = useMemo(() => {
    const byAnyThreadId = new Map<string, SourceInboxThread>();
    for (const thread of threads) {
      byAnyThreadId.set(thread.id, thread);
      byAnyThreadId.set(thread.threadId, thread);
    }
    const next = new Map<string, SourceInboxThread[]>();
    for (const profile of profiles) {
      const matches: SourceInboxThread[] = [];
      for (const threadId of profile.threadIds) {
        const thread = byAnyThreadId.get(threadId);
        if (thread && !matches.some((match) => match.id === thread.id)) {
          matches.push(thread);
        }
      }
      if (matches.length) {
        matches.sort((a, b) => {
          const active = Number(isActiveProfileThread(b)) - Number(isActiveProfileThread(a));
          if (active !== 0) return active;
          return threadSortTime(b) - threadSortTime(a);
        });
        next.set(profile.id, matches);
      }
    }
    return next;
  }, [profiles, threads]);

  const threadByProfileId = useMemo(() => {
    const next = new Map<string, SourceInboxThread>();
    for (const [profileId, profileThreads] of threadsByProfileId) {
      const activeThread = profileThreads.find(isActiveProfileThread);
      next.set(profileId, activeThread ?? profileThreads[0]);
    }
    return next;
  }, [threadsByProfileId]);

  const profileSections = useMemo(() => {
    const grouped: Record<ProfileActionBucketId, SourceInboxProfile[]> = {
      "active-conversation": [],
      "push-admin": [],
      "needs-verifier": [],
      "follow-up": [],
      "in-admin": [],
    };
    for (const profile of profiles) {
      grouped[
        profileActionBucket(
          profile,
          dealIdsByProfile[profile.id],
          profileHasActiveConversation(profile, threadsByProfileId.get(profile.id)),
        )
      ].push(profile);
    }
    return PROFILE_ACTION_BUCKETS.map((bucket) => ({
      ...bucket,
      profiles: grouped[bucket.id]
        .slice()
        .sort(bucket.id === "active-conversation" ? profileConversationSort : profileActionSort),
    })).filter((section) => section.profiles.length > 0);
  }, [dealIdsByProfile, profiles, threadsByProfileId]);

  const openProfileThread = (profile: SourceInboxProfile) => {
    const thread = threadByProfileId.get(profile.id);
    if (!thread) return;
    if (drawer) {
      drawer.openThread(thread.sourceId, thread.threadId);
      return;
    }
    const params = new URLSearchParams({ source: thread.sourceId, thread: thread.threadId });
    navigate(`/chat?${params.toString()}`);
  };

  if (!profiles.length) {
    return (
      <div className="px-4 py-3">
        <p className="text-xs text-muted-foreground/80">
          No profiles yet. Synced contacts and conversations will appear here with buyer and seller admin handoff actions.
        </p>
      </div>
    );
  }

  const handlePageSizeChange = (raw: string) => {
    const next = Number(raw) as ProfilePageSize;
    if (PROFILE_PAGE_SIZE_OPTIONS.includes(next)) {
      setPageSize(next);
      setPageBySection({});
    }
  };

  return (
    <div className="divide-y divide-border">
      <div className="flex flex-wrap items-center justify-between gap-3 px-4 py-3">
        {showHeader ? (
          <div>
            <div className="text-sm font-semibold text-foreground">Profiles</div>
            <p className="mt-0.5 text-xs leading-5 text-muted-foreground">
              People built from CRM, inbox, SMS, and social sources, with active conversations pinned first.
            </p>
          </div>
        ) : (
          <span className="font-mono-ui text-[0.66rem] uppercase tracking-[0.12em] text-muted-foreground">
            Per page
          </span>
        )}
        <div className="flex items-center gap-2">
          {showHeader && (
            <Badge variant="outline">{profiles.length} profiles</Badge>
          )}
          <Select
            value={String(pageSize)}
            onValueChange={handlePageSizeChange}
            buttonClassName="h-8 px-2 text-xs"
          >
            {PROFILE_PAGE_SIZE_OPTIONS.map((option) => (
              <SelectOption key={option} value={String(option)}>
                {option} / page
              </SelectOption>
            ))}
          </Select>
        </div>
      </div>

      {profileSections.map((section) => {
        const totalPages = Math.max(1, Math.ceil(section.profiles.length / pageSize));
        const rawPage = pageBySection[section.id] ?? 1;
        const page = Math.min(Math.max(rawPage, 1), totalPages);
        const start = (page - 1) * pageSize;
        const visibleProfiles = section.profiles.slice(start, start + pageSize);
        return (
        <div key={section.id} className="divide-y divide-border">
          <div className="bg-card px-4 py-2.5">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="font-mono-ui text-[0.66rem] font-semibold uppercase tracking-[0.16em] text-muted-foreground/90">
                {section.label}
              </div>
              <Badge variant="outline">{section.profiles.length}</Badge>
            </div>
            <p className="mt-1 text-xs leading-5 text-muted-foreground">
              {section.description}
            </p>
          </div>

          {visibleProfiles.map((profile) => {
            const thread = threadByProfileId.get(profile.id);
            const activeConversation = profileHasActiveConversation(profile, threadsByProfileId.get(profile.id));
            const dealIds = dealIdsByProfile[profile.id] ?? {};
            const sellerDealId = dealIds.listing;
            const buyerDealId = dealIds.buyer;
            return (
              <div key={profile.id} className="px-4 py-3">
                <div className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-center">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-x-2.5 gap-y-1">
                      <span
                        className={cn(
                          "h-2 w-2 shrink-0 rounded-full",
                          profile.heatLabel === "hot"
                            ? "bg-destructive"
                            : profile.heatLabel === "warm"
                              ? "bg-warning"
                              : profile.heatLabel === "watch"
                                ? "bg-success"
                                : "bg-muted-foreground/45",
                        )}
                        aria-hidden
                      />
                      <div className="min-w-0 truncate text-sm font-semibold text-foreground">
                        {profile.displayName}
                      </div>
                      <span
                        className="font-mono-ui shrink-0 text-[0.68rem] font-medium uppercase tracking-[0.08em] text-muted-foreground"
                        title={`${profile.heatLabel} · score ${profile.heatScore}`}
                      >
                        {profile.heatLabel} {profile.heatScore}
                      </span>
                      {profileHasVerifier(profile) ? (
                        <span
                          className="inline-flex items-center gap-1 text-[0.72rem] text-success"
                          title={profileVerifierSummary(profile)}
                        >
                          <CheckCircle2 className="h-3 w-3" aria-hidden />
                          verified
                        </span>
                      ) : (
                        <span
                          className="inline-flex items-center gap-1 text-[0.72rem] text-warning"
                          title={profileVerifierSummary(profile)}
                        >
                          <AlertTriangle className="h-3 w-3" aria-hidden />
                          needs verifier
                        </span>
                      )}
                      {profile.hasCrm && <Badge variant="success">CRM</Badge>}
                      {activeConversation && <Badge variant="success">active</Badge>}
                      {profile.isPotentialLead && !profile.hasCrm && (
                        <Badge variant="warning">potential lead</Badge>
                      )}
                      {sellerDealId && <Badge variant="success">{PROFILE_ADMIN_SIDE_COPY.listing.badgeLabel}</Badge>}
                      {buyerDealId && <Badge variant="success">{PROFILE_ADMIN_SIDE_COPY.buyer.badgeLabel}</Badge>}
                      <LeadStatusBadge status={profile.status} />
                    </div>
                    <p className="mt-1.5 line-clamp-2 text-xs leading-5 text-muted-foreground">
                      {profile.latestText || "No recent source context yet."}
                    </p>
                    <div className="mt-2 flex flex-wrap items-center gap-x-2 gap-y-1 text-[0.72rem] text-muted-foreground">
                      <span>{profileSourceMeta(profile)}</span>
                      <span aria-hidden className="text-muted-foreground/50">·</span>
                      <span>{profileContactLine(profile)}</span>
                      {profilePrimaryContactId(profile) && (
                        <>
                          <span aria-hidden className="text-muted-foreground/50">·</span>
                          <span>DB contact</span>
                        </>
                      )}
                      <span aria-hidden className="text-muted-foreground/50">·</span>
                      <span>{profile.threadCount} thread{profile.threadCount === 1 ? "" : "s"}</span>
                      <span aria-hidden className="text-muted-foreground/50">·</span>
                      <span>{profileWhen(profile)}</span>
                      {profile.tags.length > 0 && (
                        <span aria-hidden className="text-muted-foreground/50">·</span>
                      )}
                      {profile.tags.slice(0, 3).map((tag) => (
                        <Badge key={tag} variant="outline">{tag}</Badge>
                      ))}
                    </div>
                  </div>
                  <div className="flex flex-wrap items-center gap-2 lg:justify-end">
                    <Button
                      type="button"
                      size="sm"
                      variant="default"
                      disabled={!thread}
                      onClick={() => openProfileThread(profile)}
                    >
                      <MessageSquare className="h-3.5 w-3.5" />
                      Open thread
                    </Button>
                    <LeadStatusControl
                      profileId={profile.id}
                      status={profile.status}
                      onChanged={onChanged}
                    />
                    {(sellerDealId || buyerDealId) && (
                      <Link
                        to="/admin"
                        className={cn(buttonVariants({ variant: "outline", size: "sm" }))}
                      >
                        <ExternalLink className="h-3.5 w-3.5" />
                        Open in admin
                      </Link>
                    )}
                  </div>
                </div>
              </div>
            );
          })}
          <PaginationBar
            page={page}
            totalPages={totalPages}
            onPageChange={(next) =>
              setPageBySection((prev) => ({ ...prev, [section.id]: next }))
            }
            label={`${section.label} pagination`}
          />
        </div>
        );
      })}
    </div>
  );
}

function LeadProfilesListPage({
  onChanged,
  profiles,
  threads,
}: {
  onChanged: (nextInbox?: SourceInboxResponse) => void | Promise<void>;
  profiles: SourceInboxProfile[];
  threads: SourceInboxThread[];
}) {
  const verifiedCount = profiles.filter(profileHasVerifier).length;
  const potentialLeadCount = profiles.filter((profile) => profile.isPotentialLead).length;

  return (
    <section
      id="leads-panel-profiles"
      role="tabpanel"
      aria-labelledby="leads-tab-profiles"
      className="space-y-3"
    >
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="min-w-0">
          <h2 className="text-lg font-semibold text-foreground">Profile list</h2>
          <p className="mt-1 max-w-3xl text-sm leading-6 text-muted-foreground">
            Active conversations stay at the top, then verified profiles queue buyer workflows or seller CMA before Admin handoff.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant="outline">{profiles.length} total</Badge>
          <Badge variant={verifiedCount ? "success" : "warning"}>{verifiedCount} verified</Badge>
          <Badge variant={potentialLeadCount ? "warning" : "outline"}>{potentialLeadCount} potential leads</Badge>
        </div>
      </div>

      <div className="overflow-hidden rounded-md border border-border bg-card">
        <LeadProfilesWorkbench
          onChanged={onChanged}
          showHeader={false}
          profiles={profiles}
          threads={threads}
        />
      </div>
    </section>
  );
}

const LeadBoardRow = memo(function LeadBoardRow({
  data,
  thread,
  profile,
  showOpenThread = true,
  variant = "card",
}: {
  data: HubData;
  thread: SourceInboxThread;
  profile?: SourceInboxProfile | null;
  showOpenThread?: boolean;
  variant?: "card" | "list";
}) {
  const drawer = useThreadDrawer();
  const navigate = useNavigate();

  const mark = async (action: "done" | "archive") => {
    const nextInbox = await api.updateSourceInboxThread(thread.sourceId, thread.threadId, action);
    data.setSourceInbox(nextInbox);
  };

  const openInChat = async () => {
    try {
      await api.updateSourceInboxThread(thread.sourceId, thread.threadId, "open");
    } catch {
      // best-effort
    }
    if (drawer) {
      drawer.openThread(thread.sourceId, thread.threadId);
      return;
    }
    const params = new URLSearchParams({
      thread: thread.threadId,
      source: thread.sourceId,
    });
    navigate(`/chat?${params.toString()}`);
  };

  const inbound = thread.direction !== "outbound";
  const heat = heatStyles(thread.heatLabel);
  const wait = inboundWaitMinutes(thread);

  const isList = variant === "list";

  const metaRow = (
    <div className="font-mono-ui mt-1.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-[0.7rem] text-muted-foreground">
      <span>{thread.sourceLabel}</span>
      <span aria-hidden>·</span>
      <span>{thread.channel}</span>
      <span aria-hidden>·</span>
      <span>{inbound ? "in" : "out"}</span>
      <span aria-hidden>·</span>
      <span>{threadWhen(thread)}</span>
      {thread.messageCount > 1 && (
        <>
          <span aria-hidden>·</span>
          <span>{thread.messageCount} msgs</span>
        </>
      )}
      {inbound && wait != null && wait >= 5 && (
        <span
          className={cn(
            "rounded-sm border border-border bg-card px-1.5 py-0.5",
            wait >= 60
              ? "text-destructive"
              : wait >= 30
                ? "text-warning"
                : "text-foreground/70",
          )}
        >
          waited {formatMinutes(wait)}
        </span>
      )}
    </div>
  );

  const headerRow = (
    <div className="flex min-w-0 flex-wrap items-center gap-2">
      <div className="min-w-0 flex-1 truncate text-sm font-semibold text-foreground">
        {thread.personName}
      </div>
      <span
        className={cn(
          "font-mono-ui inline-flex items-center rounded-sm border px-2 py-0.5 text-[0.7rem] font-semibold",
          heat.pill,
        )}
      >
        {thread.heatScore}
      </span>
    </div>
  );

  const previewText = (
    <p className="mt-1 line-clamp-2 text-xs leading-5 text-foreground/75">
      {thread.latestText}
    </p>
  );

  if (isList) {
    // Minimal lane row: dot + name + status select, whole row clicks open
    // the thread. Status select inside stops propagation so changing the
    // status doesn't navigate. Status mutates the same profile record as
    // the thread drawer — the returned source inbox keeps both surfaces in sync.
    const handleRowKey = (event: React.KeyboardEvent<HTMLDivElement>) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        void openInChat();
      }
    };
    return (
      <div
        role="button"
        tabIndex={0}
        onClick={() => void openInChat()}
        onKeyDown={handleRowKey}
        aria-label={`Open thread with ${thread.personName}`}
        className="group flex w-full cursor-pointer items-center gap-3 px-3 py-2 transition-colors hover:bg-foreground/[0.03] focus:bg-foreground/[0.04] focus:outline-none"
      >
        <span
          aria-label={heat.label}
          role="img"
          className={cn("h-2 w-2 shrink-0 rounded-full", heat.dot)}
        />
        <span className="min-w-0 flex-1 truncate text-sm text-foreground">
          {thread.personName}
        </span>
        {profile && (
          <div
            onClick={(event) => event.stopPropagation()}
            onKeyDown={(event) => event.stopPropagation()}
            className="shrink-0"
          >
              <LeadStatusControl
                profileId={profile.id}
                status={profile.status}
              onChanged={(nextInbox) => {
                if (nextInbox) data.setSourceInbox(nextInbox);
              }}
              selectClassName="w-32"
              selectButtonClassName="h-7 px-2 text-xs"
            />
          </div>
        )}
        <ChevronRight className="h-3.5 w-3.5 shrink-0 text-muted-foreground/50 transition-colors group-hover:text-foreground/60" />
      </div>
    );
  }

  return (
    <div className="group rounded-md border border-border bg-card px-3 py-3 transition-colors hover:bg-card">
      <div className="flex items-start gap-3">
        <span
          aria-label={heat.label}
          role="img"
          className={cn("mt-1 h-2.5 w-2.5 shrink-0 rounded-full", heat.dot)}
        />
        <div className="min-w-0 flex-1">
          {headerRow}
          {previewText}
          {metaRow}
        </div>
      </div>
      <div className="mt-3 flex flex-wrap justify-end gap-1.5">
        <Button
          size="sm"
          variant="ghost"
          className="h-11 px-3 sm:h-9"
          onClick={() => void mark("archive")}
          aria-label={`Remove ${thread.personName} from list`}
        >
          Remove
        </Button>
        <Button
          size="sm"
          variant="outline"
          className="h-11 px-3 sm:h-9"
          onClick={() => void mark("done")}
          aria-label={`Mark ${thread.personName} done`}
        >
          <CheckCircle2 className="h-3.5 w-3.5" />
          Done
        </Button>
        {showOpenThread && (
          <Button
            size="sm"
            className="h-11 px-3 sm:h-9"
            onClick={() => void openInChat()}
            aria-label={`Open thread with ${thread.personName}`}
          >
            <ExternalLink className="h-3.5 w-3.5" />
            Open thread
          </Button>
        )}
      </div>
    </div>
  );
});


function draftWhen(draft: SourceInboxDraft): string {
  return draft.latestAt ? isoTimeAgo(draft.latestAt) : "unsynced";
}

// Canned template fallback (server: _fallback_draft_for_thread). Not a real
// AI draft — excluded from bulk/select-all approve so the operator must
// approve each one individually (Codex interim safeguard, 2026-05-18).
function isFallbackDraft(draft: SourceInboxDraft): boolean {
  return draft.fallback === true;
}

function DraftMessagesBoard({
  data,
  drafts: draftsOverride,
  emptyMessage,
  keyboard = false,
  pageSize = 8,
  showOpenThread = true,
  title = "Draft follow-ups",
}: {
  data: HubData;
  drafts?: SourceInboxDraft[];
  emptyMessage?: string;
  keyboard?: boolean;
  pageSize?: number;
  showOpenThread?: boolean;
  title?: string;
}) {
  const drawer = useThreadDrawer();
  const navigate = useNavigate();
  const allDrafts = draftsOverride ?? data.sourceInbox?.drafts ?? [];
  const [editingId, setEditingId] = useState<string | null>(null);
  const [draftEdits, setDraftEdits] = useState<Record<string, string>>({});
  const [focusedId, setFocusedId] = useState<string | null>(null);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [density, setDensity] = useState<"compact" | "expanded">("compact");
  const [dismissedIds, setDismissedIds] = useState<Set<string>>(() => new Set());
  const [selectedIds, setSelectedIds] = useState<Set<string>>(() => new Set());
  const [bulkBusy, setBulkBusy] = useState(false);
  const [helpOpen, setHelpOpen] = useState(false);
  const [showAll, setShowAll] = useState(false);
  const rowRefs = useRef<Record<string, HTMLDivElement | null>>({});

  const drafts = allDrafts.filter((d) => !dismissedIds.has(d.id));
  const visibleDrafts = showAll ? drafts : drafts.slice(0, pageSize);
  // Fallback templates require an explicit individual approve — keep them
  // out of every bulk path (select-all + Approve/Skip N).
  const selectableVisibleDrafts = visibleDrafts.filter((d) => !isFallbackDraft(d));
  const selectedVisible = selectableVisibleDrafts.filter((d) => selectedIds.has(d.id));
  const allVisibleSelected =
    selectableVisibleDrafts.length > 0 && selectedVisible.length === selectableVisibleDrafts.length;

  const profileByThreadId = useMemo(() => {
    const map = new Map<string, SourceInboxProfile>();
    for (const profile of data.sourceInbox?.profiles ?? []) {
      for (const threadId of profile.threadIds) {
        map.set(threadId, profile);
      }
    }
    return map;
  }, [data.sourceInbox?.profiles]);

  useEffect(() => {
    const liveIds = new Set(allDrafts.map((d) => d.id));
    setDismissedIds((current) => {
      if (current.size === 0) return current;
      let changed = false;
      const next = new Set<string>();
      current.forEach((id) => {
        if (liveIds.has(id)) {
          next.add(id);
        } else {
          changed = true;
        }
      });
      return changed ? next : current;
    });
    setSelectedIds((current) => {
      if (current.size === 0) return current;
      let changed = false;
      const next = new Set<string>();
      current.forEach((id) => {
        if (liveIds.has(id)) {
          next.add(id);
        } else {
          changed = true;
        }
      });
      return changed ? next : current;
    });
  }, [allDrafts]);

  useEffect(() => {
    if (!visibleDrafts.length) {
      setFocusedId(null);
      return;
    }
    if (!focusedId || !visibleDrafts.some((draft) => draft.id === focusedId)) {
      setFocusedId(visibleDrafts[0]?.id ?? null);
    }
  }, [focusedId, visibleDrafts]);

  const updateDraft = useCallback(
    async (
      draft: SourceInboxDraft,
      action: "approve" | "edit" | "skip",
      text = draft.draftText,
    ) => {
      const isDismiss = action === "approve" || action === "skip";
      if (isDismiss) {
        setDismissedIds((current) => {
          const next = new Set(current);
          next.add(draft.id);
          return next;
        });
        setEditingId((current) => (current === draft.id ? null : current));
        setExpandedId((current) => (current === draft.id ? null : current));
        setDraftEdits((current) => {
          if (!(draft.id in current)) return current;
          const next = { ...current };
          delete next[draft.id];
          return next;
        });
      }
      try {
        const nextInbox = await api.updateSourceInboxDraft(draft.sourceId, draft.taskId, action, text);
        data.setSourceInbox(nextInbox);
        if (!isDismiss) {
          setEditingId(null);
          setDraftEdits((current) => {
            const next = { ...current };
            delete next[draft.id];
            return next;
          });
        }
      } catch (error) {
        if (isDismiss) {
          setDismissedIds((current) => {
            const next = new Set(current);
            next.delete(draft.id);
            return next;
          });
        }
        console.error("Failed to update draft", error);
        window.alert(`Failed to ${action} draft: ${error instanceof Error ? error.message : String(error)}`);
      }
    },
    [data],
  );

  const openInChat = useCallback(
    async (draft: SourceInboxDraft) => {
      try {
        await api.updateSourceInboxDraft(draft.sourceId, draft.taskId, "open", draft.draftText);
      } catch {
        // best-effort
      }
      if (drawer) {
        drawer.openThread(draft.sourceId, draft.threadId);
        return;
      }
      const params = new URLSearchParams({
        thread: draft.threadId,
        source: draft.sourceId,
        draft: draft.taskId,
      });
      navigate(`/chat?${params.toString()}`);
    },
    [drawer, navigate],
  );

  useEffect(() => {
    if (!keyboard) return;
    const handler = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      const tag = target?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || target?.isContentEditable) return;
      if (event.metaKey || event.ctrlKey || event.altKey) return;
      if (!visibleDrafts.length) return;
      const currentIndex = Math.max(
        0,
        visibleDrafts.findIndex((draft) => draft.id === focusedId),
      );
      const focused = visibleDrafts[currentIndex];

      const move = (delta: number) => {
        const next = visibleDrafts[(currentIndex + delta + visibleDrafts.length) % visibleDrafts.length];
        if (next) {
          setFocusedId(next.id);
          requestAnimationFrame(() => {
            rowRefs.current[next.id]?.scrollIntoView({ behavior: "smooth", block: "nearest" });
          });
        }
      };

      switch (event.key) {
        case "ArrowDown":
        case "j":
          event.preventDefault();
          move(1);
          break;
        case "ArrowUp":
        case "k":
          event.preventDefault();
          move(-1);
          break;
        case "a":
        case "A":
          if (focused) {
            event.preventDefault();
            void updateDraft(focused, "approve");
          }
          break;
        case "s":
        case "S":
          if (focused) {
            event.preventDefault();
            void updateDraft(focused, "skip");
          }
          break;
        case "e":
        case "E":
          if (focused) {
            event.preventDefault();
            setEditingId(focused.id);
            setDraftEdits((current) => ({ ...current, [focused.id]: focused.draftText }));
          }
          break;
        case "o":
        case "O":
          if (focused && showOpenThread) {
            event.preventDefault();
            void openInChat(focused);
          }
          break;
        default:
          break;
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [focusedId, keyboard, openInChat, showOpenThread, updateDraft, visibleDrafts]);

  const toggleSelected = useCallback((id: string) => {
    setSelectedIds((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  const toggleSelectAll = useCallback(() => {
    setSelectedIds((current) => {
      if (
        selectableVisibleDrafts.length > 0 &&
        selectableVisibleDrafts.every((d) => current.has(d.id))
      ) {
        const next = new Set(current);
        selectableVisibleDrafts.forEach((d) => next.delete(d.id));
        return next;
      }
      const next = new Set(current);
      selectableVisibleDrafts.forEach((d) => next.add(d.id));
      return next;
    });
  }, [selectableVisibleDrafts]);

  const runBulk = useCallback(
    async (action: "approve" | "skip") => {
      if (selectedVisible.length === 0 || bulkBusy) return;
      setBulkBusy(true);
      try {
        for (const draft of selectedVisible) {
          await updateDraft(draft, action);
        }
        setSelectedIds(new Set());
      } finally {
        setBulkBusy(false);
      }
    },
    [bulkBusy, selectedVisible, updateDraft],
  );

  const fallbackEmpty =
    emptyMessage ??
    "No draft replies are waiting. Composio social imports, CRM follow-ups, and outreach tasks can feed approval-gated messages here.";

  return (
    <Card>
      <CardHeader>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <CardTitle>{title}</CardTitle>
              <span className="inline-flex items-center gap-1.5 text-xs text-muted-foreground">
                <span className={cn("h-1.5 w-1.5 rounded-full", drafts.length ? "bg-warning" : "bg-muted-foreground/40")} />
                {drafts.length} waiting
              </span>
            </div>
            <p className="mt-1 text-xs leading-5 text-muted-foreground">
              Approval-gated. Nothing sends until you click Approve.
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {keyboard && drafts.length > 0 && (
              <div className="relative">
                <button
                  type="button"
                  onClick={() => setHelpOpen((v) => !v)}
                  aria-expanded={helpOpen}
                  aria-haspopup="dialog"
                  aria-label="Keyboard shortcuts"
                  className="font-mono-ui inline-flex h-11 items-center gap-1.5 rounded-sm border border-border bg-card px-3 text-[0.72rem] text-muted-foreground transition hover:bg-card sm:h-9"
                >
                  <HelpCircle className="h-3.5 w-3.5" />
                  Shortcuts
                </button>
                {helpOpen && (
                  <div
                    role="dialog"
                    className="absolute right-0 top-[calc(100%+6px)] z-30 w-64 rounded-md border border-border bg-card p-3 shadow-lg"
                  >
                    <div className="font-mono-ui mb-2 text-[0.66rem] font-semibold uppercase tracking-[0.14em] text-muted-foreground">
                      Keyboard
                    </div>
                    <ul className="space-y-1.5 text-xs text-foreground">
                      {[
                        ["↑ ↓ / J K", "navigate"],
                        ["A", "approve"],
                        ["E", "edit"],
                        ["S", "skip"],
                        ...(showOpenThread ? [["O", "open thread"] as const] : []),
                      ].map(([key, label]) => (
                        <li key={key} className="flex items-center justify-between gap-2">
                          <kbd
                            aria-keyshortcuts={key}
                            className="font-mono-ui rounded border border-border bg-card px-1.5 py-0.5 text-[0.7rem]"
                          >
                            {key}
                          </kbd>
                          <span className="text-muted-foreground">{label}</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            )}
            <div
              className="font-mono-ui inline-flex h-11 overflow-hidden rounded-sm border border-border text-[0.7rem] sm:h-9"
              role="group"
              aria-label="Layout density"
            >
              <button
                type="button"
                onClick={() => setDensity("compact")}
                aria-pressed={density === "compact"}
                className={cn(
                  "px-3 transition",
                  density === "compact"
                    ? "bg-muted text-foreground"
                    : "text-muted-foreground hover:bg-card",
                )}
              >
                Compact
              </button>
              <button
                type="button"
                onClick={() => setDensity("expanded")}
                aria-pressed={density === "expanded"}
                className={cn(
                  "px-3 transition",
                  density === "expanded"
                    ? "bg-muted text-foreground"
                    : "text-muted-foreground hover:bg-card",
                )}
              >
                Expanded
              </button>
            </div>
          </div>
        </div>
        {visibleDrafts.length > 0 && (
          <div className="font-mono-ui mt-3 flex flex-wrap items-center gap-3 border-t border-border pt-3 text-xs text-muted-foreground">
            <button
              type="button"
              onClick={toggleSelectAll}
              aria-pressed={allVisibleSelected}
              className="inline-flex h-11 items-center gap-2 rounded-sm border border-border bg-card px-3 hover:bg-card sm:h-9"
            >
              {allVisibleSelected ? (
                <CheckSquare className="h-3.5 w-3.5 text-primary" />
              ) : (
                <SquareIcon className="h-3.5 w-3.5 text-muted-foreground/80" />
              )}
              {allVisibleSelected ? "Clear" : "Select all"}
            </button>
            <span className="text-muted-foreground">
              {selectedVisible.length} selected · {visibleDrafts.length} shown
              {drafts.length > visibleDrafts.length ? ` of ${drafts.length}` : ""}
            </span>
            {drafts.length > pageSize && (
              <button
                type="button"
                onClick={() => setShowAll((v) => !v)}
                className="ml-auto inline-flex h-9 items-center gap-1.5 rounded-sm border border-border bg-card px-3 text-foreground hover:bg-card"
              >
                {showAll ? `Show first ${pageSize}` : `Show all ${drafts.length}`}
              </button>
            )}
          </div>
        )}
      </CardHeader>
      <CardContent className="relative divide-y divide-border">
        {visibleDrafts.length ? (
          visibleDrafts.map((draft) => {
            const isEditing = editingId === draft.id;
            const draftText = draftEdits[draft.id] ?? draft.draftText;
            const isFocused = keyboard && focusedId === draft.id;
            const isExpanded = density === "expanded" || expandedId === draft.id || isEditing;
            const isSelected = selectedIds.has(draft.id);
            const heat = heatStyles(String(draft.leadLabel ?? ""));
            const identity = parseIdentity(draft.personName);
            const provenance = provenanceLine(draft.sourceLabel, draft.channel);
            const draftProfile = profileByThreadId.get(draft.threadId);
            return (
              <div
                key={draft.id}
                ref={(node) => {
                  rowRefs.current[draft.id] = node;
                }}
                onMouseEnter={() => keyboard && setFocusedId(draft.id)}
                className={cn(
                  "group/draft relative py-3 transition-colors first:pt-0 last:pb-0",
                  isFocused && "bg-primary/[0.06]",
                  isSelected && !isFocused && "bg-primary/[0.04]",
                  !isFocused && !isSelected && "hover:bg-foreground/[0.02]",
                )}
              >
                <div className="flex w-full min-w-0 items-start gap-2">
                  <button
                    type="button"
                    onClick={(event) => {
                      event.stopPropagation();
                      toggleSelected(draft.id);
                    }}
                    aria-pressed={isSelected}
                    aria-label={isSelected ? `Deselect draft for ${draft.personName}` : `Select draft for ${draft.personName}`}
                    className="flex h-11 w-11 shrink-0 items-center justify-center rounded-md border border-border bg-card text-muted-foreground transition hover:border-ring hover:text-primary sm:mt-0.5 sm:h-6 sm:w-6"
                  >
                    {isSelected ? (
                      <CheckSquare className="h-3.5 w-3.5 text-primary" />
                    ) : (
                      <SquareIcon className="h-3.5 w-3.5" />
                    )}
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      if (isEditing) return;
                      setExpandedId((current) => (current === draft.id ? null : draft.id));
                    }}
                    className="flex min-w-0 flex-1 items-start gap-2.5 text-left"
                    aria-expanded={isExpanded}
                  >
                    <div className="min-w-0 flex-1">
                      <div className="flex min-w-0 items-baseline gap-2">
                        <div className="min-w-0 flex-1 truncate text-sm font-semibold leading-5 text-foreground">
                          {identity.name}
                        </div>
                        <span className="font-mono-ui shrink-0 text-[0.66rem] tabular-nums text-muted-foreground/80">
                          {draftWhen(draft)}
                        </span>
                      </div>
                      <div className="font-mono-ui mt-0.5 flex min-w-0 flex-wrap items-center gap-x-1.5 gap-y-0.5 text-[0.66rem] uppercase tracking-[0.08em] text-muted-foreground/75">
                        {identity.email && (
                          <span className="truncate normal-case tracking-normal text-muted-foreground/70">
                            {identity.email}
                          </span>
                        )}
                        {identity.email && <span aria-hidden className="opacity-50">·</span>}
                        <span className="truncate">{provenance}</span>
                        {draft.leadLabel && (
                          <>
                            <span aria-hidden className="opacity-50">·</span>
                            <span
                              className={cn(
                                "inline-flex items-center gap-1 normal-case tracking-normal",
                                heat.pill,
                              )}
                              title={draft.scoreReason ?? undefined}
                            >
                              {String(draft.leadLabel)}
                              {typeof draft.score === "number" ? ` ${draft.score}` : ""}
                            </span>
                          </>
                        )}
                        {isFallbackDraft(draft) ? (
                          <>
                            <span aria-hidden className="opacity-50">·</span>
                            <span
                              className="inline-flex items-center rounded-md border border-warning/45 bg-warning/12 px-1.5 py-0.5 text-warning"
                              title="Canned template, not an AI-generated draft. Review before sending — excluded from bulk approve."
                            >
                              Template — not AI
                            </span>
                          </>
                        ) : (
                          draft.templateName ? (
                            <>
                              <span aria-hidden className="opacity-50">·</span>
                              <span className="truncate text-muted-foreground/70">
                                template: {draft.templateName}
                              </span>
                            </>
                          ) : draft.generated && (
                            <>
                              <span aria-hidden className="opacity-50">·</span>
                              <span className="text-muted-foreground/70">suggested</span>
                            </>
                          )
                        )}
                      </div>
                      <p
                        className={cn(
                          "mt-1 text-[0.82rem] leading-5 text-foreground/90",
                          !isExpanded && "line-clamp-2",
                        )}
                      >
                        {draft.draftText}
                      </p>
                    </div>
                  </button>
                  {!isEditing && (
                    <div className="flex shrink-0 items-center gap-1 opacity-80 transition group-hover:opacity-100">
                      <button
                        type="button"
                        onClick={(event) => {
                          event.stopPropagation();
                          void updateDraft(draft, "skip");
                        }}
                        title="Skip"
                        aria-label={`Skip draft for ${draft.personName}`}
                        className="flex h-9 w-9 items-center justify-center rounded-md text-muted-foreground/50 opacity-0 transition group-hover/draft:opacity-100 hover:text-destructive"
                      >
                        <XCircle className="h-4 w-4" />
                      </button>
                      <button
                        type="button"
                        onClick={(event) => {
                          event.stopPropagation();
                          void updateDraft(draft, "approve", draft.draftText);
                        }}
                        title="Approve"
                        aria-label={`Approve draft for ${draft.personName}`}
                        className="flex h-9 w-9 items-center justify-center rounded-md text-muted-foreground/50 opacity-0 transition group-hover/draft:opacity-100 hover:text-primary"
                      >
                        <Send className="h-4 w-4" />
                      </button>
                    </div>
                  )}
                </div>
                {isExpanded && (
                  <div className="mt-2 space-y-2 border-t border-border/55 pt-2">
                    {draft.context && !isEditing && (
                      <p className="text-[0.72rem] leading-5 text-muted-foreground">
                        {draft.context}
                      </p>
                    )}
                    {isEditing && (
                      <textarea
                        value={draftText}
                        onChange={(event) =>
                          setDraftEdits((current) => ({ ...current, [draft.id]: event.target.value }))
                        }
                        className="min-h-24 w-full resize-y rounded-md border border-border bg-background px-2.5 py-2 text-sm leading-6 text-foreground outline-none transition focus:border-ring focus-visible:ring-1 focus-visible:ring-ring"
                      />
                    )}
                    <div className="flex flex-wrap items-center justify-end gap-1.5">
                      {!isEditing && draftProfile && (
                        <LeadStatusControl
                          profileId={draftProfile.id}
                          status={draftProfile.status}
                          onChanged={(nextInbox) => {
                            if (nextInbox) data.setSourceInbox(nextInbox);
                          }}
                        />
                      )}
                      {!isEditing && showOpenThread && (
                        <Button size="sm" variant="ghost" className="h-11 px-3 sm:h-9" onClick={() => void openInChat(draft)}>
                          <ExternalLink className="h-3.5 w-3.5" />
                          Thread
                        </Button>
                      )}
                      {!isEditing && (
                        <Button size="sm" variant="ghost" className="h-11 px-3 sm:h-9" onClick={() => void updateDraft(draft, "skip")}>
                          <XCircle className="h-3.5 w-3.5" />
                          Skip
                        </Button>
                      )}
                      {isEditing ? (
                        <>
                          <Button size="sm" variant="ghost" className="h-11 px-3 sm:h-9" onClick={() => setEditingId(null)}>
                            Cancel
                          </Button>
                          <Button size="sm" variant="outline" className="h-11 px-3 sm:h-9" onClick={() => void updateDraft(draft, "edit", draftText)}>
                            Save
                          </Button>
                        </>
                      ) : (
                        <Button
                          size="sm"
                          variant="outline"
                          className="h-11 px-3 sm:h-9"
                          onClick={() => {
                            setEditingId(draft.id);
                            setDraftEdits((current) => ({ ...current, [draft.id]: draft.draftText }));
                          }}
                        >
                          <PencilLine className="h-3.5 w-3.5" />
                          Edit
                        </Button>
                      )}
                      <Button
                        size="sm"
                        className="h-11 px-3 sm:h-9"
                        onClick={() => void updateDraft(draft, "approve", isEditing ? draftText : draft.draftText)}
                      >
                        <Send className="h-3.5 w-3.5" />
                        Approve
                      </Button>
                    </div>
                  </div>
                )}
              </div>
            );
          })
        ) : (
          <p className="px-4 py-3 text-xs text-muted-foreground/80">
            Inbox empty. {fallbackEmpty}
          </p>
        )}
        {selectedVisible.length > 0 && (
          <div
            className="sticky bottom-3 left-0 right-0 z-20 mx-auto mt-3 flex w-fit max-w-full items-center gap-2 rounded-sm border border-border bg-card px-3 py-2 "
            role="region"
            aria-label="Bulk actions"
          >
            <span className="font-mono-ui text-[0.72rem] text-muted-foreground">
              {selectedVisible.length} selected
            </span>
            <Button
              size="sm"
              variant="ghost"
              className="h-11 px-3 sm:h-9"
              disabled={bulkBusy}
              onClick={() => setSelectedIds(new Set())}
            >
              Clear
            </Button>
            <Button
              size="sm"
              variant="outline"
              className="h-11 px-3 sm:h-9"
              disabled={bulkBusy}
              onClick={() => void runBulk("skip")}
            >
              <XCircle className="h-3.5 w-3.5" />
              Skip {selectedVisible.length}
            </Button>
            <Button
              size="sm"
              className="h-11 px-3 sm:h-9"
              disabled={bulkBusy}
              onClick={() => void runBulk("approve")}
            >
              {bulkBusy ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <Send className="h-3.5 w-3.5" />
              )}
              Approve {selectedVisible.length}
            </Button>
          </div>
        )}
      </CardContent>
    </Card>
  );
}


const LANE_LIST_MAX = 10;
const LANE_LIST_SCROLL_CLASS =
  "max-h-[26rem] divide-y divide-border overflow-y-auto rounded-md border border-border/60";

function useProfileLookups(data: HubData) {
  return useMemo(() => {
    // Profile.threadIds is keyed by the composite "{sourceId}:{threadId}"
    // string (matching SourceInboxThread.id), so we index by that AND by
    // the bare thread tail so callers can look up using either form
    // (threads have both fields; drafts only have the bare threadId).
    const byThread = new Map<string, SourceInboxProfile>();
    const byContact = new Map<string, SourceInboxProfile>();
    const byEmail = new Map<string, SourceInboxProfile>();
    const byPhone = new Map<string, SourceInboxProfile>();
    for (const profile of data.sourceInbox?.profiles ?? []) {
      for (const contactId of profile.contactIds ?? []) {
        if (contactId) byContact.set(contactId, profile);
      }
      for (const threadKey of profile.threadIds) {
        if (!threadKey) continue;
        byThread.set(threadKey, profile);
        const colonAt = threadKey.indexOf(":");
        if (colonAt >= 0) {
          const tail = threadKey.slice(colonAt + 1);
          if (tail) byThread.set(tail, profile);
        }
      }
      for (const email of profile.emails ?? []) {
        const key = email.trim().toLowerCase();
        if (key) byEmail.set(key, profile);
      }
      for (const phone of profile.phones ?? []) {
        const key = phone.trim();
        if (key) byPhone.set(key, profile);
      }
    }
    return { byThread, byContact, byEmail, byPhone };
  }, [data.sourceInbox?.profiles]);
}

function HotLeadsList({
  data,
  threads,
}: {
  data: HubData;
  threads: SourceInboxThread[];
}) {
  const { byThread } = useProfileLookups(data);
  const hot = leadSectionThreads(
    threads,
    data.sourceInbox,
    "hot",
    leadThreadBuckets(threads).hot,
  ).slice(0, LANE_LIST_MAX);
  if (!hot.length) {
    return (
      <p className="px-1 py-1 text-xs text-muted-foreground/80">
        No hot leads — recent replies and repeat opens land here.
      </p>
    );
  }
  return (
    <div className={LANE_LIST_SCROLL_CLASS}>
      {hot.map((thread) => (
        <LeadBoardRow
          key={thread.id}
          data={data}
          thread={thread}
          profile={byThread.get(thread.threadId) ?? null}
          showOpenThread
          variant="list"
        />
      ))}
    </div>
  );
}


type LeadSectionCounts = {
  hot: number;
  followUp: number;
  buyerSearch: number;
  skipped: number;
};

function LeadPipelineBoard({
  buyers,
  data,
  sectionCounts,
  skippedDrafts,
  threads,
}: {
  buyers: BuyerWatchlistEntry[];
  data: HubData;
  sectionCounts: LeadSectionCounts;
  skippedDrafts: SourceInboxDraft[];
  threads: SourceInboxThread[];
}) {
  const lanes = [
    { value: "hot", label: "Hot leads", count: sectionCounts.hot },
    { value: "follow", label: "Follow-ups", count: sectionCounts.followUp },
    { value: "buyers", label: "Buyer searches", count: sectionCounts.buyerSearch },
    { value: "skipped", label: "Recently skipped", count: sectionCounts.skipped },
  ];

  return (
    <Tabs defaultValue="hot">
      {(active, setActive) => (
        <>
          <TabsList>
            {lanes.map((lane) => (
              <TabsTrigger
                key={lane.value}
                active={active === lane.value}
                value={lane.value}
                onClick={() => setActive(lane.value)}
              >
                {lane.label}
                <span className="ml-1.5 font-mono-ui text-[0.7rem] text-muted-foreground/80 tabular-nums">
                  {lane.count}
                </span>
              </TabsTrigger>
            ))}
          </TabsList>
          <div className="min-w-0">
            {active === "hot" && <HotLeadsList data={data} threads={threads} />}
            {active === "follow" && <FollowUpThreadsList data={data} threads={threads} />}
            {active === "buyers" && (
              <PrivateSearchBuyersList
                buyers={buyers}
                data={data}
                totalCount={sectionCounts.buyerSearch}
              />
            )}
            {active === "skipped" && <SkippedDraftsList data={data} drafts={skippedDrafts} threads={threads} />}
          </div>
        </>
      )}
    </Tabs>
  );
}

function FollowUpThreadsList({
  data,
  threads,
}: {
  data: HubData;
  threads: SourceInboxThread[];
}) {
  const { byThread } = useProfileLookups(data);
  const followUps = leadSectionThreads(
    threads,
    data.sourceInbox,
    "follow_up",
    leadThreadBuckets(threads).followUp,
  ).slice(0, LANE_LIST_MAX);
  if (!followUps.length) {
    return (
      <p className="px-1 py-1 text-xs text-muted-foreground/80">
        Inbox zero — replies across email, SMS, Messenger, IG, WhatsApp will surface here.
      </p>
    );
  }
  return (
    <div className={LANE_LIST_SCROLL_CLASS}>
      {followUps.map((thread) => (
        <LeadBoardRow
          key={thread.id}
          data={data}
          thread={thread}
          profile={byThread.get(thread.threadId) ?? null}
          showOpenThread
          variant="list"
        />
      ))}
    </div>
  );
}

const BUYER_PAGE_SIZE = 20;

function PrivateSearchBuyersList({
  buyers,
  data,
  totalCount,
}: {
  buyers: BuyerWatchlistEntry[];
  data: HubData;
  totalCount: number;
}) {
  const navigate = useNavigate();
  const { byContact, byEmail, byPhone } = useProfileLookups(data);
  const [page, setPage] = useState(1);
  const [running, setRunning] = useState(false);

  const runSearch = async () => {
    setRunning(true);
    try {
      const resp = await api.getSourceConnectorPrompt("xposure-pcs");
      const prompt = (resp.prompt || "").trim();
      if (!prompt) return;
      const seed = String(Date.now());
      const seedText = `Run source connector: MLS Buyer Searches (xposure-pcs)\n\n${prompt}`;
      try {
        window.sessionStorage.setItem(`elevate:chat-seed:${seed}`, seedText);
      } catch {
        // sessionStorage disabled — the Chat page still opens, and Settings can copy the prompt.
      }
      navigate(`/chat?new=${seed}&seed=${seed}`);
    } finally {
      setRunning(false);
    }
  };

  const lookupProfile = (buyer: BuyerWatchlistEntry): SourceInboxProfile | null => {
    const contactId = (buyer.contactId ?? "").trim();
    if (contactId && byContact.has(contactId)) return byContact.get(contactId) ?? null;
    const email = (buyer.email ?? "").trim().toLowerCase();
    if (email && byEmail.has(email)) return byEmail.get(email) ?? null;
    const phone = (buyer.phone ?? "").trim();
    if (phone && byPhone.has(phone)) return byPhone.get(phone) ?? null;
    return null;
  };

  const totalPages = Math.max(1, Math.ceil(buyers.length / BUYER_PAGE_SIZE));
  const safePage = Math.min(page, totalPages);
  const start = (safePage - 1) * BUYER_PAGE_SIZE;
  const visible = buyers.slice(start, start + BUYER_PAGE_SIZE);
  const displayedTotal = Math.max(totalCount, buyers.length);

  const runButton = (
    <Button
      variant="outline"
      size="sm"
      onClick={() => void runSearch()}
      disabled={running}
      title="Run the PCS pipeline: scrape Xposure, score, refresh this list"
    >
      {running ? (
        <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
      ) : (
        <Zap className="mr-1.5 h-3.5 w-3.5" />
      )}
      Open run session
    </Button>
  );

  if (!buyers.length) {
    return (
      <div className="flex flex-col gap-3 px-1 py-1">
        <p className="text-xs text-muted-foreground/80">
          No tagged buyers yet. Buyers connected by the{" "}
          <code className="font-mono-ui text-[0.7rem]">xposure-pcs</code> tag in
          your CRM surface here. Run the search to scrape Xposure and score them.
        </p>
        <div>{runButton}</div>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center justify-between gap-2 px-1">
        <span className="font-mono-ui text-[0.7rem] uppercase tracking-[0.06em] text-muted-foreground/80">
          {buyers.length === displayedTotal
            ? `${buyers.length} tagged buyer${buyers.length === 1 ? "" : "s"}`
            : `${buyers.length} of ${displayedTotal} tagged buyers`}
        </span>
        {runButton}
      </div>
      <div className={LANE_LIST_SCROLL_CLASS}>
        {visible.map((buyer) => (
            <BuyerWatchlistRow
              key={buyer.id}
              buyer={buyer}
              profile={lookupProfile(buyer)}
              onChanged={(nextInbox) => {
                if (nextInbox) data.setSourceInbox(nextInbox);
              }}
            />
        ))}
      </div>
      {totalPages > 1 && (
        <PaginationBar
          page={safePage}
          totalPages={totalPages}
          onPageChange={setPage}
          label="buyer searches"
        />
      )}
    </div>
  );
}

function BuyerWatchlistRow({
  buyer,
  profile,
  onChanged,
}: {
  buyer: BuyerWatchlistEntry;
  profile: SourceInboxProfile | null;
  onChanged: (nextInbox?: SourceInboxResponse) => void | Promise<void>;
}) {
  const drawer = useThreadDrawer();
  const [expanded, setExpanded] = useState(false);
  const tier = (buyer.tier ?? "").toUpperCase();
  const dot =
    tier === "HOT"
      ? "bg-destructive"
      : tier === "WARM"
        ? "bg-warning"
        : "bg-foreground/40";
  const name = buyer.name || "Unnamed buyer";

  const matchedThreadId = profile?.threadIds?.[0] ?? null;
  const matchedSourceId = profile?.sourceIds?.[0] ?? null;
  const canOpenThread = Boolean(drawer && profile && matchedThreadId && matchedSourceId);

  const subtitleParts: string[] = [];
  if (buyer.sourceLabel) subtitleParts.push(buyer.sourceLabel);
  if (buyer.lastActivity) subtitleParts.push(`active ${isoTimeAgo(buyer.lastActivity)}`);
  else if (buyer.dateEntered) subtitleParts.push(`added ${isoTimeAgo(buyer.dateEntered)}`);
  if (typeof buyer.score === "number") {
    subtitleParts.push(tier && tier !== "PCS" ? `${buyer.score} · ${tier}` : `score ${buyer.score}`);
  } else if (tier && tier !== "PCS") {
    subtitleParts.push(tier);
  }
  if (buyer.searches?.length) {
    subtitleParts.push(
      `${buyer.searches.length} saved search${buyer.searches.length === 1 ? "" : "es"}`,
    );
  }
  if (buyer.matchingListings?.length) {
    subtitleParts.push(
      `${buyer.matchingListings.length} match${buyer.matchingListings.length === 1 ? "" : "es"}`,
    );
  }

  const handleRowClick = () => {
    if (canOpenThread && drawer) {
      drawer.openThread(matchedSourceId!, matchedThreadId!);
      return;
    }
    setExpanded((v) => !v);
  };

  return (
    <div className="border-b border-border last:border-b-0">
      <button
        type="button"
        onClick={handleRowClick}
        className="group flex w-full items-start gap-3 px-3 py-2 text-left transition-colors hover:bg-foreground/[0.03] focus:bg-foreground/[0.04] focus:outline-none"
        aria-expanded={canOpenThread ? undefined : expanded}
        aria-label={canOpenThread ? `Open inbox for ${name}` : `Show activity for ${name}`}
      >
        <span
          aria-hidden="true"
          className={cn("mt-1.5 h-2 w-2 shrink-0 rounded-full", dot)}
        />
        <div className="min-w-0 flex-1">
          <div className="truncate text-sm text-foreground">{name}</div>
          {subtitleParts.length > 0 && (
            <div className="mt-0.5 truncate text-[0.72rem] text-muted-foreground/80">
              {subtitleParts.join(" · ")}
            </div>
          )}
        </div>
        {profile && (
          <div
            onClick={(event) => {
              event.preventDefault();
              event.stopPropagation();
            }}
            onKeyDown={(event) => event.stopPropagation()}
            className="shrink-0"
          >
            <LeadStatusControl
              profileId={profile.id}
              status={profile.status}
              onChanged={onChanged}
              selectClassName="h-7 w-32 px-2 text-xs"
            />
          </div>
        )}
        {canOpenThread ? (
          <ChevronRight className="mt-1 h-3.5 w-3.5 shrink-0 text-muted-foreground/50 transition-colors group-hover:text-foreground/60" />
        ) : (
          <ChevronDown
            className={cn(
              "mt-1 h-3.5 w-3.5 shrink-0 text-muted-foreground/50 transition-transform group-hover:text-foreground/60",
              expanded && "rotate-180",
            )}
          />
        )}
      </button>

      {!canOpenThread && expanded && (
        <div className="space-y-2 border-t border-border/60 bg-foreground/[0.015] px-6 py-3">
          {(buyer.email || buyer.phone) && (
            <div className="flex flex-wrap gap-x-4 gap-y-1 text-[0.72rem] text-muted-foreground">
              {buyer.email && <span className="font-mono-ui">{buyer.email}</span>}
              {buyer.phone && <span className="font-mono-ui">{buyer.phone}</span>}
            </div>
          )}
          {buyer.searches?.length ? (
            <div>
              <div className="font-mono-ui text-[0.66rem] uppercase tracking-[0.08em] text-muted-foreground/70">
                Saved searches
              </div>
              <ul className="mt-1 space-y-0.5 text-[0.78rem] text-foreground/85">
                {buyer.searches.map((s, i) => (
                  <li key={i} className="truncate">· {s}</li>
                ))}
              </ul>
            </div>
          ) : null}
          {buyer.matchingListings?.length ? (
            <div>
              <div className="font-mono-ui text-[0.66rem] uppercase tracking-[0.08em] text-muted-foreground/70">
                Matching listings
              </div>
              <ul className="mt-1 space-y-0.5 text-[0.78rem] text-foreground/85">
                {buyer.matchingListings.slice(0, 8).map((l, i) => (
                  <li key={i} className="truncate">· {l}</li>
                ))}
                {buyer.matchingListings.length > 8 && (
                  <li className="text-muted-foreground/70">
                    + {buyer.matchingListings.length - 8} more
                  </li>
                )}
              </ul>
            </div>
          ) : null}
          {buyer.tags?.length ? (
            <div className="flex flex-wrap gap-1">
              {buyer.tags.map((tag) => (
                <span
                  key={tag}
                  className="rounded-sm border border-border bg-card px-1.5 py-0.5 font-mono-ui text-[0.66rem] text-muted-foreground"
                >
                  {tag}
                </span>
              ))}
            </div>
          ) : null}
          {!buyer.searches?.length &&
            !buyer.matchingListings?.length &&
            !buyer.profileUrl && (
              <p className="text-[0.72rem] text-muted-foreground/70">
                No saved-search activity scraped yet. Run the PCS pipeline to pull this
                buyer{"'"}s Xposure activity, scoring, and matched listings.
              </p>
            )}
          {buyer.profileUrl && (
            <a
              href={buyer.profileUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1 text-[0.72rem] text-primary hover:underline"
            >
              <ExternalLink className="h-3 w-3" />
              Open MLS profile
            </a>
          )}
          {buyer.scrapedAt && (
            <div className="font-mono-ui text-[0.66rem] uppercase tracking-[0.08em] text-muted-foreground/60">
              Scraped {isoTimeAgo(buyer.scrapedAt)}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function SkippedDraftsList({
  data,
  drafts: draftsOverride,
  threads,
}: {
  data: HubData;
  drafts?: SourceInboxDraft[];
  threads?: SourceInboxThread[];
}) {
  const drawer = useThreadDrawer();
  const navigate = useNavigate();
  const { byThread } = useProfileLookups(data);
  const allSkipped = draftsOverride ?? data.sourceInbox?.skippedDrafts ?? [];
  const [restoringId, setRestoringId] = useState<string | null>(null);

  // Build thread lookup by (sourceId, threadId) AND bare threadId so we can
  // borrow Hot Leads-style heat/name/status from the real thread record.
  const threadByKey = useMemo(() => {
    const map = new Map<string, SourceInboxThread>();
    for (const t of threads ?? []) {
      if (t.sourceId && t.threadId) map.set(`${t.sourceId}:${t.threadId}`, t);
      if (t.threadId) map.set(t.threadId, t);
      if (t.id) map.set(t.id, t);
    }
    return map;
  }, [threads]);

  // Dedupe drafts by thread (one row per person, newest first).
  const skipped = useMemo(() => {
    const seen = new Set<string>();
    const out: SourceInboxDraft[] = [];
    for (const d of allSkipped) {
      const key = d.threadId ? `${d.sourceId}:${d.threadId}` : d.id;
      if (seen.has(key)) continue;
      seen.add(key);
      out.push(d);
      if (out.length >= LANE_LIST_MAX) break;
    }
    return out;
  }, [allSkipped]);

  if (!skipped.length) {
    return (
      <p className="px-1 py-1 text-xs text-muted-foreground/80">
        Nothing skipped — drafts auto-clear after 3 days.
      </p>
    );
  }

  const resolveName = (draft: SourceInboxDraft, thread: SourceInboxThread | undefined) => {
    if (thread?.personName) return thread.personName;
    const raw = parseIdentity(draft.personName).name;
    // Filter out channel/source label leaking through as the display name.
    const blacklist = new Set(
      [draft.channel, draft.sourceLabel, "Apple Messages", "Email", "SMS", "Messenger", "Instagram", "WhatsApp"]
        .filter(Boolean)
        .map((s) => String(s).toLowerCase()),
    );
    if (!raw || blacklist.has(raw.toLowerCase())) return "(Unknown contact)";
    return raw;
  };

  const openThread = (draft: SourceInboxDraft) => {
    if (drawer && draft.threadId) {
      drawer.openThread(draft.sourceId, draft.threadId, { skippedDraft: draft });
      return;
    }
    const params = new URLSearchParams({
      thread: draft.threadId,
      source: draft.sourceId,
    });
    navigate(`/chat?${params.toString()}`);
  };

  const restoreDraft = async (draft: SourceInboxDraft) => {
    if (restoringId) return;
    setRestoringId(draft.id);
    try {
      const nextInbox = await api.updateSourceInboxDraft(draft.sourceId, draft.taskId, "restore", draft.draftText);
      data.setSourceInbox(nextInbox);
    } catch (error) {
      console.error("Failed to restore skipped draft", error);
      window.alert(`Failed to restore draft: ${error instanceof Error ? error.message : String(error)}`);
    } finally {
      setRestoringId(null);
    }
  };

  return (
    <div className={LANE_LIST_SCROLL_CLASS}>
      {skipped.map((draft) => {
        const thread = (draft.sourceId && draft.threadId
          ? threadByKey.get(`${draft.sourceId}:${draft.threadId}`)
          : undefined) ?? (draft.threadId ? threadByKey.get(draft.threadId) : undefined);
        const displayName = resolveName(draft, thread);
        const profile =
          (draft.sourceId && draft.threadId
            ? byThread.get(`${draft.sourceId}:${draft.threadId}`)
            : null) ??
          (draft.threadId ? byThread.get(draft.threadId) ?? null : null);
        const heat = thread ? heatStyles(thread.heatLabel) : null;
        const handleKey = (event: React.KeyboardEvent<HTMLDivElement>) => {
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            openThread(draft);
          }
        };
        return (
          <div
            key={draft.id}
            role="button"
            tabIndex={0}
            onClick={() => openThread(draft)}
            onKeyDown={handleKey}
            aria-label={`Open skipped draft for ${displayName}`}
            className="group flex w-full cursor-pointer items-center gap-3 px-3 py-2 transition-colors hover:bg-foreground/[0.03] focus:bg-foreground/[0.04] focus:outline-none"
          >
            <span
              aria-label={heat?.label ?? "skipped"}
              role="img"
              className={cn("h-2 w-2 shrink-0 rounded-full", heat?.dot ?? "bg-muted-foreground/50")}
            />
            <span className="min-w-0 flex-1 truncate text-sm text-foreground">
              {displayName}
            </span>
            {profile && (
              <div
                onClick={(event) => event.stopPropagation()}
                onKeyDown={(event) => event.stopPropagation()}
                className="shrink-0"
              >
                <LeadStatusControl
                  profileId={profile.id}
                  status={profile.status}
                  onChanged={(nextInbox) => {
                    if (nextInbox) data.setSourceInbox(nextInbox);
                  }}
                  selectClassName="w-32"
                  selectButtonClassName="h-7 px-2 text-xs"
                />
              </div>
            )}
            <button
              type="button"
              onClick={(event) => {
                event.stopPropagation();
                void restoreDraft(draft);
              }}
              disabled={restoringId !== null}
              title="Restore to approval queue"
              aria-label={`Restore skipped draft for ${displayName}`}
              className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-muted-foreground/55 transition hover:bg-muted hover:text-primary disabled:opacity-50"
            >
              {restoringId === draft.id ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <RotateCcw className="h-3.5 w-3.5" />
              )}
            </button>
            <ChevronRight className="h-3.5 w-3.5 shrink-0 text-muted-foreground/50 transition-colors group-hover:text-foreground/60" />
          </div>
        );
      })}
    </div>
  );
}

// RealEstateTodayPage moved to `real-estate-hub/today/index.tsx`.

type LeadSourceOption = {
  id: string;
  label: string;
  drafts: number;
  profiles: number;
  threads: number;
};

function LeadFilterBar({
  active,
  buyerSearches,
  drafts,
  followUps,
  hot,
  onSelect,
  options,
  pulse,
  profiles,
  skipped,
  threads,
}: {
  active: string | null;
  buyerSearches: number;
  drafts: number;
  followUps: number;
  hot: number;
  onSelect: (id: string | null) => void;
  options: LeadSourceOption[];
  pulse?: ResponsePulse;
  profiles: number;
  skipped: number;
  threads: number;
}) {
  type Stat = {
    label: string;
    value: number | string;
    tone: "warning" | "default" | "muted" | "destructive";
    emphasis?: "primary" | "secondary";
  };
  const queueStats: Stat[] = [
    { label: "Drafts to approve", value: drafts, tone: drafts > 0 ? "warning" : "muted", emphasis: "primary" },
    { label: "Hot leads", value: hot, tone: hot > 0 ? "default" : "muted", emphasis: "primary" },
    { label: "Follow-ups", value: followUps, tone: followUps > 0 ? "warning" : "muted", emphasis: "primary" },
    { label: "Buyer searches", value: buyerSearches, tone: buyerSearches > 0 ? "default" : "muted", emphasis: "primary" },
    { label: "Skipped", value: skipped, tone: skipped > 0 ? "warning" : "muted", emphasis: "primary" },
    { label: "Profiles", value: profiles, tone: profiles > 0 ? "default" : "muted", emphasis: "primary" },
    { label: "Open threads", value: threads, tone: "default", emphasis: "primary" },
  ];
  const slaStats: Stat[] = [];
  if (pulse) {
    slaStats.push({
      label: "Unanswered",
      value: pulse.unanswered,
      tone: pulse.breached30 > 0 ? "destructive" : pulse.unanswered > 0 ? "warning" : "muted",
      emphasis: "secondary",
    });
    slaStats.push({
      label: "Median wait",
      value: formatMinutes(pulse.median),
      tone: (pulse.median ?? 0) >= 30 ? "destructive" : (pulse.median ?? 0) >= 5 ? "warning" : "muted",
      emphasis: "secondary",
    });
    slaStats.push({
      label: "Longest wait",
      value: formatMinutes(pulse.longest),
      tone: (pulse.longest ?? 0) >= 60 ? "destructive" : (pulse.longest ?? 0) >= 30 ? "warning" : "muted",
      emphasis: "secondary",
    });
  }

  const renderStat = (stat: Stat) => (
    <span key={stat.label} className="inline-flex items-baseline gap-1">
      <span
        className={cn(
          "font-medium tabular-nums",
          stat.tone === "warning" && "text-warning",
          stat.tone === "destructive" && "text-destructive",
          stat.tone === "default" && "text-foreground",
          stat.tone === "muted" && "text-muted-foreground",
        )}
      >
        {stat.value}
      </span>
      <span className="text-muted-foreground">{stat.label}</span>
    </span>
  );

  return (
    <div>
      <div className="flex flex-wrap items-baseline gap-x-1 gap-y-1 px-1 py-1 text-sm text-muted-foreground">
        {queueStats.map((stat, i) => (
          <span key={stat.label} className="inline-flex items-baseline">
            {i > 0 && <span aria-hidden="true" className="mx-1.5 text-border">·</span>}
            {renderStat(stat)}
          </span>
        ))}
        {slaStats.length > 0 && (
          <span aria-hidden="true" className="mx-2 text-border">|</span>
        )}
        {slaStats.map((stat, i) => (
          <span key={stat.label} className="inline-flex items-baseline">
            {i > 0 && <span aria-hidden="true" className="mx-1.5 text-border">·</span>}
            {renderStat(stat)}
          </span>
        ))}
      </div>
      {options.length > 0 && (
        <div className="px-1 py-1.5">
          <TabsList>
            <TabsTrigger
              active={active === null}
              value="__all"
              onClick={() => onSelect(null)}
            >
              All
            </TabsTrigger>
            {options.map((option) => (
              <TabsTrigger
                key={option.id}
                active={active === option.id}
                value={option.id}
                onClick={() => onSelect(option.id)}
              >
                {option.label}
                <span className="ml-1.5 font-mono-ui text-[0.7rem] text-muted-foreground/80 tabular-nums">
                  {option.drafts || option.profiles || option.threads}
                </span>
              </TabsTrigger>
            ))}
          </TabsList>
        </div>
      )}
    </div>
  );
}


function CollapsibleSection({
  children,
  count,
  defaultOpen = false,
  description,
  title,
}: {
  children: React.ReactNode;
  count?: number;
  defaultOpen?: boolean;
  description?: string;
  title: string;
}) {
  return (
    <details
      className="group rounded-md border border-border bg-card [&_summary]:list-none"
      open={defaultOpen}
    >
      <summary className="flex min-h-[3rem] cursor-pointer items-center justify-between gap-3 px-4 py-3 text-sm font-semibold text-foreground hover:bg-card">
        <span className="flex min-w-0 items-center gap-2">
          <h3 className="text-sm font-semibold">{title}</h3>
          {typeof count === "number" && (
            <span className="font-mono-ui inline-flex items-center rounded-sm border border-border bg-card px-2 py-0.5 text-[0.66rem] font-semibold text-foreground/75">
              {count}
            </span>
          )}
          {description && (
            <span className="truncate text-xs font-normal text-foreground/70 sm:inline">
              {description}
            </span>
          )}
        </span>
        <ChevronDown
          aria-hidden
          className="h-4 w-4 shrink-0 text-muted-foreground transition-transform group-open:rotate-180"
        />
      </summary>
      <div className="border-t border-border/55 px-4 py-4">{children}</div>
    </details>
  );
}

type AgentLaneId = "new-outreach" | "hot-leads-watcher" | "follow-ups" | "private-searches";

type AgentLaneDef = {
  id: AgentLaneId;
  name: string;
  tagline: string;
  icon: ComponentType<{ className?: string }>;
  schedule: string;
  scheduleLabel: string;
  matchKeywords: string[];
  prompt: string;
  cronName: string;
};

const AGENT_LANES: AgentLaneDef[] = [
  {
    id: "new-outreach",
    name: "New Outreach",
    tagline: "Daily first-touch on fresh leads from every connected source.",
    icon: Sparkles,
    schedule: "0 8 * * *",
    scheduleLabel: "Daily · 8:00am",
    matchKeywords: ["new outreach", "outreach", "first touch", "first-touch"],
    cronName: "New Outreach",
    prompt:
      "Run the outreach skill. Pull fresh leads from every connected source (CRM, SMS, email, social via Composio) that have not yet received a first-touch in the last 14 days. For each one: enrich from CRM + property-lookup, draft a personalized first message on the channel they came in from, and write the draft to the source inbox for approval. Do not send. Mark each lead as touched only after the human approves.",
  },
  {
    id: "hot-leads-watcher",
    name: "Hot Leads Watcher",
    tagline: "Daily scan for the hottest leads across channels.",
    icon: Radar,
    schedule: "0 8 * * *",
    scheduleLabel: "Daily · 8:00am",
    matchKeywords: ["hot lead", "hot leads", "watcher", "heat"],
    cronName: "Hot Leads Watcher",
    prompt:
      "Run the outreach skill in monitor mode. Scan every connected source (Lofty CRM, Apple Messages, Gmail, SMS, social via Composio) for hot signals since the last run: inbound replies, viewing requests, repeat opens, CRM stage moves, listing alerts. Re-score heat across the inbox and surface the top 10 hottest leads. For any lead with a brand-new inbound message that needs a reply, draft a same-channel response and queue it for approval. Do not send.",
  },
  {
    id: "follow-ups",
    name: "Follow-ups",
    tagline: "Re-touches scheduled threads that went cold.",
    icon: Repeat,
    schedule: "0 10,15 * * *",
    scheduleLabel: "Twice daily · 10a + 3p",
    matchKeywords: ["follow-up", "follow up", "followup", "nurture"],
    cronName: "Follow-ups",
    prompt:
      "Run the outreach skill in nurture mode. For every lead with an open thread whose last outbound was 3+ days ago without a reply (or whose CRM stage is in nurture), draft a context-aware follow-up on the same channel they were last contacted. Use the relationship history, last touch, and CRM stage to pick the angle. Queue every draft for approval. Do not send.",
  },
  {
    id: "private-searches",
    name: "Private Searches",
    tagline: "Nightly MLS PCS scrape → score → watchlist → CRM sync.",
    icon: Filter,
    schedule: "0 3 * * *",
    scheduleLabel: "Daily · 3:00am",
    matchKeywords: [
      "private search",
      "private searches",
      "pcs",
      "xposure",
      "saved search",
      "watchlist",
    ],
    cronName: "Private Searches",
    prompt:
      "Run the PCS pipeline: (1) scrape every registered buyer with a Private Client Search from Xposure MLS, push deltas to the CRM tagged xposure-pcs; (2) score each buyer HOT (active ≤30d) / WARM (≤90d) / cold; (3) for HOT buyers, pull their saved-search criteria (areas, beds, property type) and update the CRM stage + tag; (4) build a branded watchlist PDF with cover + per-lead cards (score, last active, areas, beds, call script). Stage results in the source dir. Do not send any messages.",
  },
];

function laneCronJob(lane: AgentLaneDef, jobs: CronJob[]): CronJob | undefined {
  const target = lane.cronName.toLowerCase();
  return (
    jobs.find((job) => (job.name ?? "").toLowerCase() === target) ??
    jobs.find((job) => jobMatches(job, lane.matchKeywords))
  );
}

function laneStatus(job: CronJob | undefined): {
  label: string;
  tone: "success" | "warning" | "muted" | "destructive";
} {
  if (!job) return { label: "Not started", tone: "muted" };
  if (job.last_error) return { label: "Error", tone: "destructive" };
  if (!job.enabled || job.state === "paused") return { label: "Paused", tone: "warning" };
  const nextMs = job.next_run_at ? Date.parse(job.next_run_at) : NaN;
  const lastMs = job.last_run_at ? Date.parse(job.last_run_at) : NaN;
  const now = Date.now();
  if (Number.isFinite(nextMs) && nextMs <= now && (!Number.isFinite(lastMs) || lastMs < nextMs)) {
    return { label: "Running", tone: "success" };
  }
  if (Number.isFinite(lastMs) && now - lastMs < 5 * 60 * 1000) {
    return { label: "Just ran", tone: "success" };
  }
  return { label: "Scheduled", tone: "muted" };
}

function OutreachLanesGrid({
  cronJobs,
  onChanged,
}: {
  cronJobs: CronJob[];
  onChanged: () => Promise<void>;
}) {
  // Idempotently install/converge the default lanes the first time this view
  // renders. Server-side ``ensure-lanes`` updates an existing lane if the
  // default delivery, prompt, schedule, skills, or workdir changed. localStorage gate
  // means we don't hit the endpoint on every navigation; the UI still
  // converges if a lane was deleted (clear the flag from devtools).
  useEffect(() => {
    if (typeof window === "undefined") return;
    const FLAG = "elevate.lanes.defaults_installed_v1";
    if (window.localStorage.getItem(FLAG) === "1") return;
    let cancelled = false;
    (async () => {
      try {
        await api.ensureLaneCronJobs(
          AGENT_LANES.map((lane) => ({
            name: lane.cronName,
            schedule: lane.schedule,
            prompt: lane.prompt,
            deliver: "local",
          })),
        );
        if (!cancelled) {
          window.localStorage.setItem(FLAG, "1");
        }
      } catch {
        // Best-effort install — if the endpoint is unavailable, the
        // legacy "Start" button on each card still works.
      }
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="rounded-md border border-border bg-card">
      <div className="flex flex-col divide-y divide-border">
        {AGENT_LANES.map((lane) => (
          <AgentLaneStripRow
            key={lane.id}
            lane={lane}
            job={laneCronJob(lane, cronJobs)}
            onChanged={onChanged}
          />
        ))}
      </div>
    </div>
  );
}

const LANE_STATUS_VARIANT: Record<
  ReturnType<typeof laneStatus>["tone"],
  "success" | "warning" | "destructive" | "secondary"
> = {
  success: "success",
  warning: "warning",
  destructive: "destructive",
  muted: "secondary",
};

function AgentLaneStripRow({
  lane,
  job,
  onChanged,
}: {
  lane: AgentLaneDef;
  job: CronJob | undefined;
  onChanged: () => Promise<void>;
}) {
  const Icon = lane.icon;
  const status = laneStatus(job);
  const [busy, setBusy] = useState<"start" | "trigger" | "toggle" | null>(null);

  const start = async () => {
    setBusy("start");
    try {
      await api.createCronJob({
        name: lane.cronName,
        schedule: lane.schedule,
        prompt: lane.prompt,
        deliver: "local",
      });
      await onChanged();
    } finally {
      setBusy(null);
    }
  };

  const trigger = async () => {
    if (!job) return;
    setBusy("trigger");
    try {
      await api.triggerCronJob(job.id);
      await onChanged();
    } finally {
      setBusy(null);
    }
  };

  const toggle = async () => {
    if (!job) return;
    setBusy("toggle");
    try {
      if (job.state === "paused" || !job.enabled) {
        await api.resumeCronJob(job.id);
      } else {
        await api.pauseCronJob(job.id);
      }
      await onChanged();
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="flex items-center gap-4 px-4 py-4">
      <div className="min-w-0 flex-1">
        <div className="mb-1 flex items-center gap-2">
          <Icon className="h-3.5 w-3.5 shrink-0 text-primary" />
          <span className="truncate text-sm font-medium text-foreground">{lane.name}</span>
          <Badge variant={LANE_STATUS_VARIANT[status.tone]}>{status.label}</Badge>
        </div>
        <p className="mb-1 truncate text-xs text-muted-foreground">{lane.tagline}</p>
        <div className="flex flex-col gap-1 text-xs text-muted-foreground lg:flex-row lg:flex-wrap lg:items-center lg:gap-x-4">
          <span className="font-mono truncate">{job?.schedule_display || lane.scheduleLabel}</span>
          <span className="flex flex-wrap gap-x-4 gap-y-1">
            <span>last: {job?.last_run_at ? isoTimeAgo(job.last_run_at) : "—"}</span>
            <span>next: {job?.next_run_at ? isoTimeAgo(job.next_run_at) : job ? "queued" : "—"}</span>
          </span>
        </div>
        {job?.last_error && (
          <p className="mt-1 text-xs text-destructive">{job.last_error}</p>
        )}
      </div>

      <div className="flex shrink-0 items-center gap-1">
        {job ? (
          <>
            <Button
              variant="ghost"
              size="icon"
              onClick={() => void toggle()}
              disabled={busy !== null}
              title={job.state === "paused" || !job.enabled ? "Resume" : "Pause"}
              aria-label={
                job.state === "paused" || !job.enabled
                  ? `Resume ${lane.name}`
                  : `Pause ${lane.name}`
              }
            >
              {job.state === "paused" || !job.enabled ? (
                <Play className="h-4 w-4 text-success" />
              ) : (
                <Pause className="h-4 w-4 text-warning" />
              )}
            </Button>
            <Button
              variant="ghost"
              size="icon"
              onClick={() => void trigger()}
              disabled={busy !== null}
              title="Run now"
              aria-label={`Run ${lane.name} now`}
            >
              <Zap className="h-4 w-4" />
            </Button>
            <Link
              to={`/cron?edit=${job.id}`}
              aria-label={`Edit ${lane.name} schedule`}
              title="Edit"
              className={cn(
                buttonVariants({ variant: "ghost", size: "icon" }),
                "text-foreground/70 hover:text-foreground",
              )}
            >
              <PencilLine className="h-4 w-4" />
            </Link>
          </>
        ) : (
          <Button
            variant="ghost"
            size="icon"
            onClick={() => void start()}
            disabled={busy !== null}
            title={`Start ${lane.name}`}
            aria-label={`Start ${lane.name}`}
          >
            <Plus className="h-4 w-4 text-primary" />
          </Button>
        )}
      </div>
    </div>
  );
}

const SOURCE_ICON_BY_ID: Record<string, ComponentType<{ className?: string }>> = {
  "apple-messages": MessageSquare,
  "sms-provider": Phone,
  "android-device": Smartphone,
  rcs: Phone,
  crm: DatabaseIcon,
  social: Share2,
  email: Mail,
  skills: Network,
  "market-stats": Activity,
  "admin-requirements": BriefcaseBusiness,
  "document-storage": FileText,
  "forms-signing": FileCheck2,
};

const OUTREACH_CATEGORIES = new Set(["messages", "leads"]);

function sourceIcon(source: SourceConnectorStatus): ComponentType<{ className?: string }> {
  return SOURCE_ICON_BY_ID[source.id] ?? Inbox;
}

function compactCount(value: number): string {
  if (value >= 10000) {
    return new Intl.NumberFormat(undefined, { notation: "compact" }).format(value);
  }
  return new Intl.NumberFormat().format(value);
}

type ContactState = {
  uncontacted: number;
  contacted: number;
};

function contactStateFromThreads(threads: SourceInboxThread[]): ContactState {
  let contacted = 0;
  let uncontacted = 0;
  for (const thread of threads) {
    if (thread.outboundCount > 0) contacted += 1;
    else uncontacted += 1;
  }
  return { contacted, uncontacted };
}

function contactStateFromProfiles(
  profiles: SourceInboxProfile[],
  threadsById: Map<string, SourceInboxThread>,
): ContactState {
  let contacted = 0;
  let uncontacted = 0;
  for (const profile of profiles) {
    const touched = profile.threadIds.some((id) => {
      const thread = threadsById.get(id);
      return thread ? thread.outboundCount > 0 : false;
    });
    if (touched) contacted += 1;
    else uncontacted += 1;
  }
  return { contacted, uncontacted };
}

function ComposioChannelStrip() {
  const [status, setStatus] = useState<ComposioStatus | null>(null);
  const [connections, setConnections] = useState<ComposioConnectedAccount[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const s = await api.getComposioStatus();
        if (cancelled) return;
        setStatus(s);
        if (!s.valid) {
          setConnections([]);
          return;
        }
        const conns = await api.getComposioConnections();
        if (cancelled) return;
        const data = (conns.data as { items?: ComposioConnectedAccount[] } | ComposioConnectedAccount[]) ?? [];
        setConnections(Array.isArray(data) ? data : data.items ?? []);
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    void load();
    return () => {
      cancelled = true;
    };
  }, []);

  if (loading || !status) return null;
  if (!status.hasKey) return null;

  return (
    <div className="space-y-2.5">
      <div className="flex items-center justify-between gap-2">
        <h4 className="font-mono-ui text-[0.66rem] font-semibold uppercase tracking-[0.16em] text-muted-foreground/80">
          Composio {status.valid ? `· ${connections.length} connected` : "· key invalid"}
        </h4>
        <Link
          to="/config#composio"
          className="text-xs text-foreground/65 transition-colors hover:text-foreground"
        >
          Manage
        </Link>
      </div>
      {!status.valid ? (
        <p className="text-xs leading-5 text-warning">
          Composio rejected the saved key. Update it in Config to import these channels.
        </p>
      ) : connections.length === 0 ? (
        <p className="text-xs leading-5 text-muted-foreground">
          No Composio accounts linked yet. Connect Instagram, Gmail, Twilio, or any other app from the Config page.
        </p>
      ) : (
        <div className="flex flex-wrap gap-1.5">
          {connections.map((conn, idx) => (
            <span
              key={String(conn.id ?? idx)}
              className="inline-flex items-center gap-1.5 rounded-sm border border-border bg-card px-2.5 py-1 text-xs text-foreground"
            >
              {conn.toolkit?.logo && (
                <img
                  src={conn.toolkit.logo}
                  alt=""
                  width={14}
                  height={14}
                  loading="lazy"
                  decoding="async"
                  className="h-3.5 w-3.5 rounded-sm"
                />
              )}
              <span>{conn.toolkit?.name ?? conn.toolkit?.slug ?? "app"}</span>
              {conn.status === "ACTIVE" && (
                <span aria-label="active" className="h-1.5 w-1.5 rounded-full bg-success" />
              )}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

function ChannelsPanel({
  profiles,
  sources,
  threads,
}: {
  profiles: SourceInboxProfile[];
  sources: SourceConnectorStatus[];
  threads: SourceInboxThread[];
}) {
  const threadsById = useMemo(() => {
    const map = new Map<string, SourceInboxThread>();
    for (const thread of threads) map.set(thread.id, thread);
    return map;
  }, [threads]);

  const threadsBySource = useMemo(() => {
    const grouped = new Map<string, SourceInboxThread[]>();
    for (const thread of threads) {
      const list = grouped.get(thread.sourceId) ?? [];
      list.push(thread);
      grouped.set(thread.sourceId, list);
    }
    return grouped;
  }, [threads]);

  const { live, available } = useMemo(() => {
    const liveList: SourceConnectorStatus[] = [];
    const availableList: SourceConnectorStatus[] = [];
    for (const source of sources) {
      if (!OUTREACH_CATEGORIES.has(source.category)) continue;
      if (source.connected || source.importOnly || source.blocked || source.state === "needs_operator" || source.state === "error") {
        liveList.push(source);
      } else {
        availableList.push(source);
      }
    }
    return { live: liveList, available: availableList };
  }, [sources]);

  const cross = contactStateFromProfiles(profiles, threadsById);
  const totalContacts = cross.contacted + cross.uncontacted;

  return (
    <Card>
      <CardHeader>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <CardTitle className="flex items-center gap-2 text-sm">
              <Plug className="h-4 w-4 text-foreground/65" />
              Channels
            </CardTitle>
            <p className="font-mono-ui mt-1.5 text-[0.72rem] tabular-nums text-muted-foreground">
              {compactCount(cross.contacted)} contacted · {compactCount(cross.uncontacted)} uncontacted ·{" "}
              {compactCount(totalContacts)} people · {live.length} live{available.length ? ` · ${available.length} available` : ""}
            </p>
          </div>
          <Link
            to="/config#composio"
            className={cn(buttonVariants({ variant: "outline", size: "sm" }), "h-11 px-3 text-xs sm:h-9")}
            aria-label="Connect a new channel from Config"
          >
            <Plus className="h-3.5 w-3.5" />
            Connect channel
          </Link>
        </div>
      </CardHeader>
      <CardContent className="flex flex-col gap-7">
        {live.length > 0 && (
          <div className="divide-y divide-border">
            {live.map((source) => (
              <LiveChannelCard
                key={source.id}
                source={source}
                threads={threadsBySource.get(source.id) ?? []}
              />
            ))}
          </div>
        )}

        <ComposioChannelStrip />

        {available.length > 0 && (
          <div className="space-y-2.5">
            <h4 className="font-mono-ui text-[0.66rem] font-semibold uppercase tracking-[0.16em] text-muted-foreground/80">
              Available — connect to expand the inbox
            </h4>
            <div className="flex flex-wrap gap-1.5">
              {available.map((source) => (
                <AvailableChannelChip key={source.id} source={source} />
              ))}
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function LiveChannelCard({
  source,
  threads,
}: {
  source: SourceConnectorStatus;
  threads: SourceInboxThread[];
}) {
  const Icon = sourceIcon(source);
  const state = contactStateFromThreads(threads);
  const totalRecords = Object.values(source.recordCounts ?? {}).reduce(
    (sum, value) => sum + (Number(value) || 0),
    0,
  );
  const tone = source.blocked
    ? "destructive"
    : source.connected
      ? "success"
      : source.importOnly
        ? "default"
        : "warning";
  const stateLabel = source.connected
    ? "live"
    : source.importOnly
      ? "import only"
      : source.blocked
        ? "blocked"
        : source.state === "needs_operator"
          ? "needs setup"
          : "error";

  return (
    <Link
      to="/config#composio"
      aria-label={`Configure ${source.label} channel — ${stateLabel}, ${compactCount(state.uncontacted)} uncontacted, ${compactCount(state.contacted)} contacted, ${compactCount(totalRecords)} records`}
      className="group flex items-start gap-3 py-3 transition-colors first:pt-0 last:pb-0 hover:bg-foreground/[0.02]"
    >
      <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-card border border-border text-primary">
        {createElement(Icon, { className: "h-4 w-4" })}
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
          <span className="truncate text-sm font-semibold text-foreground">{source.label}</span>
          <span
            className={cn(
              "font-mono-ui inline-flex items-center gap-1 rounded-sm px-1.5 py-0.5 text-[0.62rem] font-semibold uppercase tracking-[0.14em]",
              tone === "success" && "bg-card border border-border text-success",
              tone === "warning" && "bg-card border border-border text-warning",
              tone === "destructive" && "bg-card border border-border text-destructive",
              tone === "default" && "bg-card border border-border text-primary",
            )}
          >
            {stateLabel}
          </span>
        </div>
        {source.nextOperatorStep && !source.connected && (
          <p className="mt-1 line-clamp-2 text-[0.72rem] leading-4 text-muted-foreground">
            {source.nextOperatorStep}
          </p>
        )}
      </div>
      <div className="font-mono-ui shrink-0 self-center text-right text-[0.72rem] tabular-nums leading-tight text-muted-foreground">
        <div>
          <span className="text-warning">{compactCount(state.uncontacted)}</span> uncontacted
        </div>
        <div className="mt-0.5">
          <span className="text-success">{compactCount(state.contacted)}</span> contacted
          <span className="text-muted-foreground/60"> · </span>
          <span className="text-foreground/85">{compactCount(totalRecords)}</span> records
        </div>
      </div>
    </Link>
  );
}

function AvailableChannelChip({ source }: { source: SourceConnectorStatus }) {
  const Icon = sourceIcon(source);
  return (
    <Link
      to="/config#composio"
      aria-label={`Connect ${source.label} channel`}
      className="inline-flex items-center gap-1.5 rounded-sm border border-border bg-card px-2.5 py-1 text-xs text-foreground/75 transition-colors hover:border-ring hover:bg-card hover:text-foreground"
    >
      {createElement(Icon, { className: "h-3 w-3" })}
      <span>{source.label}</span>
      <Plus className="h-3 w-3" />
    </Link>
  );
}

const LANE_META: Record<OutreachLane, { label: string; icon: typeof Sparkles; tone: string }> = {
  "new-outreach": { label: "New Outreach", icon: Sparkles, tone: "text-primary" },
  "hot-leads-watcher": { label: "Hot Leads Watcher", icon: Flame, tone: "text-warning" },
  "follow-ups": { label: "Follow-ups", icon: Repeat, tone: "text-success" },
};

const LEAD_TABS = [
  { id: "action-board" as const, label: "Action Board", icon: Radar },
  { id: "profiles" as const, label: "Profiles", icon: Users },
  { id: "templates" as const, label: "Templates", icon: BookText },
  { id: "sent" as const, label: "Sent", icon: Send },
];

type LeadTab = (typeof LEAD_TABS)[number]["id"];

function LeadsTabBar({ active, onChange }: { active: LeadTab; onChange: (tab: LeadTab) => void }) {
  return (
    <div
      role="tablist"
      aria-label="Leads view"
      className="inline-flex items-center gap-1 rounded-sm border border-border bg-card p-1 text-xs"
    >
      {LEAD_TABS.map((tab) => {
        const Icon = tab.icon;
        const selected = tab.id === active;
        return (
          <button
            key={tab.id}
            type="button"
            role="tab"
            id={`leads-tab-${tab.id}`}
            aria-selected={selected}
            aria-controls={`leads-panel-${tab.id}`}
            tabIndex={selected ? 0 : -1}
            onClick={() => onChange(tab.id)}
            className={cn(
              "inline-flex h-9 items-center gap-1.5 rounded-sm px-3 transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring",
              selected
                ? "bg-foreground text-background"
                : "text-foreground/70 hover:bg-foreground/5 hover:text-foreground",
            )}
          >
            <Icon className="h-3.5 w-3.5" />
            {tab.label}
          </button>
        );
      })}
    </div>
  );
}

function LaneOverviewCard({
  laneOv,
  onSuggest,
  suggesting,
}: {
  laneOv: OutreachLaneOverview;
  onSuggest: (lane: OutreachLane) => void;
  suggesting: boolean;
}) {
  const meta = LANE_META[laneOv.lane];
  const Icon = meta.icon;
  return (
    <div className="rounded-md border border-border bg-card p-3">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <Icon className={cn("h-4 w-4", meta.tone)} />
          <span className="text-sm font-semibold text-foreground">{meta.label}</span>
        </div>
        <Button
          size="sm"
          variant="outline"
          onClick={() => onSuggest(laneOv.lane)}
          disabled={suggesting}
          className="h-11 px-3 text-xs sm:h-9"
          aria-label={`Suggest a new ${meta.label} variant`}
        >
          {suggesting ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Sparkles className="h-3.5 w-3.5" />}
          Suggest variant
        </Button>
      </div>

      <div className="font-mono-ui mt-3 flex items-baseline gap-3 text-[0.78rem] tabular-nums text-muted-foreground">
        <span>
          <span className="text-base font-semibold text-foreground">{laneOv.activeTemplates}</span>{" "}
          <span className="text-[0.66rem] uppercase tracking-[0.16em] text-muted-foreground/80">active</span>
        </span>
        <span className="text-foreground/35">·</span>
        <span>
          <span className="text-base font-semibold text-foreground">{laneOv.totalAttempts}</span>{" "}
          <span className="text-[0.66rem] uppercase tracking-[0.16em] text-muted-foreground/80">sent</span>
        </span>
        <span className="text-foreground/35">·</span>
        <span>
          <span className="text-base font-semibold text-foreground">
            {(laneOv.laneReplyRate * 100).toFixed(0)}%
          </span>{" "}
          <span className="text-[0.66rem] uppercase tracking-[0.16em] text-muted-foreground/80">reply</span>
        </span>
      </div>

      <div className="mt-3 space-y-1.5">
        {laneOv.best ? (
          <div className="flex items-start gap-2 text-xs">
            <Award className="mt-0.5 h-3.5 w-3.5 shrink-0 text-success" />
            <div className="min-w-0">
              <span className="text-foreground/65">Best: </span>
              <span className="text-foreground">{laneOv.best.name}</span>
              <span className="text-foreground/65">
                {" "}· {(laneOv.best.replyRate * 100).toFixed(0)}% / {laneOv.best.uses} sends
              </span>
            </div>
          </div>
        ) : (
          <div className="text-xs text-foreground/65">
            Need {Math.max(5 - laneOv.totalAttempts, 5)}+ more sends to rank.
          </div>
        )}
        {laneOv.worst && (
          <div className="flex items-start gap-2 text-xs">
            <TrendingDown className="mt-0.5 h-3.5 w-3.5 shrink-0 text-destructive" />
            <div className="min-w-0">
              <span className="text-foreground/65">Weakest: </span>
              <span className="text-foreground">{laneOv.worst.name}</span>
              <span className="text-foreground/65">
                {" "}· {(laneOv.worst.replyRate * 100).toFixed(0)}% / {laneOv.worst.uses} sends
              </span>
            </div>
          </div>
        )}
        {laneOv.drift.length > 0 && (
          <div className="flex items-start gap-2 text-xs">
            <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-warning" />
            <div className="text-foreground/70">
              <span className="text-foreground">{laneOv.drift[0].template.name}</span> dropped{" "}
              <span className="text-warning">{laneOv.drift[0].deltaPct}%</span> in last 30d.
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function PendingApprovalRow({
  template,
  onApprove,
  onReject,
  busy,
}: {
  template: OutreachTemplate;
  onApprove: (id: string) => void;
  onReject: (id: string) => void;
  busy: boolean;
}) {
  return (
    <div className="rounded-md border border-border bg-card p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <Sparkles className="h-3.5 w-3.5 text-warning" />
          <span className="text-sm font-medium text-foreground">{template.name}</span>
          <Badge variant="warning" className="text-[10px]">
            pending approval
          </Badge>
        </div>
        <div className="flex items-center gap-1.5">
          <Button
            size="sm"
            variant="outline"
            onClick={() => onReject(template.id)}
            disabled={busy}
            className="h-9 px-3 text-xs"
            aria-label={`Reject template ${template.name}`}
          >
            <ThumbsDown className="h-3.5 w-3.5" />
            Reject
          </Button>
          <Button
            size="sm"
            onClick={() => onApprove(template.id)}
            disabled={busy}
            className="h-9 px-3 text-xs"
            aria-label={`Approve template ${template.name}`}
          >
            {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <ThumbsUp className="h-3.5 w-3.5" />}
            Approve
          </Button>
        </div>
      </div>
      <p className="mt-2 whitespace-pre-wrap text-sm leading-relaxed text-foreground">
        {template.body}
      </p>
      {template.rationale && (
        <p className="mt-2 text-xs italic text-muted-foreground">
          Why: {template.rationale}
        </p>
      )}
    </div>
  );
}

function TemplatesPanel() {
  const [templates, setTemplates] = useState<OutreachTemplate[]>([]);
  const [overview, setOverview] = useState<OutreachOverview | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState<Record<string, { name: string; body: string }>>({});
  const [savingId, setSavingId] = useState<string | null>(null);
  const [suggestingLane, setSuggestingLane] = useState<OutreachLane | null>(null);
  const [showNew, setShowNew] = useState<OutreachLane | null>(null);
  const [draft, setDraft] = useState<{ lane: OutreachLane; name: string; body: string }>({
    lane: "new-outreach",
    name: "",
    body: "",
  });

  const reload = useCallback(async () => {
    setLoading(true);
    try {
      const [tplRes, ovRes] = await Promise.all([
        api.getOutreachTemplates(),
        api.getOutreachOverview(),
      ]);
      setTemplates(tplRes.templates);
      setOverview(ovRes);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void reload();
  }, [reload]);

  const suggest = async (lane: OutreachLane) => {
    setSuggestingLane(lane);
    try {
      await api.suggestOutreachTemplate({ lane });
      await reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSuggestingLane(null);
    }
  };

  const approve = async (id: string) => {
    setSavingId(id);
    try {
      await api.approveOutreachTemplate(id);
      await reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSavingId(null);
    }
  };

  const reject = async (id: string) => {
    setSavingId(id);
    try {
      await api.rejectOutreachTemplate(id);
      await reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSavingId(null);
    }
  };

  const grouped = useMemo(() => {
    const map: Record<OutreachLane, OutreachTemplate[]> = {
      "new-outreach": [],
      "hot-leads-watcher": [],
      "follow-ups": [],
    };
    for (const t of templates) {
      if (t.status !== "active" && t.status !== undefined && t.status !== null) continue;
      if (map[t.lane]) map[t.lane].push(t);
    }
    return map;
  }, [templates]);

  const pendingByLane = useMemo(() => {
    const map: Record<OutreachLane, OutreachTemplate[]> = {
      "new-outreach": [],
      "hot-leads-watcher": [],
      "follow-ups": [],
    };
    for (const t of templates) {
      if (t.status === "pending_approval" && map[t.lane]) map[t.lane].push(t);
    }
    return map;
  }, [templates]);

  const startEdit = (t: OutreachTemplate) => {
    setEditing((prev) => ({ ...prev, [t.id]: { name: t.name, body: t.body } }));
  };
  const cancelEdit = (id: string) => {
    setEditing((prev) => {
      const next = { ...prev };
      delete next[id];
      return next;
    });
  };
  const saveEdit = async (t: OutreachTemplate) => {
    const draftEdit = editing[t.id];
    if (!draftEdit) return;
    setSavingId(t.id);
    try {
      await api.updateOutreachTemplate(t.id, { name: draftEdit.name, body: draftEdit.body });
      cancelEdit(t.id);
      await reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSavingId(null);
    }
  };
  const toggleActive = async (t: OutreachTemplate) => {
    setSavingId(t.id);
    try {
      await api.updateOutreachTemplate(t.id, { active: !t.active });
      await reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSavingId(null);
    }
  };
  const remove = async (t: OutreachTemplate) => {
    if (!confirm(`Delete template "${t.name}"? Past attempts stay logged.`)) return;
    setSavingId(t.id);
    try {
      await api.deleteOutreachTemplate(t.id);
      await reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSavingId(null);
    }
  };
  const createNew = async () => {
    if (!draft.name.trim() || !draft.body.trim()) return;
    setSavingId("__new__");
    try {
      await api.createOutreachTemplate({
        lane: draft.lane,
        name: draft.name.trim(),
        body: draft.body.trim(),
      });
      setDraft({ lane: draft.lane, name: "", body: "" });
      setShowNew(null);
      await reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSavingId(null);
    }
  };

  if (loading && templates.length === 0) {
    return (
      <div className="flex items-center gap-2 rounded-md border border-border bg-card p-6 text-sm text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" />
        Loading templates…
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="rounded-md border border-border bg-card p-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <div className="text-sm font-semibold text-foreground">Templates overview</div>
            <p className="mt-1 max-w-prose text-xs text-muted-foreground">
              What's working, what's not, and fresh variants for approval. Best/worst rank after{" "}
              {overview?.thresholds.minUsesForRanking ?? 5}+ sends. Drift flags templates whose 30-day
              reply rate dropped {overview?.thresholds.driftDropPct ?? 30}%+ vs all-time.
            </p>
          </div>
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <span>{templates.length} total · {templates.filter((t) => t.active).length} active</span>
            {(overview?.pendingTotal ?? 0) > 0 && (
              <Badge variant="warning" className="text-[10px]">
                {overview!.pendingTotal} pending
              </Badge>
            )}
          </div>
        </div>
        {error && (
          <div className="mt-3 rounded-sm border border-border bg-card px-3 py-2 text-xs text-destructive">
            {error}
          </div>
        )}
      </div>

      {overview && (
        <div className="grid gap-3 lg:grid-cols-3">
          {overview.lanes.map((laneOv) => (
            <LaneOverviewCard
              key={laneOv.lane}
              laneOv={laneOv}
              onSuggest={suggest}
              suggesting={suggestingLane === laneOv.lane}
            />
          ))}
        </div>
      )}

      {(Object.keys(LANE_META) as OutreachLane[]).map((lane) => {
        const meta = LANE_META[lane];
        const Icon = meta.icon;
        const list = grouped[lane];
        return (
          <Card key={lane} className="border-border bg-card">
            <CardHeader className="flex flex-row items-center justify-between gap-3 space-y-0 pb-3">
              <div className="flex items-center gap-2">
                <Icon className={cn("h-4 w-4", meta.tone)} />
                <CardTitle className="text-sm font-semibold text-foreground">
                  {meta.label}
                </CardTitle>
                <Badge variant="outline" className="text-[10px]">
                  {list.length} template{list.length === 1 ? "" : "s"}
                </Badge>
              </div>
              <Button
                size="sm"
                variant="outline"
                onClick={() => {
                  setShowNew(lane);
                  setDraft({ lane, name: "", body: "" });
                }}
              >
                <Plus className="h-3.5 w-3.5" />
                New template
              </Button>
            </CardHeader>
            <CardContent className="flex flex-col gap-3 pt-0">
              {pendingByLane[lane].length > 0 && (
                <div className="space-y-2">
                  <h4 className="flex items-center gap-2 text-[12px] font-semibold text-warning">
                    <Sparkles className="h-3 w-3" />
                    {pendingByLane[lane].length} variant{pendingByLane[lane].length === 1 ? "" : "s"} awaiting approval
                  </h4>
                  {pendingByLane[lane].map((p) => (
                    <PendingApprovalRow
                      key={p.id}
                      template={p}
                      onApprove={approve}
                      onReject={reject}
                      busy={savingId === p.id}
                    />
                  ))}
                </div>
              )}
              {showNew === lane && (
                <div className="rounded-md border border-border bg-card p-3">
                  <input
                    type="text"
                    placeholder="Template name (e.g. 'Quick warm intro')"
                    value={draft.name}
                    onChange={(e) => setDraft({ ...draft, name: e.target.value })}
                    className="w-full rounded-md border border-border bg-background px-3 py-1.5 text-sm text-foreground outline-none focus:border-ring"
                  />
                  <textarea
                    placeholder="Message body. Use {first_name}, {city}, {topic}, {source}, {area}, {signal}."
                    rows={4}
                    value={draft.body}
                    onChange={(e) => setDraft({ ...draft, body: e.target.value })}
                    className="mt-2 w-full resize-y rounded-md border border-border bg-background px-3 py-2 text-sm text-foreground outline-none focus:border-ring"
                  />
                  <div className="mt-2 flex justify-end gap-2">
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => {
                        setShowNew(null);
                        setDraft({ lane, name: "", body: "" });
                      }}
                    >
                      Cancel
                    </Button>
                    <Button
                      size="sm"
                      onClick={createNew}
                      disabled={!draft.name.trim() || !draft.body.trim() || savingId === "__new__"}
                    >
                      {savingId === "__new__" ? (
                        <Loader2 className="h-3.5 w-3.5 animate-spin" />
                      ) : (
                        <Check className="h-3.5 w-3.5" />
                      )}
                      Save template
                    </Button>
                  </div>
                </div>
              )}

              {list.length === 0 && showNew !== lane && (
                <p className="px-1 py-1 text-xs text-muted-foreground/80">
                  No templates yet — the agent on this lane will skip drafting until at least one exists.
                </p>
              )}

              {list.map((t) => {
                const editingDraft = editing[t.id];
                const isEditing = Boolean(editingDraft);
                return (
                  <div
                    key={t.id}
                    className={cn(
                      "rounded-md border bg-card p-3 transition-colors",
                      t.active ? "border-border/55" : "border-border opacity-65",
                    )}
                  >
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      {isEditing ? (
                        <input
                          type="text"
                          value={editingDraft.name}
                          onChange={(e) =>
                            setEditing((prev) => ({
                              ...prev,
                              [t.id]: { ...editingDraft, name: e.target.value },
                            }))
                          }
                          className="flex-1 min-w-0 rounded-md border border-border bg-background px-2 py-1 text-sm font-medium text-foreground outline-none focus:border-ring"
                        />
                      ) : (
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="text-sm font-medium text-foreground">{t.name}</span>
                          {!t.active && (
                            <Badge variant="outline" className="text-[10px]">
                              paused
                            </Badge>
                          )}
                        </div>
                      )}
                      <div className="flex items-center gap-1">
                        {isEditing ? (
                          <>
                            <Button
                              size="sm"
                              variant="ghost"
                              onClick={() => cancelEdit(t.id)}
                              disabled={savingId === t.id}
                            >
                              <XCircle className="h-3.5 w-3.5" />
                            </Button>
                            <Button size="sm" onClick={() => saveEdit(t)} disabled={savingId === t.id}>
                              {savingId === t.id ? (
                                <Loader2 className="h-3.5 w-3.5 animate-spin" />
                              ) : (
                                <Check className="h-3.5 w-3.5" />
                              )}
                              Save
                            </Button>
                          </>
                        ) : (
                          <>
                            <Button
                              size="sm"
                              variant="ghost"
                              onClick={() => toggleActive(t)}
                              disabled={savingId === t.id}
                              title={t.active ? "Pause this template" : "Activate this template"}
                            >
                              {t.active ? <Pause className="h-3.5 w-3.5" /> : <Play className="h-3.5 w-3.5" />}
                            </Button>
                            <Button size="sm" variant="ghost" onClick={() => startEdit(t)}>
                              <PencilLine className="h-3.5 w-3.5" />
                            </Button>
                            <Button
                              size="sm"
                              variant="ghost"
                              onClick={() => remove(t)}
                              disabled={savingId === t.id}
                              className="text-destructive hover:bg-muted hover:text-destructive"
                            >
                              <Trash2 className="h-3.5 w-3.5" />
                            </Button>
                          </>
                        )}
                      </div>
                    </div>
                    {isEditing ? (
                      <textarea
                        rows={4}
                        value={editingDraft.body}
                        onChange={(e) =>
                          setEditing((prev) => ({
                            ...prev,
                            [t.id]: { ...editingDraft, body: e.target.value },
                          }))
                        }
                        className="mt-2 w-full resize-y rounded-md border border-border bg-background px-3 py-2 text-sm text-foreground outline-none focus:border-ring"
                      />
                    ) : (
                      <p className="mt-2 whitespace-pre-wrap text-sm leading-relaxed text-muted-foreground">
                        {t.body}
                      </p>
                    )}
                    <div className="mt-2 flex flex-wrap items-center gap-3 text-[11px] text-muted-foreground">
                      <span>Used {t.uses}×</span>
                      <span>· {t.replies} repl{t.replies === 1 ? "y" : "ies"}</span>
                      {t.uses > 0 && (
                        <span>· {(t.replyRate * 100).toFixed(0)}% reply rate</span>
                      )}
                      {t.wins > 0 && <span>· {t.wins} won</span>}
                    </div>
                  </div>
                );
              })}
            </CardContent>
          </Card>
        );
      })}
    </div>
  );
}

type SentStatus = SourceInboxSentItem["status"];

function sentStatusTone(status: SentStatus): "success" | "warning" | "danger" | "muted" {
  switch (status) {
    case "sent":
      return "success";
    case "sending":
    case "queued":
      return "muted";
    case "retrying":
      return "warning";
    case "failed":
      return "danger";
    default:
      return "muted";
  }
}

function sentRecipientLabel(item: SourceInboxSentItem): string {
  const r = item.payload?.recipient || {};
  const name = (r.person_name || "").trim();
  const phone = (r.phone || "").trim();
  const email = (r.email || "").trim();
  const handle = (r.social_handle || "").trim();
  if (name && (phone || email || handle)) {
    return `${name} · ${phone || email || handle}`;
  }
  return name || phone || email || handle || r.contact_id || item.threadId;
}

function sentTransportLabel(item: SourceInboxSentItem): string {
  const pmid = (item.providerMessageId || "").toLowerCase();
  if (pmid.startsWith("imessage")) return "iMessage";
  if (pmid.startsWith("sms")) return "SMS";
  if (pmid.startsWith("stub")) return "stub";
  if (pmid.startsWith("agent")) return "agent";
  return item.channel;
}

function SentMessagesBoard({ filterSourceId }: { filterSourceId: string | null }) {
  const [items, setItems] = useState<SourceInboxSentItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [includePending, setIncludePending] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const resp = await api.getSourceInboxSent(200, includePending);
      setItems(resp.items ?? []);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [includePending]);

  useEffect(() => {
    void load();
  }, [load]);

  const visible = useMemo(
    () => (filterSourceId ? items.filter((it) => it.sourceId === filterSourceId) : items),
    [items, filterSourceId],
  );

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="text-xs text-foreground/70">
          {loading ? "Loading…" : `${visible.length} message${visible.length === 1 ? "" : "s"}`}
          {includePending && !loading && " (including in-flight)"}
        </div>
        <div className="flex items-center gap-2">
          <label className="flex items-center gap-1.5 text-xs text-foreground/70">
            <input
              type="checkbox"
              checked={includePending}
              onChange={(e) => setIncludePending(e.target.checked)}
              className="h-3.5 w-3.5"
            />
            Include queued / retrying / failed
          </label>
          <Button size="sm" variant="outline" onClick={() => void load()} className="h-8 px-3 text-xs">
            Refresh
          </Button>
        </div>
      </div>
      {error && (
        <div className="rounded-md border border-warning/40 bg-warning/10 px-3 py-2 text-xs text-foreground">
          {error}
        </div>
      )}
      {!loading && visible.length === 0 && !error && (
        <div className="rounded-md border border-border bg-card px-4 py-6 text-center text-sm text-muted-foreground">
          No sent messages yet. Approve a draft on the Action Board to send your first.
        </div>
      )}
      {visible.length > 0 && (
        <div className="overflow-hidden rounded-md border border-border bg-card">
          <table className="w-full text-sm">
            <thead className="bg-foreground/[0.03] text-[0.68rem] font-mono-ui uppercase tracking-[0.06em] text-muted-foreground">
              <tr>
                <th className="px-3 py-2 text-left">When</th>
                <th className="px-3 py-2 text-left">Recipient</th>
                <th className="px-3 py-2 text-left">Source · transport</th>
                <th className="px-3 py-2 text-left">Message</th>
                <th className="px-3 py-2 text-left">Status</th>
              </tr>
            </thead>
            <tbody>
              {visible.map((it) => {
                const tone = sentStatusTone(it.status);
                const draft = String(it.payload?.draft_text || "").trim();
                const updatedAt = new Date(it.updatedAt);
                const updatedLabel = isNaN(updatedAt.getTime())
                  ? it.updatedAt
                  : updatedAt.toLocaleString();
                return (
                  <tr key={it.id} className="border-t border-border/50 align-top">
                    <td className="whitespace-nowrap px-3 py-2 font-mono-ui text-[0.72rem] tabular-nums text-muted-foreground">
                      {updatedLabel}
                    </td>
                    <td className="px-3 py-2 text-foreground">{sentRecipientLabel(it)}</td>
                    <td className="px-3 py-2 text-foreground/80">
                      <div>{it.sourceId}</div>
                      <div className="font-mono-ui text-[0.68rem] uppercase tracking-[0.06em] text-muted-foreground">
                        {sentTransportLabel(it)}
                      </div>
                    </td>
                    <td className="max-w-[40ch] px-3 py-2 text-foreground/85">
                      <div className="line-clamp-2 whitespace-pre-wrap">{draft || <span className="text-muted-foreground">(empty)</span>}</div>
                      {it.providerMessageId && (
                        <div className="mt-1 font-mono-ui text-[0.66rem] text-muted-foreground">
                          id: {it.providerMessageId}
                        </div>
                      )}
                      {it.lastError && (
                        <div className="mt-1 text-[0.7rem] text-warning">{it.lastError}</div>
                      )}
                    </td>
                    <td className="whitespace-nowrap px-3 py-2">
                      <Badge
                        variant={
                          tone === "success"
                            ? "success"
                            : tone === "warning"
                              ? "warning"
                              : tone === "danger"
                                ? "destructive"
                                : "secondary"
                        }
                      >
                        {it.status}
                        {it.attempts > 0 && ` · ${it.attempts}×`}
                      </Badge>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

export function RealEstateLeadsPage() {
  const data = useRealEstateHubData();
  useHubHeader("Leads", data);
  const [sourceFilter, setSourceFilter] = useState<string | null>(null);
  const [tab, setTab] = useState<LeadTab>("action-board");
  const leadsSetup = useLeadsSetup();
  const [forceOnboarding, setForceOnboarding] = useState(false);
  const showOnboarding = !leadsSetup.loading && !!leadsSetup.setup && (!leadsSetup.setup.complete || forceOnboarding);
  const setupSnapshot = leadsSetup.setup;

  const allThreads = useMemo(() => data.sourceInbox?.threads ?? [], [data.sourceInbox?.threads]);
  const allDrafts = useMemo(() => data.sourceInbox?.drafts ?? [], [data.sourceInbox?.drafts]);
  const allProfiles = useMemo(() => data.sourceInbox?.profiles ?? [], [data.sourceInbox?.profiles]);
  const allSources = useMemo(() => data.sourceInbox?.sources ?? [], [data.sourceInbox?.sources]);

  const filterOptions = useMemo<LeadSourceOption[]>(() => {
    const seen = new Map<string, LeadSourceOption>();
    for (const source of allSources) {
      if (!source.connected && !source.importOnly) continue;
      seen.set(source.id, {
        id: source.id,
        label: source.label,
        drafts: 0,
        profiles: 0,
        threads: 0,
      });
    }
    for (const thread of allThreads) {
      const entry = seen.get(thread.sourceId);
      if (entry) entry.threads += 1;
    }
    for (const draft of allDrafts) {
      const entry = seen.get(draft.sourceId);
      if (entry) entry.drafts += 1;
    }
    for (const profile of allProfiles) {
      for (const sourceId of profile.sourceIds) {
        const entry = seen.get(sourceId);
        if (entry) entry.profiles += 1;
      }
    }
    return Array.from(seen.values()).filter(
      (option) => option.threads > 0 || option.drafts > 0 || option.profiles > 0,
    );
  }, [allDrafts, allProfiles, allSources, allThreads]);

  const filterFn = useCallback(
    (sourceId: string) => sourceFilter === null || sourceId === sourceFilter,
    [sourceFilter],
  );

  const threads = useMemo(
    () => allThreads.filter((thread) => filterFn(thread.sourceId)),
    [allThreads, filterFn],
  );
  const drafts = useMemo(
    () => allDrafts.filter((draft) => filterFn(draft.sourceId)),
    [allDrafts, filterFn],
  );
  const skippedDrafts = useMemo(
    () => (data.sourceInbox?.skippedDrafts ?? []).filter((draft) => filterFn(draft.sourceId)),
    [data.sourceInbox?.skippedDrafts, filterFn],
  );
  const profiles = useMemo(
    () => allProfiles.filter((profile) => sourceFilter === null || profile.sourceIds.includes(sourceFilter)),
    [allProfiles, sourceFilter],
  );
  const buyerSearches = useMemo(
    () =>
      (data.sourceInbox?.privateSearchBuyers ?? []).filter((buyer) => (
        sourceFilter === null || buyer.source === sourceFilter
      )),
    [data.sourceInbox?.privateSearchBuyers, sourceFilter],
  );

  const followUpJobs = data.cronJobs.filter((job) =>
    jobMatches(job, ["lead", "outreach", "follow-up", "follow up", "buyer", "seller"]),
  );
  const leadJobIds = new Set(followUpJobs.map((job) => job.id));
  const leadSessions = data.sessions.filter((session) => {
    if (sessionMatches(session, ["lead", "outreach", "buyer", "seller", "follow-up", "follow up"])) {
      return true;
    }
    if ((session.source ?? "") === "cron" && session.id?.startsWith("cron_")) {
      const jobIdGuess = session.id.replace(/^cron_/, "").split("_", 1)[0];
      return leadJobIds.has(jobIdGuess);
    }
    return false;
  });

  const leadBuckets = leadThreadBuckets(threads);
  const hotLeadThreads = leadSectionThreads(
    threads,
    data.sourceInbox,
    "hot",
    leadBuckets.hot,
  );
  const followUpThreads = leadSectionThreads(
    threads,
    data.sourceInbox,
    "follow_up",
    leadBuckets.followUp,
  );
  const useBackendLeadSections = sourceFilter === null;
  const hotLeads = useBackendLeadSections
    ? leadSectionCount(data.sourceInbox, "hot", hotLeadThreads.length)
    : hotLeadThreads.length;
  const followUpThreadCount = useBackendLeadSections
    ? leadSectionCount(data.sourceInbox, "follow_up", followUpThreads.length)
    : followUpThreads.length;
  const buyerSearchCount = useBackendLeadSections
    ? leadSectionCount(data.sourceInbox, "buyer_search", buyerSearches.length)
    : buyerSearches.length;
  const skippedCount = useBackendLeadSections
    ? leadSectionCount(data.sourceInbox, "skipped", skippedDrafts.length)
    : skippedDrafts.length;
  const sectionCounts = {
    hot: hotLeads,
    followUp: followUpThreadCount,
    buyerSearch: buyerSearchCount,
    skipped: skippedCount,
  };
  const blockedSources = allSources.filter((source) => source.blocked);
  const pulse = useMemo(() => computeResponsePulse(threads), [threads]);

  const refresh = data.refresh;
  const shellIcon =
    tab === "profiles" ? Users
      : tab === "templates" ? BookText
      : tab === "sent" ? Send
      : Radar;
  const shellTitle =
    tab === "profiles"
      ? "Lead profiles."
      : tab === "templates"
        ? "Lead templates."
        : tab === "sent"
          ? "Sent messages."
          : "Lead action board.";

  return (
    <ThreadDrawerProvider data={data}>
    <HubShell
      data={data}
      eyebrow="Lead Desk"
      icon={shellIcon}
      title={shellTitle}
    >
      <div className="flex w-full flex-col gap-5">
        {leadsSetup.loading ? (
          <div className="rounded-md border border-border bg-card px-4 py-6 text-sm text-muted-foreground">
            Loading leads onboarding…
          </div>
        ) : leadsSetup.error ? (
          <div className="rounded-md border border-warning/40 bg-warning/10 px-4 py-3 text-sm text-foreground">
            Could not load leads setup: {leadsSetup.error}
          </div>
        ) : showOnboarding && setupSnapshot ? (
          <LeadsSetupLaunch
            setup={setupSnapshot}
            onSetupUpdated={(next) => leadsSetup.setSetup(next)}
            forceOnboarding={forceOnboarding}
            onForceOnboardingDone={() => setForceOnboarding(false)}
          />
        ) : (
        <>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <LeadsTabBar active={tab} onChange={setTab} />
            {setupSnapshot?.complete && (
              <Button
                type="button"
                variant="ghost"
                size="sm"
                className="h-8 px-2 text-[11px] uppercase tracking-wide text-muted-foreground hover:text-foreground"
                onClick={() => setForceOnboarding(true)}
              >
                Re-run onboarding
              </Button>
            )}
          </div>
          {tab === "profiles" && (
            <span className="text-xs text-foreground/70">
              A searchable source-filtered list of people, separate from the action board.
            </span>
          )}
          {tab === "templates" && (
            <span className="text-xs text-foreground/70">
              Templates control what the agent says. Edits apply on the next lane run.
            </span>
          )}
          {tab === "sent" && (
            <span className="text-xs text-foreground/70">
              Outbound history. Every message you approved on the Action Board lands here.
            </span>
          )}
        </div>

        {tab === "templates" ? (
          <div id="leads-panel-templates" role="tabpanel" aria-labelledby="leads-tab-templates">
            <TemplatesPanel />
          </div>
        ) : tab === "sent" ? (
          <div id="leads-panel-sent" role="tabpanel" aria-labelledby="leads-tab-sent">
            <SentMessagesBoard filterSourceId={sourceFilter} />
          </div>
        ) : (
          <>
            <LeadFilterBar
              active={sourceFilter}
              buyerSearches={buyerSearchCount}
              drafts={drafts.length}
              followUps={followUpThreadCount}
              hot={hotLeads}
              onSelect={setSourceFilter}
              options={filterOptions}
              pulse={pulse}
              profiles={profiles.length}
              skipped={skippedCount}
              threads={threads.length}
            />

            {blockedSources.length > 0 && (
              <div className="rounded-md border border-border bg-card px-4 py-3 text-sm text-foreground">
                <div className="flex items-center gap-2 text-warning">
                  <AlertTriangle className="h-4 w-4" />
                  <span className="font-semibold">A lead source needs access.</span>
                </div>
                <div className="mt-2 space-y-1.5 text-xs text-foreground/75">
                  {blockedSources.slice(0, 3).map((source) => (
                    <div key={source.id}>
                      <span className="font-medium text-foreground">{source.label}: </span>
                      {source.nextOperatorStep || source.lastError || "Open Settings and reconnect this source."}
                    </div>
                  ))}
                  <Link
                    to="/config#composio"
                    className={cn(buttonVariants({ variant: "outline", size: "sm" }), "mt-2 h-9 px-3")}
                  >
                    Open Settings
                  </Link>
                </div>
              </div>
            )}

            {tab === "profiles" ? (
              <LeadProfilesListPage
                onChanged={(nextInbox) => {
                  if (nextInbox) {
                    data.setSourceInbox(nextInbox);
                  } else {
                    void refresh();
                  }
                }}
                profiles={profiles}
                threads={threads}
              />
            ) : (
              <section
                id="leads-panel-action-board"
                role="tabpanel"
                aria-labelledby="leads-tab-action-board"
                className="space-y-5"
              >
                <div className="grid gap-4 2xl:grid-cols-[minmax(0,1.55fr)_minmax(0,1fr)]">
                  <DraftMessagesBoard
                    data={data}
                    drafts={drafts}
                    keyboard
                    pageSize={12}
                    showOpenThread={false}
                    title="Approve replies"
                    emptyMessage={
                      sourceFilter
                        ? "No drafts waiting from this source. Switch the filter or wait for the next agent run."
                        : "Inbox zero on drafts. New approvals will land here as your agent generates replies."
                    }
                  />

                  <div className="flex flex-col gap-4">
                    <LeadPipelineBoard
                      buyers={buyerSearches}
                      data={data}
                      sectionCounts={sectionCounts}
                      skippedDrafts={skippedDrafts}
                      threads={threads}
                    />
                  </div>
                </div>

                <CollapsibleSection
                  title="Channels"
                  description="Connected sources, profiles, and routing."
                >
                  <ChannelsPanel
                    profiles={data.sourceInbox?.profiles ?? []}
                    sources={allSources}
                    threads={allThreads}
                  />
                </CollapsibleSection>

                <CollapsibleSection
                  title="Outreach automations"
                  description="Scheduled lanes: outreach, hot leads, follow-ups, PCS. Edit any from /cron."
                >
                  <OutreachLanesGrid cronJobs={data.cronJobs} onChanged={refresh} />
                </CollapsibleSection>

                <CollapsibleSection
                  title="Lead activity"
                  count={leadSessions.length}
                  description="What the agent just did across your inbox."
                >
                  <RecentSessions
                    title="Recent agent runs"
                    sessions={leadSessions}
                    empty="No agent activity yet. Once a lane runs, its sessions will surface here."
                  />
                </CollapsibleSection>

                <CollapsibleSection
                  title="Other automations"
                  count={followUpJobs.length}
                  description="Other lead-related schedules from /cron, beyond the outreach lanes above."
                >
                  <TimedTasks
                    jobs={followUpJobs}
                    empty="No additional schedules yet. Add custom ones from /cron."
                    title="Lead schedules"
                  />
                </CollapsibleSection>
              </section>
            )}
          </>
        )}
        </>
        )}
      </div>
    </HubShell>
    </ThreadDrawerProvider>
  );
}

export { RealEstateAdminPage } from "@/pages/real-estate-hub/admin";

export { RealEstateMemoryPage } from "@/pages/real-estate-hub/memory";
export { RealEstateSocialMediaPage } from "@/pages/real-estate-hub/social";
export { RealEstateTasksPage } from "@/pages/real-estate-hub/tasks";

```

---
## `src/pages/RealEstateTemplatesPage.tsx`
```tsx
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
      <Badge variant="outline">{lane}</Badge>
      <Badge variant="secondary">{channel}</Badge>
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
      <span className="font-mono-ui text-[0.68rem] uppercase tracking-[0.06em] text-muted-foreground">
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
            <span className="font-mono-ui text-[0.68rem] uppercase tracking-[0.06em] text-muted-foreground">
              v{row.version}
              {row.versionCount > 1 ? ` · ${row.versionCount} versions` : ""}
            </span>
          </div>
          <LaneChannelBadges lane={row.lane} channel={row.channel} />
        </div>
        <div className="flex items-center gap-1">
          {bucket === "trial" && (
            <Badge variant="warning">Trial</Badge>
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
          <Badge variant="outline">{ORIGIN_LABEL[template.origin] ?? template.origin}</Badge>
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
          <span className="font-mono-ui text-[0.68rem] uppercase tracking-[0.06em] text-muted-foreground">
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
        <Badge variant="destructive">
          {template.status === "rejected" ? "Rejected" : "Retired"}
        </Badge>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <p className="whitespace-pre-wrap text-sm leading-relaxed text-foreground/70">
          {template.body}
        </p>
        {template.rationale && (
          <p className="text-xs italic text-muted-foreground/85">
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
    <p className="px-1 py-1 text-xs text-muted-foreground/80">
      {title}. {hint}
    </p>
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
      <span className="font-mono-ui text-[0.68rem] uppercase tracking-[0.06em] text-muted-foreground">
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
        <div className="flex items-start gap-2 rounded-md border border-border bg-card px-4 py-3 text-sm text-destructive">
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
      <span className="font-mono-ui text-[0.68rem] uppercase tracking-[0.06em] text-muted-foreground">
        {label}
      </span>
      <span className="text-xs text-muted-foreground/85">{hint}</span>
    </header>
  );
}


```

---
## `src/pages/real-estate-hub/_shared/action-board.tsx`
```tsx
import { Link } from "react-router-dom";
import { Badge } from "@/components/ui/badge";
import { buttonVariants } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import type { BoardAction } from "./types";

export function ActionBoard({
  actions,
  empty,
  title,
}: {
  actions: BoardAction[];
  empty: string;
  title: string;
}) {
  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between gap-3">
          <CardTitle>{title}</CardTitle>
          <Badge variant={actions.length ? "warning" : "success"}>{actions.length}</Badge>
        </div>
      </CardHeader>
      <CardContent className="divide-y divide-border/40">
        {actions.length ? (
          actions.slice(0, 8).map((action) => {
            const Icon = action.icon;
            return (
              <div
                key={action.id}
                className="flex items-start gap-3 py-3 first:pt-0 last:pb-0"
              >
                <span className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-primary/10 text-primary ring-1 ring-primary/20">
                  <Icon className="h-4 w-4" />
                </span>
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <div className="min-w-0 flex-1 truncate text-sm font-semibold text-foreground">
                      {action.title}
                    </div>
                    <Badge variant={action.variant ?? "outline"}>{action.status}</Badge>
                  </div>
                  <p className="mt-1 line-clamp-2 text-xs leading-5 text-muted-foreground">
                    {action.detail}
                  </p>
                  <div className="mt-2 flex items-center justify-between gap-3">
                    <span className="truncate text-[0.72rem] text-muted-foreground">{action.meta}</span>
                    <Link
                      className={cn(buttonVariants({ variant: "outline", size: "sm" }), "h-7 px-2.5")}
                      to={action.to}
                    >
                      Open
                    </Link>
                  </div>
                </div>
              </div>
            );
          })
        ) : (
          <p className="px-1 py-1 text-xs text-muted-foreground/80">{empty}</p>
        )}
      </CardContent>
    </Card>
  );
}

```

---
## `src/pages/real-estate-hub/_shared/agent-widgets.tsx`
```tsx
import { useState } from "react";
import { Link } from "react-router-dom";
import {
  Activity,
  AlertTriangle,
  Bot,
  Brain,
  Check,
  Clock,
  Loader2,
  MessageSquare,
  Play,
  Repeat,
  XCircle,
  Zap,
} from "lucide-react";
import {
  api,
  type AdminActionRun,
  type AdminDealTask,
  type AgentHubSnapshot,
  type CronJob,
  type SessionInfo,
} from "@/lib/api";
import { cn, isoTimeAgo, timeAgo } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { HubMetric } from "./hub-metric";

type AdminRunTone = "default" | "secondary" | "destructive" | "outline" | "success" | "warning";
export type AdminRunBusy = { id: string; action: "approve" | "cancel" } | null;

export function sessionTitle(session: SessionInfo): string {
  const title = session.title?.trim();
  if (title && title !== "Untitled") return title;
  return session.preview?.trim() || "Untitled chat";
}

export function adminRunStatusVariant(
  status: string,
): "default" | "secondary" | "destructive" | "outline" | "success" | "warning" {
  if (status === "succeeded" || status === "completed") return "success";
  if (status === "failed" || status === "cancelled") return "destructive";
  if (status === "waiting_human" || status === "waiting_external") return "warning";
  if (status === "running" || status === "queued") return "secondary";
  return "outline";
}

function adminRunRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : {};
}

function adminRunText(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}

function adminRunList(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((item) => {
    if (typeof item === "string" && item.trim()) return [item.trim()];
    const record = adminRunRecord(item);
    const label =
      adminRunText(record.label) ||
      adminRunText(record.name) ||
      adminRunText(record.key) ||
      adminRunText(record.field);
    return label ? [label] : [];
  });
}

function adminRunPrompt(run: AdminActionRun): Record<string, unknown> {
  const direct = adminRunRecord(run.humanPrompt);
  if (Object.keys(direct).length > 0) return direct;
  const resultPrompt = adminRunRecord(adminRunRecord(run.result).humanPrompt);
  return resultPrompt;
}

function adminRunTitle(run: AdminActionRun): string {
  const prompt = adminRunPrompt(run);
  return (
    adminRunText(prompt.title) ||
    adminRunText(prompt.question) ||
    adminRunText(prompt.summary) ||
    run.registryName ||
    run.skill ||
    "Admin run"
  );
}

function adminRunMessage(run: AdminActionRun): string {
  const prompt = adminRunPrompt(run);
  return (
    adminRunText(prompt.message) ||
    adminRunText(prompt.body) ||
    adminRunText(prompt.prompt) ||
    adminRunText(prompt.decisionNeeded) ||
    adminRunText(prompt.reason)
  );
}

function adminRunRequiredFields(run: AdminActionRun): string[] {
  const prompt = adminRunPrompt(run);
  const fields = [
    ...adminRunList(prompt.requiredFields),
    ...adminRunList(prompt.missingFields),
    ...adminRunList(prompt.inputsNeeded),
    ...adminRunList(prompt.fields),
  ];
  return Array.from(new Set(fields)).slice(0, 10);
}

function adminRunDeliveryInfo(run: AdminActionRun): { label: string; detail: string; variant: AdminRunTone } {
  const delivery = adminRunRecord(adminRunRecord(run.payload).delivery);
  if (Object.keys(delivery).length > 0) {
    const deliver = adminRunText(delivery.deliver) || "local";
    const channel = deliver.startsWith("telegram") ? "Telegram" : "Delivery";
    const attempted = delivery.attempted === true;
    const ok = delivery.ok === true;
    const error = adminRunText(delivery.error);
    const suppressed = adminRunText(delivery.suppressedReason);
    if (ok) {
      return { label: `${channel} notified`, detail: deliver, variant: "success" };
    }
    if (attempted && error) {
      return { label: `${channel} failed`, detail: error, variant: "destructive" };
    }
    if (suppressed) {
      return { label: `${channel} skipped`, detail: suppressed.replace(/_/g, " "), variant: "outline" };
    }
    return { label: `${channel} not sent`, detail: deliver, variant: "warning" };
  }
  if (run.cronJobId) {
    return {
      label: "Telegram pending",
      detail: "Cron will record delivery after the Admin response.",
      variant: "outline",
    };
  }
  return {
    label: "UI queue only",
    detail: "No cron delivery is attached to this run yet.",
    variant: "outline",
  };
}

function handoffStatusVariant(status: string): "success" | "warning" | "outline" | "secondary" | "destructive" {
  if (status === "completed" || status === "succeeded") return "success";
  if (status === "failed") return "destructive";
  if (status === "waiting_human") return "warning";
  if (status === "queued" || status === "running") return "warning";
  return "outline";
}

export function RecentSessions({
  empty,
  sessions,
  title,
}: {
  empty: string;
  sessions: SessionInfo[];
  title: string;
}) {
  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between gap-3">
          <CardTitle>{title}</CardTitle>
          <Badge variant="outline">{sessions.length}</Badge>
        </div>
      </CardHeader>
      <CardContent className="divide-y divide-border/40">
        {sessions.length ? (
          sessions.slice(0, 6).map((session) => (
            <div
              key={session.id}
              className="flex items-center gap-3 py-3 first:pt-0 last:pb-0"
            >
              <span
                className={cn(
                  "h-2.5 w-2.5 shrink-0 rounded-full",
                  session.is_active ? "bg-success" : "bg-muted-foreground/40",
                )}
              />
              <div className="min-w-0 flex-1">
                <div className="truncate text-sm font-medium text-foreground">
                  {sessionTitle(session)}
                </div>
                <div className="mt-0.5 flex flex-wrap gap-2 text-[0.72rem] text-muted-foreground">
                  <span>{session.source ?? "local"}</span>
                  <span>{timeAgo(session.last_active)}</span>
                  <span>{session.message_count} messages</span>
                </div>
              </div>
              <Badge variant="outline">{session.tool_call_count} tools</Badge>
            </div>
          ))
        ) : (
          <p className="px-1 py-1 text-xs text-muted-foreground/80">{empty}</p>
        )}
      </CardContent>
    </Card>
  );
}

export function TimedTasks({
  empty = "No timed tasks match this area yet.",
  jobs,
  title = "Timed tasks",
}: {
  empty?: string;
  jobs: CronJob[];
  title?: string;
}) {
  const automationBadge = (job: CronJob) => {
    if (job.last_error) return { label: "error", variant: "warning" as const };
    if (job.alignment_status === "blocked") return { label: "blocked", variant: "warning" as const };
    if (job.alignment_status === "optional") return { label: "optional", variant: "outline" as const };
    if (job.alignment_status === "legacy") return { label: "legacy", variant: "warning" as const };
    if (job.enabled) return { label: job.state || "scheduled", variant: "success" as const };
    return { label: job.state || "paused", variant: "outline" as const };
  };

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between gap-3">
          <CardTitle>{title}</CardTitle>
          <Badge variant="outline">{jobs.length}</Badge>
        </div>
      </CardHeader>
      <CardContent className="divide-y divide-border/40">
        {jobs.length ? (
          jobs.slice(0, 6).map((job) => (
            <div
              key={job.id}
              className="grid gap-1.5 py-3 first:pt-0 last:pb-0"
            >
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="truncate text-sm font-medium text-foreground">
                    {job.name || job.prompt.slice(0, 70)}
                  </div>
                  <div className="mt-0.5 text-[0.72rem] text-muted-foreground">
                    {job.schedule_display || job.schedule.display}
                  </div>
                </div>
                {(() => {
                  const badge = automationBadge(job);
                  return <Badge variant={badge.variant}>{badge.label}</Badge>;
                })()}
              </div>
              <div className="flex flex-wrap gap-2 text-[0.72rem] text-muted-foreground">
                <span>{job.deliver ?? "local"}</span>
                {job.next_run_at && <span>Next {isoTimeAgo(job.next_run_at)}</span>}
                {!job.enabled && !job.next_run_at && <span>Paused</span>}
                {job.last_error && <span className="text-destructive">Error</span>}
              </div>
              {(job.paused_reason || job.alignment_reason || job.last_error) && (
                <p className="line-clamp-2 text-[0.72rem] leading-5 text-muted-foreground">
                  {job.paused_reason || job.alignment_reason || job.last_error}
                </p>
              )}
            </div>
          ))
        ) : (
          <p className="px-1 py-1 text-xs text-muted-foreground/80">{empty}</p>
        )}
      </CardContent>
    </Card>
  );
}

export function AdminDealTasks({
  empty = "No transaction tasks need attention.",
  onChanged,
  tasks,
  title = "Transaction tasks",
}: {
  empty?: string;
  onChanged?: () => Promise<void> | void;
  tasks: AdminDealTask[];
  title?: string;
}) {
  const [runningTaskId, setRunningTaskId] = useState<string | null>(null);
  const runTask = async (task: AdminDealTask) => {
    if (!task.canRunWithAi || !task.skill || runningTaskId) return;
    setRunningTaskId(task.id);
    try {
      await api.runAdminDealTask({
        dealId: task.dealId,
        skill: task.skill,
        title: task.title,
        sourceTaskId: task.id,
        runNow: true,
      });
      await onChanged?.();
    } finally {
      setRunningTaskId(null);
    }
  };
  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between gap-3">
          <CardTitle>{title}</CardTitle>
          <Badge variant={tasks.length ? "warning" : "outline"}>{tasks.length}</Badge>
        </div>
      </CardHeader>
      <CardContent className="divide-y divide-border/40">
        {tasks.length ? (
          tasks.slice(0, 10).map((task) => (
            <div key={task.id} className="grid gap-2 py-3 first:pt-0 last:pb-0">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="flex min-w-0 flex-wrap items-center gap-1.5">
                    <span className="truncate text-sm font-medium text-foreground">{task.title}</span>
                    {task.canRunWithAi && (
                      <Badge variant="success" className="gap-1">
                        <Bot className="h-3 w-3" />
                        AI
                      </Badge>
                    )}
                  </div>
                  <div className="mt-1 flex flex-wrap gap-2 text-[0.72rem] text-muted-foreground">
                    <span>{task.dealTitle}</span>
                    <span>{task.side}</span>
                    <span>{task.stageName || `Stage ${task.currentStage + 1}`}</span>
                    {task.skill && <span>{task.skill}</span>}
                  </div>
                </div>
                <Badge variant={adminRunStatusVariant(task.status)}>{task.status.replace(/_/g, " ")}</Badge>
              </div>
              {task.description && (
                <div className="text-[0.76rem] leading-5 text-muted-foreground">{task.description}</div>
              )}
              <div className="flex flex-wrap justify-end gap-2">
                {task.canRunWithAi && task.skill && task.status === "available" && (
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={runningTaskId !== null}
                    onClick={() => void runTask(task)}
                  >
                    {runningTaskId === task.id ? (
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    ) : (
                      <Play className="h-3.5 w-3.5" />
                    )}
                    Run AI
                  </Button>
                )}
                <Link
                  to={`/admin?deal=${encodeURIComponent(task.dealId)}`}
                  className="inline-flex h-9 items-center rounded-md px-2 font-mono-ui text-[0.68rem] font-semibold uppercase tracking-[0.12em] text-primary hover:text-primary/80"
                >
                  Open deal
                </Link>
              </div>
            </div>
          ))
        ) : (
          <p className="px-1 py-1 text-xs text-muted-foreground/80">{empty}</p>
        )}
      </CardContent>
    </Card>
  );
}

export function AdminActionRuns({
  empty = "No Admin action runs yet.",
  onChanged,
  runs,
  title = "Admin action runs",
}: {
  empty?: string;
  onChanged?: () => Promise<void> | void;
  runs: AdminActionRun[];
  title?: string;
}) {
  const [busyRun, setBusyRun] = useState<AdminRunBusy>(null);
  const resolveRun = async (run: AdminActionRun, approved: boolean) => {
    if (busyRun || run.status !== "waiting_human") return;
    setBusyRun({ id: run.id, action: approved ? "approve" : "cancel" });
    try {
      await api.approveAdminActionRun(run.id, { approved, runNow: approved });
      await onChanged?.();
    } finally {
      setBusyRun(null);
    }
  };
  const visibleRuns = [...runs]
    .sort((a, b) => {
      if (a.status === "waiting_human" && b.status !== "waiting_human") return -1;
      if (a.status !== "waiting_human" && b.status === "waiting_human") return 1;
      return new Date(b.updatedAt).getTime() - new Date(a.updatedAt).getTime();
    })
    .slice(0, 12);
  const waitingCount = runs.filter((run) => run.status === "waiting_human").length;
  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between gap-3">
          <div>
            <CardTitle>{title}</CardTitle>
            <p className="mt-1 text-xs leading-5 text-muted-foreground">
              Human-gated Admin work that needs a decision before the pipeline can move.
            </p>
          </div>
          <div className="flex shrink-0 flex-wrap justify-end gap-1.5">
            {waitingCount > 0 && <Badge variant="warning">{waitingCount} waiting</Badge>}
            <Badge variant={runs.some((run) => ["failed", "waiting_human"].includes(run.status)) ? "warning" : "outline"}>
              {runs.length}
            </Badge>
          </div>
        </div>
      </CardHeader>
      <CardContent className="grid gap-2">
        {visibleRuns.length ? (
          visibleRuns.map((run) => (
            <AdminRunDecisionRow
              key={run.id}
              busyRun={busyRun}
              run={run}
              onApprove={() => void resolveRun(run, true)}
              onCancel={() => void resolveRun(run, false)}
            />
          ))
        ) : (
          <p className="px-1 py-1 text-xs text-muted-foreground/80">{empty}</p>
        )}
      </CardContent>
    </Card>
  );
}

export function AgentHandoffsCard({
  handoffs,
}: {
  handoffs?: AgentHubSnapshot["handoffs"];
}) {
  const recent = handoffs?.recent ?? [];
  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between gap-3">
          <div>
            <CardTitle>Agent handoffs</CardTitle>
            <p className="mt-1 text-xs leading-5 text-muted-foreground">
              Cross-agent work moving through the local orchestration bus.
            </p>
          </div>
          <Badge variant={(handoffs?.open ?? 0) > 0 ? "warning" : "outline"}>
            {handoffs?.open ?? 0} open
          </Badge>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="grid grid-cols-3 gap-2">
          <HubMetric icon={Clock} label="Queued" value={handoffs?.queued ?? 0} />
          <HubMetric icon={Bot} label="Running" value={handoffs?.running ?? 0} />
          <HubMetric icon={AlertTriangle} label="Human" value={handoffs?.waitingHuman ?? 0} />
        </div>
        <div className="divide-y divide-border/40">
          {recent.length ? (
            recent.slice(0, 6).map((handoff) => (
              <div key={handoff.id} className="grid gap-1.5 py-3 first:pt-0 last:pb-0">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="truncate text-sm font-medium text-foreground">
                      {handoff.title}
                    </div>
                    <div className="mt-0.5 flex flex-wrap gap-2 text-[0.72rem] text-muted-foreground">
                      <span>{handoff.fromAgentId}</span>
                      <span>to</span>
                      <span>{handoff.toAgentId}</span>
                      <span>{isoTimeAgo(handoff.updatedAt)}</span>
                    </div>
                  </div>
                  <Badge variant={handoffStatusVariant(String(handoff.status))}>
                    {String(handoff.status).replace(/_/g, " ")}
                  </Badge>
                </div>
              </div>
            ))
          ) : (
            <p className="px-1 py-1 text-xs text-muted-foreground/80">No handoffs yet.</p>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

export function AgentWorkerCard({
  memory,
  worker,
}: {
  memory?: AgentHubSnapshot["memory"];
  worker?: AgentHubSnapshot["agentWorker"];
}) {
  const heartbeat = worker?.heartbeat;
  const wake = worker?.wake;
  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between gap-3">
          <div>
            <CardTitle>Wake loop</CardTitle>
            <p className="mt-1 text-xs leading-5 text-muted-foreground">
              The local worker that drains handoffs, heartbeats, and queued agent work.
            </p>
          </div>
          <Badge variant={worker?.enabled ? "success" : "outline"}>
            {worker?.state ?? "unknown"}
          </Badge>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="grid grid-cols-2 gap-2">
          <HubMetric icon={Repeat} label="Handoffs drained" value={worker?.drained.handoffs ?? 0} />
          <HubMetric icon={Activity} label="Admin runs" value={worker?.drained.adminRuns ?? 0} />
          <HubMetric icon={Brain} label="Memory queue" value={memory?.journal.pending ?? 0} />
          <HubMetric icon={Zap} label="Wake count" value={wake?.count ?? 0} />
        </div>
        <div className="rounded-md border border-border/55 bg-background/35 p-3 text-xs leading-5 text-muted-foreground">
          <div className="font-semibold text-foreground">
            {worker?.loop?.running ? "Loop running" : "Loop idle"}
          </div>
          <div className="mt-1">
            Heartbeat {heartbeat?.enabled ? "enabled" : "disabled"}
            {heartbeat?.nextBeatAt ? ` - next ${isoTimeAgo(heartbeat.nextBeatAt)}` : ""}
          </div>
          <div className="mt-1">
            Wake {wake?.pending ? "pending" : "clear"}
            {wake?.lastReason ? ` - ${wake.lastReason}` : ""}
          </div>
          {worker?.lastError && <div className="mt-2 text-destructive">{worker.lastError}</div>}
        </div>
      </CardContent>
    </Card>
  );
}

export function AdminRunDecisionRow({
  busyRun,
  compact = false,
  onApprove,
  onCancel,
  run,
}: {
  busyRun: AdminRunBusy;
  compact?: boolean;
  onApprove: () => void;
  onCancel: () => void;
  run: AdminActionRun;
}) {
  const waiting = run.status === "waiting_human";
  const message = adminRunMessage(run);
  const requiredFields = adminRunRequiredFields(run);
  const delivery = adminRunDeliveryInfo(run);
  const busyAction = busyRun?.id === run.id ? busyRun.action : null;
  return (
    <div
      className={cn(
        "rounded-lg border px-3 py-2.5",
        waiting ? "border-warning/35 bg-warning/10" : "border-border/45 bg-background/30",
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="text-sm font-medium leading-5 text-foreground">{adminRunTitle(run)}</div>
          <div className="mt-1 flex flex-wrap gap-x-2 gap-y-1 text-[0.72rem] text-muted-foreground">
            <span>{run.skill ?? "admin"}</span>
            <span>Deal {run.dealId.slice(0, 8)}</span>
            {run.cronJobId && <span>Cron {run.cronJobId.slice(0, 8)}</span>}
            <span>{isoTimeAgo(run.updatedAt)}</span>
          </div>
        </div>
        <Badge variant={adminRunStatusVariant(run.status)}>{run.status.replace(/_/g, " ")}</Badge>
      </div>

      {message && (
        <p className={cn("mt-2 text-[0.78rem] leading-5 text-foreground/85", !waiting && "line-clamp-3")}>
          {message}
        </p>
      )}

      {requiredFields.length > 0 && waiting && (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {requiredFields.map((field) => (
            <span
              key={field}
              className="inline-flex max-w-full items-center rounded-full border border-warning/25 bg-background/40 px-2 py-0.5 text-[0.68rem] text-warning"
            >
              <span className="truncate">{field}</span>
            </span>
          ))}
        </div>
      )}

      {run.errorMessage && (
        <div className="mt-2 rounded-md border border-destructive/25 bg-destructive/10 px-2 py-1.5 text-[0.72rem] leading-5 text-destructive">
          {run.errorMessage}
        </div>
      )}

      <div className={cn("mt-2 flex flex-wrap items-center justify-between gap-2", compact && "items-start")}>
        <div className="flex min-w-0 items-center gap-1.5 text-[0.72rem] text-muted-foreground" title={delivery.detail}>
          <MessageSquare className="h-3.5 w-3.5 shrink-0" />
          <Badge variant={delivery.variant}>{delivery.label}</Badge>
          {!compact && <span className="min-w-0 truncate">{delivery.detail}</span>}
        </div>
        {waiting && (
          <div className="flex shrink-0 flex-wrap justify-end gap-1.5">
            <Button size="sm" variant="outline" disabled={busyRun !== null} onClick={onCancel}>
              {busyAction === "cancel" ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <XCircle className="h-3.5 w-3.5" />
              )}
              Needs revision
            </Button>
            <Button size="sm" disabled={busyRun !== null} onClick={onApprove}>
              {busyAction === "approve" ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <Check className="h-3.5 w-3.5" />
              )}
              Approve and run
            </Button>
          </div>
        )}
      </div>
    </div>
  );
}

```

---
## `src/pages/real-estate-hub/_shared/contact-overview-board.tsx`
```tsx
import type { SourceInboxProfile } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import { contactBuckets, heatVariant, profileWhen } from "@/pages/real-estate-hub/utils";
import type { HubData } from "./types";

function ContactProfileRow({ profile }: { profile: SourceInboxProfile }) {
  return (
    <div className="rounded-md border border-border/55 bg-background/35 px-3 py-3">
      <div className="flex min-w-0 items-start gap-3">
        <span
          className={cn(
            "mt-1 h-2.5 w-2.5 shrink-0 rounded-full",
            profile.heatLabel === "hot" ? "bg-warning" : profile.heatLabel === "warm" ? "bg-success" : "bg-muted-foreground/45",
          )}
        />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <div className="min-w-0 flex-1 truncate text-sm font-semibold text-foreground">
              {profile.displayName}
            </div>
            <Badge variant={profile.hasCrm ? "success" : profile.isPotentialLead ? "warning" : "outline"}>
              {profile.hasCrm ? "CRM" : profile.isPotentialLead ? "potential" : "conversation"}
            </Badge>
          </div>
          <p className="mt-1 line-clamp-2 text-xs leading-5 text-muted-foreground">
            {profile.latestText || "No recent context yet."}
          </p>
          <div className="mt-2 flex flex-wrap items-center gap-1.5">
            <Badge variant={heatVariant(profile)}>
              {profile.heatLabel} {profile.heatScore}
            </Badge>
            {profile.crmStage && <Badge variant="outline">{profile.crmStage}</Badge>}
            {profile.leadSource && <Badge variant="outline">{profile.leadSource}</Badge>}
            {profile.sources.slice(0, 2).map((source) => (
              <Badge key={source} variant="outline">{source}</Badge>
            ))}
            {profile.channels.slice(0, 2).map((channel) => (
              <Badge key={channel} variant="outline">{channel}</Badge>
            ))}
            <Badge variant="outline">{profileWhen(profile)}</Badge>
          </div>
        </div>
      </div>
    </div>
  );
}

function ContactColumn({
  empty,
  profiles,
  title,
}: {
  empty: string;
  profiles: SourceInboxProfile[];
  title: string;
}) {
  return (
    <div className="min-w-0">
      <div className="mb-2 flex items-center justify-between gap-2">
        <div className="text-xs font-semibold text-muted-foreground">{title}</div>
        <Badge variant={profiles.length ? "outline" : "secondary"}>{profiles.length}</Badge>
      </div>
      <div className="space-y-2">
        {profiles.length ? (
          profiles.map((profile) => <ContactProfileRow key={profile.id} profile={profile} />)
        ) : (
          <p className="px-1 py-1 text-xs text-muted-foreground/80">{empty}</p>
        )}
      </div>
    </div>
  );
}

export function ContactOverviewBoard({ data }: { data: HubData }) {
  const profiles = data.sourceInbox?.profiles ?? [];
  const buckets = contactBuckets(profiles);
  return (
    <Card>
      <CardHeader>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <CardTitle>Contact overview</CardTitle>
            <p className="mt-1 text-xs leading-5 text-muted-foreground">
              CRM contacts are the main source of truth. Conversations from Messages, SMS, email, and social attach when phone, email, or name matches.
            </p>
          </div>
          <Badge variant="outline">{profiles.length} people</Badge>
        </div>
      </CardHeader>
      <CardContent>
        <div className="grid gap-4 xl:grid-cols-[minmax(0,1.15fr)_minmax(0,0.9fr)_minmax(0,0.85fr)]">
          <ContactColumn
            title="CRM contacts"
            profiles={buckets.crmContacts}
            empty="No CRM contacts are synced yet. Lofty/FUB/CRM people will anchor this column."
          />
          <ContactColumn
            title="Current conversations"
            profiles={buckets.active}
            empty="No unmatched active conversations yet."
          />
          <ContactColumn
            title="Potential social leads"
            profiles={buckets.potential}
            empty="No out-of-CRM social leads yet. Facebook/Instagram DMs with buyer/seller language will appear here."
          />
        </div>
      </CardContent>
    </Card>
  );
}

```

---
## `src/pages/real-estate-hub/_shared/hub-metric.tsx`
```tsx
import type { ComponentType } from "react";

export function HubMetric({
  icon: Icon,
  label,
  value,
}: {
  icon: ComponentType<{ className?: string }>;
  label: string;
  value: string | number;
}) {
  return (
    <div className="rounded-md border border-border/70 bg-background/35 px-3 py-3">
      <div className="flex items-center gap-2 text-[0.72rem] text-muted-foreground">
        <Icon className="h-3.5 w-3.5" />
        <span>{label}</span>
      </div>
      <div className="mt-1 truncate text-lg font-semibold text-foreground">{value}</div>
    </div>
  );
}

```

---
## `src/pages/real-estate-hub/_shared/hub-shell.tsx`
```tsx
import type { ComponentType, ReactNode } from "react";
import { cn } from "@/lib/utils";
import { LoadingState } from "./loading-state";
import type { HubData } from "./types";

export function HubShell({
  children,
  data,
  eyebrow,
  icon: Icon,
  title,
}: {
  children: ReactNode;
  data: HubData;
  eyebrow: string;
  hero?: string;
  icon: ComponentType<{ className?: string }>;
  title: string;
}) {
  if (data.loading && !data.snapshot && !data.status) return <LoadingState />;

  const gatewayOnline = !!(data.snapshot?.gateway.running || data.status?.gateway_running);
  const activeJobs = data.cronJobs.filter((job) => job.enabled).length;

  return (
    <div className="real-estate-hub flex flex-col gap-4 pb-6">
      <section className="flex flex-wrap items-center justify-between gap-3 border-b border-border/60 pb-4">
        <div className="min-w-0 flex items-center gap-3">
          <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-primary/12 text-primary ring-1 ring-primary/25">
            <Icon className="h-4 w-4" />
          </span>
          <div className="min-w-0">
            <div className="font-mono-ui text-[0.68rem] uppercase tracking-[0.14em] text-muted-foreground font-semibold">
              {eyebrow}
            </div>
            <h1 className="text-xl font-semibold leading-tight text-foreground sm:text-[1.6rem]">
              {title}
            </h1>
          </div>
        </div>
        <div className="font-mono-ui flex items-center gap-2 text-[0.72rem] text-muted-foreground">
          <span
            className={cn(
              "inline-flex items-center gap-1.5 text-xs",
              gatewayOnline ? "text-muted-foreground" : "text-destructive",
            )}
          >
            <span
              className={cn("h-1.5 w-1.5 rounded-full", gatewayOnline ? "bg-success" : "bg-destructive")}
            />
            Agent {gatewayOnline ? "online" : "offline"}
          </span>
          <span className="inline-flex items-center gap-1.5 text-xs text-muted-foreground">
            <span className="h-1.5 w-1.5 rounded-full bg-muted-foreground/40" />
            {activeJobs} job{activeJobs === 1 ? "" : "s"}
          </span>
        </div>
        {data.error && (
          <div className="basis-full rounded-xl border border-warning/25 bg-warning/10 px-3 py-2 text-xs text-warning">
            {data.error}
          </div>
        )}
      </section>

      {children}
    </div>
  );
}

```

---
## `src/pages/real-estate-hub/_shared/lead-status-control.tsx`
```tsx
import { useState } from "react";
import { Loader2 } from "lucide-react";
import { Select, SelectOption } from "@/components/ui/select";
import { Badge } from "@/components/ui/badge";
import { api } from "@/lib/api";
import type { SourceInboxProfileStatus, SourceInboxResponse } from "@/lib/api";
import { cn } from "@/lib/utils";

const STATUS_OPTIONS: Array<{ value: SourceInboxProfileStatus | "none"; label: string }> = [
  { value: "none", label: "No status" },
  { value: "new_lead", label: "New Lead" },
  { value: "follow_up", label: "Follow Up" },
  { value: "ghosting", label: "Ghosting" },
  { value: "dead", label: "Dead" },
  { value: "closed_seller", label: "Closed Seller" },
  { value: "closed_buyer", label: "Closed Buyer" },
];

const STATUS_BADGE: Record<
  SourceInboxProfileStatus,
  { label: string; variant: "default" | "secondary" | "success" | "warning" | "destructive" | "outline" }
> = {
  new_lead: { label: "new lead", variant: "default" },
  follow_up: { label: "follow up", variant: "warning" },
  ghosting: { label: "ghosting", variant: "secondary" },
  dead: { label: "dead", variant: "destructive" },
  closed_seller: { label: "closed seller", variant: "success" },
  closed_buyer: { label: "closed buyer", variant: "success" },
};

export function LeadStatusBadge({ status }: { status: SourceInboxProfileStatus | null }) {
  if (!status) return null;
  const meta = STATUS_BADGE[status];
  if (!meta) return null;
  return <Badge variant={meta.variant}>{meta.label}</Badge>;
}

export function LeadStatusControl({
  profileId,
  status,
  onChanged,
  className,
  selectClassName = "w-40",
  selectButtonClassName,
  disabled = false,
}: {
  profileId: string;
  status: SourceInboxProfileStatus | null;
  onChanged?: (nextInbox?: SourceInboxResponse) => void | Promise<void>;
  className?: string;
  selectClassName?: string;
  selectButtonClassName?: string;
  disabled?: boolean;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleChange = async (next: string) => {
    if (busy || disabled) return;
    setBusy(true);
    setError(null);
    try {
      const value = next === "none" ? null : (next as SourceInboxProfileStatus);
      const nextInbox = await api.updateSourceInboxProfile(profileId, value);
      await onChanged?.(nextInbox);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className={cn("relative", className)}>
      <div className="flex items-center gap-1.5">
        {busy && <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin text-muted-foreground" aria-hidden />}
        <Select
          value={status ?? "none"}
          onValueChange={handleChange}
          disabled={busy || disabled}
          className={selectClassName}
          buttonClassName={selectButtonClassName}
        >
          {STATUS_OPTIONS.map((option) => (
            <SelectOption key={option.value} value={option.value}>
              {option.label}
            </SelectOption>
          ))}
        </Select>
      </div>
      {error && <p className="mt-1 text-[0.7rem] leading-4 text-destructive">{error}</p>}
    </div>
  );
}

```

---
## `src/pages/real-estate-hub/_shared/loading-state.tsx`
```tsx
import { Loader2 } from "lucide-react";

export function LoadingState() {
  return (
    <div className="flex min-h-[42vh] items-center justify-center">
      <Loader2 className="h-6 w-6 animate-spin text-primary" />
    </div>
  );
}

```

---
## `src/pages/real-estate-hub/_shared/use-hub-data.tsx`
```tsx
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { useLocation } from "react-router-dom";
import { RefreshCw } from "lucide-react";
import { api } from "@/lib/api";
import type {
  AdminActionRun,
  AdminDealTask,
  AgentHubSnapshot,
  CronJob,
  PaginatedSessions,
  SessionInfo,
  SourceInboxResponse,
  StatusResponse,
} from "@/lib/api";
import { Button } from "@/components/ui/button";
import { usePageHeader } from "@/contexts/usePageHeader";
import { cn } from "@/lib/utils";
import type { HubData } from "./types";

const SOURCE_INBOX_REFRESH_LIMIT = 500;

export function useRealEstateHubData(): HubData {
  const { pathname } = useLocation();
  const [snapshot, setSnapshot] = useState<AgentHubSnapshot | null>(null);
  const [status, setStatus] = useState<StatusResponse | null>(null);
  const [sourceInbox, setSourceInbox] = useState<SourceInboxResponse | null>(null);
  const [sessions, setSessions] = useState<SessionInfo[]>([]);
  const [cronJobs, setCronJobs] = useState<CronJob[]>([]);
  const [dealTasks, setDealTasks] = useState<AdminDealTask[]>([]);
  const [actionRuns, setActionRuns] = useState<AdminActionRun[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const refreshSeq = useRef(0);
  const includeMemoryGraph = pathname === "/memory" || pathname.startsWith("/memory/");
  const includeSourceInbox =
    pathname === "/" ||
    pathname === "/today" ||
    pathname.startsWith("/today/") ||
    pathname === "/leads" ||
    pathname.startsWith("/leads/");
  const includeAdminTaskData =
    pathname === "/tasks" ||
    pathname.startsWith("/tasks/") ||
    pathname === "/today" ||
    pathname.startsWith("/today/") ||
    pathname === "/";
  const includeOrchestration =
    pathname === "/" || pathname === "/today" || pathname.startsWith("/today/");
  const includeAgentHub = includeMemoryGraph || includeOrchestration || includeAdminTaskData;

  const refresh = useCallback(async () => {
    const refreshId = ++refreshSeq.current;
    setError(null);
    const [
      hubResult,
      statusResult,
      sessionsResult,
      cronResult,
      sourceInboxResult,
      dealTasksResult,
      actionRunsResult,
    ] = await Promise.allSettled([
      includeAgentHub
        ? api.getAgentHub({
            lite: true,
            includeMemoryGraph,
            includeOrchestration,
          })
        : Promise.resolve(null),
      api.getStatus(),
      api.getSessions(36, 0, { includeTotal: false }),
      api.getCronJobs({ compact: true }),
      includeSourceInbox ? api.getSourceInbox(SOURCE_INBOX_REFRESH_LIMIT) : Promise.resolve(null),
      includeAdminTaskData ? api.getAdminDealTasks({ status: "open", limit: 200 }) : Promise.resolve(null),
      includeAdminTaskData ? api.getAdminActionRuns({ limit: 200 }) : Promise.resolve(null),
    ]);

    if (refreshSeq.current !== refreshId) return;

    if (hubResult.status === "fulfilled") setSnapshot(hubResult.value);
    if (statusResult.status === "fulfilled") setStatus(statusResult.value);
    if (sessionsResult.status === "fulfilled") {
      setSessions((sessionsResult.value as PaginatedSessions).sessions);
    }
    if (cronResult.status === "fulfilled") setCronJobs(cronResult.value);
    if (sourceInboxResult.status === "fulfilled" && sourceInboxResult.value) {
      setSourceInbox(sourceInboxResult.value);
    } else {
      setSourceInbox(null);
    }
    if (dealTasksResult.status === "fulfilled" && dealTasksResult.value) {
      setDealTasks(dealTasksResult.value.items);
    } else {
      setDealTasks([]);
    }
    if (actionRunsResult.status === "fulfilled" && actionRunsResult.value) {
      setActionRuns(actionRunsResult.value.items);
    } else {
      setActionRuns([]);
    }

    const failed = [hubResult, statusResult, sessionsResult, cronResult, sourceInboxResult, dealTasksResult, actionRunsResult].find(
      (result) => result.status === "rejected",
    );

    if (failed?.status === "rejected") {
      setError(failed.reason instanceof Error ? failed.reason.message : "Some hub data failed");
    }

  }, [includeAdminTaskData, includeMemoryGraph, includeOrchestration, includeSourceInbox, includeAgentHub]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    refresh()
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "Hub failed");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
      refreshSeq.current += 1;
    };
  }, [refresh]);

  useEffect(() => {
    if (typeof document === "undefined") return;
    let id: ReturnType<typeof setInterval> | null = null;
    const start = () => {
      if (!id) id = window.setInterval(() => void refresh(), 25_000);
    };
    const stop = () => {
      if (id) { window.clearInterval(id); id = null; }
    };
    const onVisibility = () => {
      if (document.hidden) stop();
      else { void refresh(); start(); }
    };
    start();
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      stop();
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [refresh]);

  return { actionRuns, cronJobs, dealTasks, error, loading, refresh, setSourceInbox, sourceInbox, sessions, snapshot, status };
}

export function useHubHeader(title: string, data: HubData) {
  const { setAfterTitle, setEnd, setTitle } = usePageHeader();
  const gatewayOnline = Boolean(data.snapshot?.gateway.running || data.status?.gateway_running);

  useLayoutEffect(() => {
    setTitle(title);
    setAfterTitle(
      <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
        <span
          className={cn(
            "h-2 w-2 rounded-full",
            gatewayOnline ? "bg-success" : "bg-muted-foreground/45",
          )}
        />
        {gatewayOnline ? "Local gateway online" : "Local gateway offline"}
      </span>,
    );
    setEnd(
      <Button variant="outline" size="sm" onClick={() => void data.refresh()} disabled={data.loading}>
        <RefreshCw className={cn("h-3.5 w-3.5", data.loading && "animate-spin")} />
        Refresh
      </Button>,
    );
    return () => {
      setTitle(null);
      setAfterTitle(null);
      setEnd(null);
    };
  }, [data.loading, data.refresh, gatewayOnline, setAfterTitle, setEnd, setTitle, title]);
}

```

---
## `src/pages/real-estate-hub/_shared/workflow-strip.tsx`
```tsx
import type { ComponentType } from "react";

export function WorkflowStrip({
  items,
}: {
  items: Array<{
    icon?: ComponentType<{ className?: string }>;
    label: string;
    value: string | number;
  }>;
}) {
  return (
    <div className="flex flex-wrap items-baseline gap-x-1 gap-y-1 px-1 py-1 text-sm text-muted-foreground">
      {items.map((item, i) => (
        <span key={item.label} className="inline-flex items-baseline gap-1">
          {i > 0 && <span aria-hidden="true" className="mx-1.5 text-border">·</span>}
          <span className="font-medium tabular-nums text-foreground">{item.value}</span>
          <span>{item.label}</span>
        </span>
      ))}
    </div>
  );
}

```

---
## `src/pages/real-estate-hub/_shared/index.ts`
```ts
export { ActionBoard } from "./action-board";
export {
  AdminActionRuns,
  AdminDealTasks,
  AdminRunDecisionRow,
  AgentHandoffsCard,
  AgentWorkerCard,
  adminRunStatusVariant,
  RecentSessions,
  sessionTitle,
  TimedTasks,
} from "./agent-widgets";
export type { AdminRunBusy } from "./agent-widgets";
export { ContactOverviewBoard } from "./contact-overview-board";
export {
  APPROVAL_CUE_KEYWORDS,
  ADMIN_WORKFLOW_KEYWORDS,
  approvalCueActions,
  approvalCueCount,
  jobAction,
  jobMatches,
  sessionAction,
  sessionMatches,
} from "./page-helpers";
export { HubMetric } from "./hub-metric";
export { LeadStatusBadge, LeadStatusControl } from "./lead-status-control";
export { parseIdentity, provenanceLine } from "./parse-identity";
export type { ParsedIdentity } from "./parse-identity";
export { HubShell } from "./hub-shell";
export { LoadingState } from "./loading-state";
export { useHubHeader, useRealEstateHubData } from "./use-hub-data";
export { WorkflowStrip } from "./workflow-strip";
export type { BoardAction, HubData } from "./types";

```

---
## `src/pages/real-estate-hub/_shared/page-helpers.ts`
```ts
import type { ComponentType } from "react";
import { ShieldCheck } from "lucide-react";
import type { CronJob, SessionInfo } from "@/lib/api";
import { isoTimeAgo, timeAgo } from "@/lib/utils";
import { sessionTitle } from "./agent-widgets";
import type { BoardAction } from "./types";

export const APPROVAL_CUE_KEYWORDS = ["approval", "approve", "review", "send", "gate"];

export const ADMIN_WORKFLOW_KEYWORDS = [
  "admin",
  "listing",
  "deal",
  "transaction",
  "cma",
  "seller update",
  "seller-update",
  "showing",
  "showingtime",
  "showing time",
  "weekly",
  "relisting",
  "mlc",
  "signing",
  "signing-package",
  "digisign",
  "webforms",
  "contract",
  "paperwork",
  "document",
  "doc router",
  "gmail-doc-router",
  "gmail doc",
  "skyslope",
  "photo-cleanup",
  "listing-build",
  "offer-review",
  "subject-removal",
  "closing-admin",
  "market stats",
  "market-stats",
];

export function sessionMatches(session: SessionInfo, keywords: string[]): boolean {
  const haystack = [
    session.title ?? "",
    session.preview ?? "",
    session.source ?? "",
    session.model ?? "",
  ]
    .join(" ")
    .toLowerCase();
  return keywords.some((keyword) => haystack.includes(keyword));
}

export function jobMatches(job: CronJob, keywords: string[]): boolean {
  const haystack = [
    job.name ?? "",
    job.prompt,
    job.schedule_display ?? "",
    job.deliver ?? "",
    job.skill ?? "",
    ...(job.skills ?? []),
  ]
    .join(" ")
    .toLowerCase();
  return keywords.some((keyword) => haystack.includes(keyword));
}

export function sessionAction(
  session: SessionInfo,
  titlePrefix: string,
  icon: ComponentType<{ className?: string }>,
): BoardAction {
  return {
    detail:
      session.preview?.trim() ||
      `${session.message_count} saved message${session.message_count === 1 ? "" : "s"}.`,
    icon,
    id: `session-${session.id}`,
    meta: `${session.source ?? "local"} / ${timeAgo(session.last_active)}`,
    status: session.is_active ? "active" : "resume",
    title: `${titlePrefix}: ${sessionTitle(session)}`,
    to: `/chat?resume=${encodeURIComponent(session.id)}`,
    variant: session.is_active ? "success" : "outline",
  };
}

export function jobAction(
  job: CronJob,
  titlePrefix: string,
  icon: ComponentType<{ className?: string }>,
): BoardAction {
  return {
    detail: job.prompt,
    icon,
    id: `job-${job.id}`,
    meta: job.next_run_at
      ? `Next ${isoTimeAgo(job.next_run_at)}`
      : job.schedule_display || job.schedule.display || "Scheduled",
    status: job.last_error ? "error" : job.enabled ? "scheduled" : "paused",
    title: `${titlePrefix}: ${job.name || job.prompt.slice(0, 68)}`,
    to: "/cron",
    variant: job.last_error ? "warning" : job.enabled ? "success" : "outline",
  };
}

export function approvalCueCount(sessions: SessionInfo[], jobs: CronJob[]): number {
  return (
    sessions.filter((session) => sessionMatches(session, APPROVAL_CUE_KEYWORDS)).length +
    jobs.filter((job) => jobMatches(job, APPROVAL_CUE_KEYWORDS)).length
  );
}

export function approvalCueActions(
  sessions: SessionInfo[],
  jobs: CronJob[],
  lane: string,
): BoardAction[] {
  const sessionCues = sessions
    .filter((session) => sessionMatches(session, APPROVAL_CUE_KEYWORDS))
    .slice(0, 3)
    .map((session) => ({
      ...sessionAction(session, `${lane} approval`, ShieldCheck),
      status: "review",
      variant: "warning" as const,
    }));
  const jobCues = jobs
    .filter((job) => jobMatches(job, APPROVAL_CUE_KEYWORDS))
    .slice(0, 3)
    .map((job) => ({
      ...jobAction(job, `${lane} review`, ShieldCheck),
      status: "review",
      variant: "warning" as const,
    }));
  return [...sessionCues, ...jobCues];
}

```

---
## `src/pages/real-estate-hub/_shared/parse-identity.ts`
```ts
const EMAIL_RE = /^[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+$/;
const ENVELOPE_RE = /^\s*(?:"([^"]+)"|([^<]*?))\s*<\s*([^>\s]+)\s*>\s*$/;
const FORWARDED_RE = /\.gmail\.com@/i;
const PLACEHOLDER_DOMAINS = /(?:\.fdske\.com|\.example\.com|@noreply|@no-reply)$/i;

export type ParsedIdentity = {
  /** Display name suitable for the row title. Falls back to local-part. */
  name: string;
  /** Email address if one was parsed and looks legitimate. */
  email: string | null;
  /** True when the input was clearly an RFC822 envelope. */
  isEnvelope: boolean;
};

export function parseIdentity(raw: string | null | undefined): ParsedIdentity {
  const input = (raw ?? "").trim();
  if (!input) return { name: "—", email: null, isEnvelope: false };

  const envelopeMatch = input.match(ENVELOPE_RE);
  if (envelopeMatch) {
    const quoted = envelopeMatch[1];
    const bare = envelopeMatch[2];
    const email = envelopeMatch[3] ?? null;
    const rawName = (quoted ?? bare ?? "").trim();
    const email_ = email && EMAIL_RE.test(email) ? email : null;
    const name = rawName.length > 0 ? rawName : email_ ? localPart(email_) : input;
    return {
      name: cleanName(name),
      email: hideJunkEmail(email_),
      isEnvelope: true,
    };
  }

  if (EMAIL_RE.test(input)) {
    return {
      name: cleanName(localPart(input)),
      email: hideJunkEmail(input),
      isEnvelope: true,
    };
  }

  return { name: cleanName(input), email: null, isEnvelope: false };
}

function localPart(email: string): string {
  const at = email.indexOf("@");
  if (at <= 0) return email;
  return email.slice(0, at);
}

function cleanName(name: string): string {
  return name.replace(/^["']+|["']+$/g, "").trim() || "—";
}

function hideJunkEmail(email: string | null): string | null {
  if (!email) return null;
  if (FORWARDED_RE.test(email)) return null;
  if (PLACEHOLDER_DOMAINS.test(email)) return null;
  return email;
}

/**
 * Combine a sourceLabel like "Composio — gmail" with a channel like "gmail".
 * Returns the de-duplicated provenance string for the row's secondary line.
 */
export function provenanceLine(sourceLabel: string, channel: string): string {
  const src = sourceLabel.trim();
  const ch = channel.trim();
  if (!src) return ch;
  if (!ch) return src;
  if (src.toLowerCase().includes(ch.toLowerCase())) return src;
  return `${src} · ${ch}`;
}

```

---
## `src/pages/real-estate-hub/_shared/types.ts`
```ts
import type { ComponentType } from "react";
import type {
  AdminActionRun,
  AdminDealTask,
  AgentHubSnapshot,
  CronJob,
  SessionInfo,
  SourceInboxResponse,
  StatusResponse,
} from "@/lib/api";

export type HubData = {
  actionRuns: AdminActionRun[];
  cronJobs: CronJob[];
  dealTasks: AdminDealTask[];
  error: string | null;
  loading: boolean;
  refresh: () => Promise<void>;
  setSourceInbox: (sourceInbox: SourceInboxResponse | null) => void;
  sourceInbox: SourceInboxResponse | null;
  sessions: SessionInfo[];
  snapshot: AgentHubSnapshot | null;
  status: StatusResponse | null;
};

export type BoardAction = {
  detail: string;
  icon: ComponentType<{ className?: string }>;
  id: string;
  meta: string;
  status: string;
  title: string;
  to: string;
  variant?: "success" | "warning" | "outline";
};

```

---
## `src/pages/real-estate-hub/admin/index.tsx`
```tsx
import React, {
  memo,
  useCallback,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
} from "react";
import { createPortal } from "react-dom";
import {
  BriefcaseBusiness,
  Building2,
  CalendarClock,
  CheckCircle2,
  CheckSquare,
  ChevronDown,
  Cloud,
  Clock,
  Database as DatabaseIcon,
  ExternalLink,
  FileCheck2,
  FileText,
  Flame,
  Globe,
  Home,
  KeyRound,
  Loader2,
  Lock,
  Mail,
  MessageCircle,
  Phone,
  Send,
  Square as SquareIcon,
  Plus,
  RefreshCw,
  RotateCcw,
  ShieldCheck,
  Sparkles,
  Target,
  Users,
  X as CloseIcon,
} from "lucide-react";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "@/lib/api";
import type {
  AdminActionRun,
  AdminContact,
  AdminDeal,
  AdminDealCreateRequest,
  AdminProvinceGuideCoverage,
  AdminSetupSnapshot,
  DealAttachmentCreateRequest,
  DealContactCreateRequest,
  DealContext,
  ProvinceStageDocumentItem,
  SourceInboxProfileVerifier,
} from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { cn, isoTimeAgo } from "@/lib/utils";
import {
  playOnboardingChime,
  playOnboardingClick,
  playOnboardingSwell,
} from "@/lib/onboarding-sounds";
import {
  adminSetupDraftFromSnapshot,
  adminSetupPayloadFromDraft,
  type AdminSetupDraft,
} from "@/pages/real-estate-hub/admin-setup";
import { heatVariant } from "@/pages/real-estate-hub/utils";
import { verifierSummary } from "@/pages/real-estate-hub/profile-workflow";
import {
  ActionBoard,
  AdminRunDecisionRow,
  adminRunStatusVariant,
  HubShell,
  RecentSessions,
  TimedTasks,
  useHubHeader,
  useRealEstateHubData,
  WorkflowStrip,
  type AdminRunBusy,
} from "@/pages/real-estate-hub/_shared";
import {
  ADMIN_WORKFLOW_KEYWORDS,
  APPROVAL_CUE_KEYWORDS,
  approvalCueActions,
  approvalCueCount,
  jobAction,
  jobMatches,
  sessionAction,
  sessionMatches,
} from "@/pages/real-estate-hub/_shared/page-helpers";

const DEFAULT_ADMIN_AUTOMATIONS = [
  {
    name: "Gmail Doc Router",
    schedule: "0 9 * * 1",
    skill: "gmail-doc-router",
    skills: ["gmail-doc-router"],
    deliver: "local",
    workdir: "",
    prompt:
      "Run the gmail-doc-router skill. Check the last 7 days of Gmail attachments, match listing documents to active Elevate deals with deal-matcher, file documents to the correct Drive folder, and write artifacts/checklist evidence back to the deal with admin-result-writer. Do not send messages.",
  },
  {
    name: "Seller Update",
    schedule: "0 16 * * 1-5",
    skill: "seller-update",
    skills: ["seller-update"],
    deliver: "local",
    workdir: "",
    prompt:
      "Run the seller-update skill. Pull ShowingTime feedback/activity for active listings, match each listing to an Elevate deal, write the digest back to SQLite, and create Gmail seller-update drafts. Never send directly.",
  },
  {
    name: "Market Stats Watcher",
    schedule: "0 7 * * 1",
    skill: "market-stats-watcher",
    skills: ["market-stats-watcher"],
    deliver: "local",
    workdir: "",
    prompt:
      "Run the market-stats-watcher skill. Pull fresh market-stat emails and route useful market context into the real estate knowledge/admin workflow. Do not send messages.",
  },
];

const ADMIN_STAGE_NUMBERS = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10] as const;

type AdminSide = "listing" | "buyer";
type AdminStageNumber = (typeof ADMIN_STAGE_NUMBERS)[number];

const CANADIAN_PROVINCES: Array<{ code: string; label: string }> = [
  { code: "AB", label: "Alberta" },
  { code: "BC", label: "British Columbia" },
  { code: "MB", label: "Manitoba" },
  { code: "NB", label: "New Brunswick" },
  { code: "NL", label: "Newfoundland and Labrador" },
  { code: "NS", label: "Nova Scotia" },
  { code: "NT", label: "Northwest Territories" },
  { code: "NU", label: "Nunavut" },
  { code: "ON", label: "Ontario" },
  { code: "PEI", label: "Prince Edward Island" },
  { code: "QC", label: "Quebec" },
  { code: "SK", label: "Saskatchewan" },
  { code: "YK", label: "Yukon" },
];

const PROVINCE_LABEL_BY_CODE = new Map(CANADIAN_PROVINCES.map(({ code, label }) => [code, label]));

type AdminStageLabel = {
  title: string;
  subtitle: string;
};

type AdminColumn = {
  stage: AdminStageNumber;
  stageNumber: string;
  stageLabel?: string;
  labels: Record<AdminSide, AdminStageLabel>;
};

type AdminChecklistItem = { id: string; label: string };

type AdminPhaseAutomationInfo = {
  agents: string[];
  background: string[];
  moveSignal: string;
  approvalGate?: string;
};

type AdminEnumField =
  | "signing_authority"
  | "fintrac_form_type"
  | "listing_track"
  | "property_subtype"
  | "estate_status"
  | "transaction_type"
  | "listing_type";

type AdminToggleField =
  | "pep"
  | "tenanted"
  | "poa_signing"
  | "corporate"
  | "has_suite"
  | "multiple_offers"
  | "family_member"
  | "dual_rep"
  | "unrepresented_other_side"
  | "lockbox"
  | "delayed_offer"
  | "sale_of_buyers_property";

type AdminConditionField = AdminEnumField | AdminToggleField;
type AdminConditionValue = string | boolean | null;
type AdminCompletedByStage = Partial<Record<AdminStageNumber, Record<string, boolean>>>;

type AdminSourceContext = {
  profileName?: string;
  latestText?: string;
  latestAt?: string;
  heatLabel?: string;
  heatScore?: number;
  sources: string[];
  channels: string[];
  contactIds: string[];
  conversationIds: string[];
  verifiers: SourceInboxProfileVerifier[];
  rejectedContactId?: string;
};

type AdminCard = {
  id: string;
  side: AdminSide;
  stage: AdminStageNumber;
  client: string;
  contactInitials: string;
  property?: string;
  nextLabel?: string;
  nextDate?: string;
  daysOut?: number;
  pinnedTop25?: boolean;
  completedByStage?: AdminCompletedByStage;
  conditions?: Partial<Record<AdminConditionField, AdminConditionValue>>;
  sourceContext?: AdminSourceContext;
};

const ADMIN_SIDE_LABELS: Record<AdminSide, { title: string; description: string }> = {
  listing: {
    title: "Listing Admin",
    description: "CMA through closed file",
  },
  buyer: {
    title: "Buyer Admin",
    description: "Walkthrough through one-week follow-up",
  },
};

const ADMIN_COLUMNS: AdminColumn[] = [
  {
    stage: 0,
    stageNumber: "S0",
    stageLabel: "Pre-CMA",
    labels: {
      listing: { title: "Pre-CMA", subtitle: "Google Form + Lofty contact" },
      buyer: { title: "Intake", subtitle: "Profile + budget" },
    },
  },
  {
    stage: 1,
    stageNumber: "S1",
    stageLabel: "CMA",
    labels: {
      listing: { title: "CMA / Evaluation", subtitle: "PDF + pricing story" },
      buyer: { title: "Search Setup", subtitle: "Criteria + MLS" },
    },
  },
  {
    stage: 2,
    stageNumber: "S2",
    stageLabel: "Intake",
    labels: {
      listing: { title: "Listing Intake", subtitle: "Trigger MLC + missing fields" },
      buyer: { title: "Tours", subtitle: "Route + notes" },
    },
  },
  {
    stage: 3,
    stageNumber: "S3",
    stageLabel: "SkySlope",
    labels: {
      listing: { title: "SkySlope & Matrix Prep", subtitle: "Compliance file + incomplete MLS draft" },
      buyer: { title: "Follow-Up", subtitle: "Feedback + fit" },
    },
  },
  {
    stage: 4,
    stageNumber: "S4",
    stageLabel: "Marketing",
    labels: {
      listing: { title: "Marketing Go", subtitle: "Coming-soon + launch assets" },
      buyer: { title: "Offer Prep", subtitle: "Comps + offer paperwork" },
    },
  },
  {
    stage: 5,
    stageNumber: "S5",
    stageLabel: "MLS",
    labels: {
      listing: { title: "MLS Entry", subtitle: "Listing build + launch prep" },
      buyer: { title: "Accepted", subtitle: "Lender + docs" },
    },
  },
  {
    stage: 6,
    stageNumber: "S6",
    stageLabel: "Live",
    labels: {
      listing: { title: "Listing Live / Marketing", subtitle: "MLS live + seller updates" },
      buyer: { title: "Conditions", subtitle: "Inspection + property review" },
    },
  },
  {
    stage: 7,
    stageNumber: "S7",
    stageLabel: "Contract",
    labels: {
      listing: { title: "Accepted Offer", subtitle: "Contract review + dates" },
      buyer: { title: "Conditions Removed", subtitle: "Deposit + dates" },
    },
  },
  {
    stage: 8,
    stageNumber: "S8",
    stageLabel: "Conditions",
    labels: {
      listing: { title: "Condition Removal", subtitle: "Conditions + lawyer package" },
      buyer: { title: "Closing", subtitle: "Lawyer + walkthrough" },
    },
  },
  {
    stage: 9,
    stageNumber: "S9",
    stageLabel: "Closing",
    labels: {
      listing: { title: "Closing", subtitle: "Lawyer / conveyance + possession" },
      buyer: { title: "Possession", subtitle: "Gift + follow-up" },
    },
  },
  {
    stage: 10,
    stageNumber: "S10",
    stageLabel: "Closed",
    labels: {
      listing: { title: "Closed", subtitle: "Archive + nurture" },
      buyer: { title: "Closed", subtitle: "Archive + nurture" },
    },
  },
];

const ADMIN_PHASE_AUTOMATIONS: Record<AdminSide, Record<AdminStageNumber, AdminPhaseAutomationInfo>> = {
  listing: {
    0: {
      agents: ["pre-cma-dashboard-setup", "lofty-crm-client-contacts"],
      background: [],
      moveSignal: "pre-CMA dashboard setup complete + Lofty contact verified",
      approvalGate: "confirm missing contact/setup details",
    },
    1: {
      agents: ["cma", "seller-package"],
      background: [],
      moveSignal: "CMA PDF/evaluation complete + client says yes",
      approvalGate: "approve CMA/evaluation before client delivery",
    },
    2: {
      agents: ["mlc", "deal-matcher", "signing-package"],
      background: ["gmail-doc-router"],
      moveSignal: "MLC intake complete + listing docs ready",
      approvalGate: "approve docs/signature placements before signing send",
    },
    3: {
      agents: ["skyslope-sync", "matrix-incomplete-listing", "deal-matcher"],
      background: ["gmail-doc-router"],
      moveSignal: "signed docs saved + SkySlope/Matrix prep complete",
      approvalGate: "approve Matrix draft before publish",
    },
    4: {
      agents: ["photo-cleanup", "marketing", "matrix-incomplete-listing"],
      background: [],
      moveSignal: "photos cleaned/saved + Marketing Go package ready + Matrix photos uploaded",
      approvalGate: "answer Marketing Go/photo questions and approve launch assets before external publishing",
    },
    5: {
      agents: ["property-lookup", "listing-build"],
      background: [],
      moveSignal: "MLS package approved",
      approvalGate: "approve MLS copy/package",
    },
    6: {
      agents: ["marketing"],
      background: ["seller-update"],
      moveSignal: "offer accepted",
      approvalGate: "approve outgoing drafts",
    },
    7: {
      agents: ["offer-review"],
      background: ["gmail-doc-router"],
      moveSignal: "accepted-offer dates verified",
      approvalGate: "review offer terms",
    },
    8: {
      agents: ["subject-removal", "signing-package"],
      background: ["gmail-doc-router"],
      moveSignal: "conditions removed + deposit verified",
      approvalGate: "confirm condition removal",
    },
    9: {
      agents: ["closing-admin"],
      background: ["gmail-doc-router"],
      moveSignal: "closing package complete",
      approvalGate: "confirm closing package",
    },
    10: {
      agents: ["skyslope-sync", "marketing"],
      background: [],
      moveSignal: "file closed + nurture queued",
      approvalGate: "approve closeout",
    },
  },
  buyer: {
    0: { agents: [], background: [], moveSignal: "profile verified" },
    1: { agents: [], background: [], moveSignal: "search criteria ready" },
    2: { agents: [], background: [], moveSignal: "showing notes complete" },
    3: { agents: [], background: [], moveSignal: "follow-up complete" },
    4: { agents: [], background: [], moveSignal: "offer package ready" },
    5: { agents: [], background: [], moveSignal: "accepted-offer checklist complete" },
    6: { agents: [], background: [], moveSignal: "conditions tracked" },
    7: { agents: [], background: [], moveSignal: "conditions removed" },
    8: { agents: [], background: [], moveSignal: "closing checklist complete" },
    9: { agents: [], background: [], moveSignal: "possession follow-up queued" },
    10: { agents: [], background: [], moveSignal: "file archived" },
  },
};

// Per-stage checklist catalog. Card state (completedByStage) overlays this.
const ADMIN_STAGE_CHECKLISTS: Record<AdminSide, Record<AdminStageNumber, AdminChecklistItem[]>> = {
  listing: {
    0: [
    { id: "pre_cma_google_form", label: "Pre-CMA Google Form filled" },
    { id: "lofty_contact_verified", label: "Lofty contact verified / created" },
    { id: "pre_cma_handoff", label: "Client/property notes saved for CMA" },
    ],
    1: [
    { id: "cma_pdf_ready", label: "CMA PDF / evaluation ready" },
    { id: "pricing_story_approved", label: "Pricing story approved" },
    { id: "client_yes_to_listing", label: "Client said yes to listing" },
    ],
    2: [
    { id: "mlc_intake_started", label: "MLC intake triggered" },
    { id: "listing_missing_fields", label: "Missing listing fields surfaced" },
    { id: "listing_docs_approval", label: "Listing docs/signature placements ready for approval" },
    ],
    3: [
    { id: "signed_listing_docs_saved", label: "Signed listing docs saved to Drive" },
    { id: "skyslope_file_created", label: "SkySlope file created / synced" },
    { id: "matrix_incomplete_listing_prepped", label: "Matrix/Xposure incomplete listing prepped" },
    { id: "matrix_missing_fields_surfaced", label: "Matrix missing fields surfaced" },
    ],
    4: [
    { id: "marketing_go_started", label: "Marketing Go started after SkySlope/Matrix prep" },
    { id: "photographer_drive_link_received", label: "Photographer Google Drive/photo link received or requested" },
    { id: "marketing_go_questions_answered", label: "Marketing Go questions answered / blockers surfaced" },
    { id: "photo_cleanup_complete", label: "Photo cleanup complete" },
    { id: "cleaned_photos_saved_to_drive", label: "Cleaned photos saved to listing Google Drive folder" },
    { id: "best_99_matrix_photos_selected", label: "Best 99 Matrix photos selected if photographer sent more than 99" },
    { id: "matrix_photos_uploaded", label: "Photos uploaded to Matrix/Xposure" },
    { id: "matrix_listing_finished_with_photos", label: "Matrix listing finished with final photos" },
    { id: "coming_soon_assets_ready", label: "Coming-soon assets ready" },
    { id: "landing_page_ready", label: "Landing page ready" },
    { id: "launch_copy_social_email_ready", label: "Launch copy, social posts, and email assets ready" },
    { id: "marketing_package_ready_for_approval", label: "Marketing package ready for approval" },
    ],
    5: [
    { id: "workflow_evalue_bc_age_verified", label: "Property valuation age verified" },
    { id: "workflow_listing_description_approved", label: "Listing description approved" },
    { id: "workflow_feature_sheet_uploaded", label: "Feature sheet uploaded" },
    { id: "workflow_ai_edited_photos_labelled", label: "AI-edited photos labelled" },
    { id: "workflow_stage_4_complete", label: "MLS package approved" },
    ],
    6: [
    { id: "workflow_just_listed_blast_sent", label: "Just listed blast sent" },
    { id: "workflow_social_posts_published", label: "Social posts published" },
    { id: "workflow_flodesk_mailout_sent", label: "Flodesk mailout sent" },
    { id: "workflow_lofty_text_blast_sent", label: "Lofty text blast sent" },
    { id: "workflow_stage_5_complete", label: "Live marketing checklist complete" },
    ],
    7: [
    { id: "workflow_within_24hrs_contract_reviewed", label: "Contract reviewed within 24 hours" },
    { id: "workflow_email_buyer_accepted_offer_checklist_sent", label: "Accepted-offer checklist email sent" },
    { id: "workflow_fintrac_drivers_occupation_employer_captured", label: "FINTRAC details captured" },
    { id: "workflow_calendar_dates_added", label: "Calendar dates added" },
    { id: "workflow_moving_checklist_sent", label: "Moving checklist sent" },
    { id: "workflow_stage_6_complete", label: "Accepted-offer admin verified" },
    ],
    8: [
    { id: "workflow_subject_removal_form_sent", label: "Condition removal / waiver sent" },
    { id: "workflow_title_charges_verified", label: "Title charges verified" },
    { id: "workflow_bir_pds_received", label: "Property disclosure docs received" },
    { id: "workflow_lawyer_info_requested", label: "Lawyer info requested" },
    { id: "workflow_stage_7_complete", label: "Conditions removed / waived" },
    ],
    9: [
    { id: "workflow_conveyancer_package_sent", label: "Lawyer / conveyancer package sent" },
    { id: "workflow_down_payment_to_trust", label: "Down payment to trust" },
    { id: "workflow_mortgage_instructions_received", label: "Mortgage instructions received" },
    { id: "workflow_insurance_binder_confirmed", label: "Insurance binder confirmed" },
    { id: "workflow_client_signed_lawyer", label: "Client signed at lawyer" },
    { id: "workflow_funds_released", label: "Funds released" },
    { id: "workflow_stage_8_complete", label: "Closing admin verified" },
    ],
    10: [
    { id: "workflow_commission_submitted", label: "Commission submitted" },
    { id: "workflow_skyslope_deal_closed", label: "SkySlope deal closed" },
    { id: "workflow_sold_update_sent", label: "Sold update sent" },
    { id: "workflow_closing_gift_sent", label: "Closing gift sent" },
    { id: "workflow_review_requested", label: "Review requested" },
    { id: "workflow_stage_9_complete", label: "Closed file archived" },
    ],
  },
  buyer: {
    0: [
    { id: "buyer-profile", label: "Buyer profile (budget, financing, areas, beds, must-haves)" },
    { id: "search-criteria", label: "MLS / Lofty search filter built" },
    ],
    1: [
    { id: "shortlist", label: "Property shortlist + ranked-fit" },
    { id: "showing-route", label: "Showing route + itinerary" },
    { id: "preview-notes", label: "Preview notes per property" },
    ],
    2: [
    { id: "followup-draft", label: "Per-showing follow-up draft" },
    { id: "feedback-summary", label: "Feedback summary (liked / disliked / dealbreakers)" },
    ],
    3: [
    { id: "criteria-update", label: "Buyer criteria updated" },
    { id: "comp-pull", label: "Comparable sales pulled" },
    { id: "cps-checklist", label: "Offer document checklist + strategy" },
    ],
    4: [
    { id: "lender-paperwork", label: "Lender paperwork sent" },
    { id: "accepted-offer-checklist", label: "Accepted-offer checklist run" },
    { id: "doc-list", label: "Doc list (offer, addenda, disclosures, deposit receipt)" },
    ],
    5: [
    { id: "inspection-booked", label: "Inspection booked" },
    { id: "insurance-deadline", label: "Insurance deadline tracked" },
    { id: "strata-review", label: "Strata / condo review (if applicable)" },
    ],
    6: [
    { id: "deposit-due", label: "Deposit due date tracked" },
    { id: "lawyer-info", label: "Lawyer / conveyancer info captured" },
    { id: "skyslope-docs", label: "SkySlope missing-doc list cleared" },
    ],
    7: [
    { id: "subjects-removed", label: "All conditions removed / waived" },
    { id: "deposit-received", label: "Deposit received" },
    { id: "completion-locked", label: "Completion + possession dates locked" },
    ],
    8: [
    { id: "lawyer-final-docs", label: "Final docs forwarded to lawyer" },
    { id: "completion-checklist", label: "Completion checklist complete" },
    { id: "final-walkthrough", label: "Final walkthrough scheduled" },
    ],
    9: [
    { id: "utility-reminder", label: "Utility / change-of-address reminder sent" },
    { id: "key-handoff", label: "Key handoff coordinated" },
    { id: "closing-gift", label: "Closing gift sent" },
    { id: "thank-you", label: "Thank-you / review / referral drafts queued" },
    { id: "one-week-followup", label: "One-week-after follow-up scheduled" },
    { id: "anniversary", label: "Anniversary reminder added" },
    ],
    10: [
    { id: "buyer-file-archived", label: "Buyer file archived" },
    ],
  },
};

const ADMIN_ENUM_CONDITIONS: Array<{
  field: AdminEnumField;
  label: string;
  options: Array<{ value: string; label: string }>;
}> = [
  {
    field: "signing_authority",
    label: "Signing authority",
    options: [
      { value: "seller", label: "Seller" },
      { value: "buyer", label: "Buyer" },
      { value: "both", label: "Both clients" },
      { value: "poa", label: "Power of attorney" },
      { value: "corporate", label: "Corporate signer" },
      { value: "estate_executor", label: "Estate executor" },
    ],
  },
  {
    field: "fintrac_form_type",
    label: "FINTRAC form type",
    options: [
      { value: "individual", label: "Individual" },
      { value: "corporation", label: "Corporation" },
      { value: "estate", label: "Estate" },
      { value: "poa", label: "Power of attorney" },
      { value: "third_party", label: "Third party" },
    ],
  },
  {
    field: "listing_track",
    label: "Listing track",
    options: [
      { value: "standard", label: "Standard" },
      { value: "rush", label: "Rush" },
      { value: "pre_market", label: "Pre-market" },
      { value: "relist", label: "Relist" },
    ],
  },
  {
    field: "property_subtype",
    label: "Property subtype",
    options: [
      { value: "detached", label: "Detached" },
      { value: "townhouse", label: "Townhouse" },
      { value: "condo", label: "Condo" },
      { value: "strata", label: "Strata" },
      { value: "acreage", label: "Acreage" },
      { value: "land", label: "Land" },
      { value: "multifamily", label: "Multifamily" },
    ],
  },
  {
    field: "estate_status",
    label: "Estate status",
    options: [
      { value: "none", label: "None" },
      { value: "estate_sale", label: "Estate sale" },
      { value: "probate_pending", label: "Probate pending" },
      { value: "probate_granted", label: "Probate granted" },
    ],
  },
  {
    field: "transaction_type",
    label: "Transaction type",
    options: [
      { value: "residential", label: "Residential" },
      { value: "commercial", label: "Commercial" },
      { value: "referral", label: "Referral" },
      { value: "assignment", label: "Assignment" },
    ],
  },
  {
    field: "listing_type",
    label: "Listing type",
    options: [
      { value: "mls", label: "MLS" },
      { value: "exclusive", label: "Exclusive" },
      { value: "coming_soon", label: "Coming soon" },
      { value: "mere_posting", label: "Mere posting" },
    ],
  },
];

const ADMIN_TOGGLE_CONDITIONS: Array<{ field: AdminToggleField; label: string }> = [
  { field: "pep", label: "PEP" },
  { field: "tenanted", label: "Tenanted" },
  { field: "poa_signing", label: "POA signing" },
  { field: "corporate", label: "Corporate" },
  { field: "has_suite", label: "Has suite" },
  { field: "multiple_offers", label: "Multiple offers" },
  { field: "family_member", label: "Family member" },
  { field: "dual_rep", label: "Dual representation" },
  { field: "unrepresented_other_side", label: "Unrepresented other side" },
  { field: "lockbox", label: "Lockbox" },
  { field: "delayed_offer", label: "Delayed offer" },
  { field: "sale_of_buyers_property", label: "Sale of buyer's property" },
];

const ADMIN_CONDITION_FIELD_SET = new Set<string>([
  ...ADMIN_ENUM_CONDITIONS.map((item) => item.field),
  ...ADMIN_TOGGLE_CONDITIONS.map((item) => item.field),
]);

const ADMIN_DEAL_CONDITION_API_KEYS: Record<AdminConditionField, keyof AdminDeal> = {
  signing_authority: "signingAuthority",
  fintrac_form_type: "fintracFormType",
  listing_track: "listingTrack",
  property_subtype: "propertySubtype",
  estate_status: "estateStatus",
  transaction_type: "transactionType",
  listing_type: "listingType",
  pep: "pep",
  tenanted: "tenanted",
  poa_signing: "poaSigning",
  corporate: "corporate",
  has_suite: "hasSuite",
  multiple_offers: "multipleOffers",
  family_member: "familyMember",
  dual_rep: "dualRep",
  unrepresented_other_side: "unrepresentedOtherSide",
  lockbox: "lockbox",
  delayed_offer: "delayedOffer",
  sale_of_buyers_property: "saleOfBuyersProperty",
};

function isAdminConditionField(field: string): field is AdminConditionField {
  return ADMIN_CONDITION_FIELD_SET.has(field);
}

function isAdminSide(value: unknown): value is AdminSide {
  return value === "listing" || value === "buyer";
}

function toAdminStage(value: unknown): AdminStageNumber {
  const numeric = typeof value === "number" ? value : Number(value);
  if (Number.isInteger(numeric) && ADMIN_STAGE_NUMBERS.includes(numeric as AdminStageNumber)) {
    return numeric as AdminStageNumber;
  }
  return 0;
}

function adminStageDefinition(stage: AdminStageNumber): AdminColumn {
  return ADMIN_COLUMNS.find((column) => column.stage === stage) ?? ADMIN_COLUMNS[0];
}

function adminStageLabel(side: AdminSide, stage: AdminStageNumber): AdminStageLabel {
  return adminStageDefinition(stage).labels[side];
}

function adminStageChecklist(side: AdminSide, stage: AdminStageNumber): AdminChecklistItem[] {
  return ADMIN_STAGE_CHECKLISTS[side][stage];
}

function adminPhaseAutomation(side: AdminSide, stage: AdminStageNumber): AdminPhaseAutomationInfo {
  return ADMIN_PHASE_AUTOMATIONS[side][stage];
}

function visibleAdminStages(side: AdminSide): AdminStageNumber[] {
  return ADMIN_STAGE_NUMBERS.filter((stage) => !(side === "listing" && stage === 5));
}

function adminNextStage(card: AdminCard): AdminStageNumber | null {
  if (card.stage >= 10) return null;
  if (card.side === "listing" && card.stage === 4) return 6;
  return (card.stage + 1) as AdminStageNumber;
}

function getStageProgress(card: AdminCard, stage: AdminStageNumber): { done: number; total: number; nextItem?: string } {
  const items = adminStageChecklist(card.side, stage);
  const completed = card.completedByStage?.[stage] ?? {};
  let done = 0;
  let nextItem: string | undefined;
  for (const item of items) {
    if (completed[item.id]) done++;
    else if (!nextItem) nextItem = item.label;
  }
  return { done, total: items.length, nextItem };
}

function getCardProgress(card: AdminCard): { done: number; total: number; nextItem?: string } {
  return getStageProgress(card, card.stage);
}

function adminChecklistStageForItem(side: AdminSide, itemId: string): AdminStageNumber | null {
  for (const stage of ADMIN_STAGE_NUMBERS) {
    if (adminStageChecklist(side, stage).some((item) => item.id === itemId)) {
      return stage;
    }
  }
  return null;
}

function initialsFromTitle(title: string): string {
  const words = title
    .replace(/[^a-z0-9\s&]/gi, " ")
    .split(/\s+/)
    .filter(Boolean);
  const initials = words
    .slice(0, 2)
    .map((word) => word.slice(0, 1).toUpperCase())
    .join("");
  return initials || "AD";
}

function adminConditionValueFromDeal(deal: AdminDeal, field: AdminConditionField): AdminConditionValue {
  const value = deal[ADMIN_DEAL_CONDITION_API_KEYS[field]];
  if (value === undefined) return null;
  if (typeof value === "string" || typeof value === "boolean" || value == null) {
    return value;
  }
  return String(value);
}

function adminConditionsFromDeal(deal: AdminDeal): Partial<Record<AdminConditionField, AdminConditionValue>> {
  const conditions: Partial<Record<AdminConditionField, AdminConditionValue>> = {};
  for (const field of ADMIN_CONDITION_FIELD_SET) {
    if (isAdminConditionField(field)) {
      conditions[field] = adminConditionValueFromDeal(deal, field);
    }
  }
  return conditions;
}

function completedStagesFromDeal(deal: AdminDeal, side: AdminSide): AdminCompletedByStage {
  const completed: AdminCompletedByStage = {};
  const extraToggles = deal.extraToggles ?? {};
  for (const stage of ADMIN_STAGE_NUMBERS) {
    const stageCompleted: Record<string, boolean> = {};
    for (const item of adminStageChecklist(side, stage)) {
      if (extraToggles[item.id] === true) {
        stageCompleted[item.id] = true;
      }
    }
    if (Object.keys(stageCompleted).length > 0) {
      completed[stage] = stageCompleted;
    }
  }
  return completed;
}

function adminStringList(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value
    .map((item) => (typeof item === "string" ? item.trim() : ""))
    .filter(Boolean)
    .slice(0, 6);
}

function adminStringValue(value: unknown): string | undefined {
  return typeof value === "string" && value.trim() ? value.trim() : undefined;
}

function adminNumberValue(value: unknown): number | undefined {
  return typeof value === "number" && Number.isFinite(value) ? value : undefined;
}

function adminVerifierList(value: unknown): SourceInboxProfileVerifier[] {
  if (!Array.isArray(value)) return [];
  return value
    .map((item) => {
      if (!item || typeof item !== "object") return null;
      const record = item as Record<string, unknown>;
      const kind = adminStringValue(record.kind);
      const verifierValue = adminStringValue(record.value);
      const key = adminStringValue(record.key);
      if (!kind || !verifierValue || !key) return null;
      return { kind, value: verifierValue, key };
    })
    .filter((item): item is SourceInboxProfileVerifier => item !== null)
    .slice(0, 6);
}

function adminSourceContextFromDeal(deal: AdminDeal): AdminSourceContext | undefined {
  const extra = deal.extraToggles ?? {};
  if (!adminStringValue(extra.sourceProfileId) && extra.workflow !== "cma") return undefined;
  return {
    profileName: adminStringValue(extra.profileDisplayName) ?? adminStringValue(extra.sourceProfileName),
    latestText: adminStringValue(extra.profileLatestText) ?? adminStringValue(extra.sourceLatestText),
    latestAt: adminStringValue(extra.profileLatestAt) ?? adminStringValue(extra.sourceLatestAt),
    heatLabel: adminStringValue(extra.profileHeatLabel) ?? adminStringValue(extra.sourceHeatLabel),
    heatScore: adminNumberValue(extra.profileHeatScore) ?? adminNumberValue(extra.sourceHeatScore),
    sources: adminStringList(extra.profileSources).length
      ? adminStringList(extra.profileSources)
      : adminStringList(extra.sourceLabels),
    channels: adminStringList(extra.profileChannels).length
      ? adminStringList(extra.profileChannels)
      : adminStringList(extra.sourceChannels),
    contactIds: adminStringList(extra.profileContactIds).length
      ? adminStringList(extra.profileContactIds)
      : adminStringList(extra.sourceContactIds),
    conversationIds: adminStringList(extra.profileConversationIds).length
      ? adminStringList(extra.profileConversationIds)
      : adminStringList(extra.sourceConversationIds),
    verifiers: adminVerifierList(extra.profileVerifiers).length
      ? adminVerifierList(extra.profileVerifiers)
      : adminVerifierList(extra.sourceVerifiers),
    rejectedContactId: adminStringValue(extra.sourcePrimaryContactIdRejected),
  };
}

function adminCardFromDeal(deal: AdminDeal): AdminCard {
  const side = isAdminSide(deal.side) ? deal.side : "listing";
  const stage = toAdminStage(deal.currentStage);
  const stageLabel = adminStageLabel(side, stage);
  const property = deal.listingAddress || (deal.province ? `${deal.province} deal` : undefined);
  return {
    id: deal.id,
    side,
    stage,
    client: deal.title || "Untitled deal",
    contactInitials: initialsFromTitle(deal.title || "Admin deal"),
    property,
    nextLabel: stageLabel.title,
    pinnedTop25: deal.extraToggles?.pinnedTop25 === true || deal.extraToggles?.top25 === true,
    completedByStage: completedStagesFromDeal(deal, side),
    conditions: adminConditionsFromDeal(deal),
    sourceContext: adminSourceContextFromDeal(deal),
  };
}

function applyLocalDealField(card: AdminCard, field: string, value: AdminConditionValue): AdminCard {
  if (isAdminConditionField(field)) {
    return {
      ...card,
      conditions: {
        ...(card.conditions ?? {}),
        [field]: value,
      },
    };
  }

  const stage = adminChecklistStageForItem(card.side, field);
  if (stage == null) return card;

  const currentStageState = card.completedByStage?.[stage] ?? {};
  const nextStageState = { ...currentStageState };
  if (value === true) nextStageState[field] = true;
  else delete nextStageState[field];

  return {
    ...card,
    completedByStage: {
      ...(card.completedByStage ?? {}),
      [stage]: nextStageState,
    },
  };
}

function replaceCardFromDeal(cards: AdminCard[], deal: AdminDeal): AdminCard[] {
  const nextCard = adminCardFromDeal(deal);
  return cards.map((card) => (card.id === nextCard.id ? nextCard : card));
}

function isApiNotFound(error: unknown): boolean {
  return error instanceof Error && /^404\b/.test(error.message);
}

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback;
}

function useAdminSetup(): {
  setup: AdminSetupSnapshot | null;
  loading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
  setSetup: (setup: AdminSetupSnapshot) => void;
} {
  const [setup, setSetup] = useState<AdminSetupSnapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setSetup(await api.getAdminSetup());
    } catch (err) {
      setError(errorMessage(err, "Admin setup failed"));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  return { setup, loading, error, refresh, setSetup };
}

function AdminSetupField({
  label,
  value,
  onChange,
  placeholder,
  suggestions,
  listId,
  type,
  helper,
  autoComplete,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  suggestions?: readonly string[];
  listId?: string;
  type?: "text" | "email" | "password" | "url";
  helper?: string;
  autoComplete?: string;
}) {
  const resolvedListId = suggestions && suggestions.length > 0 ? listId : undefined;
  return (
    <label className="block min-w-0">
      <span className="mb-1.5 block text-[12px] font-medium text-muted-foreground">{label}</span>
      <input
        type={type ?? "text"}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder}
        list={resolvedListId}
        autoComplete={autoComplete ?? (type === "password" ? "new-password" : "off")}
        spellCheck={type === "password" || type === "email" ? false : undefined}
        className="h-9 w-full rounded-md border border-border bg-card/60 px-3 text-[13px] text-foreground outline-none backdrop-blur-sm transition-colors placeholder:text-muted-foreground/50 focus:border-primary focus:ring-1 focus:ring-primary/30"
      />
      {helper && (
        <span className="mt-1.5 block text-[11.5px] leading-5 text-muted-foreground/80">{helper}</span>
      )}
      {resolvedListId && (
        <datalist id={resolvedListId}>
          {suggestions!.map((item) => (
            <option key={item} value={item} />
          ))}
        </datalist>
      )}
    </label>
  );
}

const PROVIDER_SUGGESTIONS = {
  email: ["Gmail", "Outlook", "Apple Mail"],
  calendar: ["Google Calendar", "Outlook Calendar", "Apple Calendar"],
  drive: ["Google Drive", "Dropbox", "SharePoint", "OneDrive"],
  crm: ["Lofty", "kvCORE", "BoldTrail", "Follow Up Boss", "Sierra Interactive", "Chime", "HubSpot"],
  mls: ["Matrix", "Paragon", "Xposure", "Stellar MLS", "MLS-Touch", "Realtor.ca"],
  forms: ["WEBForms", "TransactionDesk", "ZipForm", "Authentisign"],
  signing: ["DigiSign", "DocuSign", "Authentisign", "Dotloop", "PandaDoc"],
  compliance: ["SkySlope", "Lone Wolf", "Dotloop", "BrokerWolf"],
  showing: ["ShowingTime", "BrokerBay", "Aligned Showings", "ShowingSmart"],
  photo: ["Nano Banana", "Higgsfield", "BoxBrownie", "Virtual Staging AI"],
  fintrac: ["Fintracker", "Manual FIN# capture", "OneID", "Treefort"],
} as const;

type OnboardingFieldType = "text" | "textarea" | "province" | "email" | "password" | "url";

type OnboardingField = {
  key: keyof AdminSetupDraft;
  label: string;
  placeholder?: string;
  type?: OnboardingFieldType;
  suggestions?: readonly string[];
  listId?: string;
  helper?: string;
  fullWidth?: boolean;
  autoComplete?: string;
  optional?: boolean;
};

type OnboardingStep = {
  id: string;
  eyebrow: string;
  title: string;
  subtitle: string;
  banner?: { tone: "credentials" | "info"; text: string };
  fields: OnboardingField[];
};

const WIZARD_STEPS: OnboardingStep[] = [
  {
    id: "you",
    eyebrow: "Step 1 of 9",
    title: "Who's the realtor?",
    subtitle: "Legal name on file, the brokerage you hang your license at, and the team if you run one.",
    fields: [
      { key: "realtorLegalName", label: "Realtor legal name" },
      { key: "licenseName", label: "Licensed / public name", placeholder: "How it shows on listings" },
      { key: "brokerageName", label: "Brokerage" },
      { key: "teamName", label: "Team / PREC", placeholder: "Leave blank if you don't run a team", optional: true },
    ],
  },
  {
    id: "where",
    eyebrow: "Step 2 of 9",
    title: "Where do you work?",
    subtitle: "Province sets the legal forms and reference docs. Market and boards refine the playbook.",
    fields: [
      { key: "province", label: "Province / territory", type: "province" },
      { key: "market", label: "Primary market", placeholder: "Kamloops, Calgary..." },
      { key: "boardMemberships", label: "Board memberships", placeholder: "AOIR, FVREB...", helper: "Comma-separated. Leave blank if not a board member.", optional: true },
    ],
  },
  {
    id: "approval",
    eyebrow: "Step 3 of 9",
    title: "How does approval work?",
    subtitle: "Admin will pause for sign-off here. Tell it where to ping you and what it can / can't do without you.",
    fields: [
      { key: "managingBrokerEmail", label: "Managing broker / admin email" },
      { key: "approvalChannel", label: "Approval channel", placeholder: "Telegram Admin bot / lane" },
      {
        key: "approvalPolicy",
        label: "Approval policy",
        type: "textarea",
        placeholder: "What AI can draft / upload, what needs sign-off, whether docs / MLS / signing ever go out without a human.",
      },
    ],
  },
  {
    id: "daily-tools",
    eyebrow: "Step 4 of 9",
    title: "Daily tools",
    subtitle: "Email, calendar, and the cloud drive where deal folders live.",
    fields: [
      { key: "emailProvider", label: "Email", placeholder: "Gmail / Outlook account", suggestions: PROVIDER_SUGGESTIONS.email, listId: "onboard-email" },
      { key: "calendarProvider", label: "Calendar", placeholder: "Google Calendar / Outlook", suggestions: PROVIDER_SUGGESTIONS.calendar, listId: "onboard-calendar" },
      { key: "driveProvider", label: "Cloud drive", placeholder: "Google Drive / SharePoint", suggestions: PROVIDER_SUGGESTIONS.drive, listId: "onboard-drive" },
    ],
  },
  {
    id: "crm-mls",
    eyebrow: "Step 5 of 9",
    title: "CRM + MLS",
    subtitle: "Where leads live and where listings get published.",
    fields: [
      { key: "crmProvider", label: "CRM", placeholder: "Lofty, kvCORE, BoldTrail...", suggestions: PROVIDER_SUGGESTIONS.crm, listId: "onboard-crm" },
      { key: "mlsProvider", label: "MLS / board portal", placeholder: "Matrix, Xposure, Paragon...", suggestions: PROVIDER_SUGGESTIONS.mls, listId: "onboard-mls" },
    ],
  },
  {
    id: "documents",
    eyebrow: "Step 6 of 9",
    title: "Documents flow",
    subtitle: "How paperwork moves: form filler, signing, and compliance review.",
    fields: [
      { key: "formsProvider", label: "Forms provider", placeholder: "WEBForms / TransactionDesk", suggestions: PROVIDER_SUGGESTIONS.forms, listId: "onboard-forms" },
      { key: "signingProvider", label: "Signing provider", placeholder: "DigiSign / DocuSign", suggestions: PROVIDER_SUGGESTIONS.signing, listId: "onboard-signing" },
      { key: "complianceProvider", label: "Compliance platform", placeholder: "SkySlope / Lone Wolf", suggestions: PROVIDER_SUGGESTIONS.compliance, listId: "onboard-compliance" },
    ],
  },
  {
    id: "specialty",
    eyebrow: "Step 7 of 9",
    title: "Listings + verification",
    subtitle: "Showings, photo processing, and FINTRAC / ID workflow.",
    fields: [
      { key: "showingProvider", label: "Showing platform", placeholder: "ShowingTime / BrokerBay", suggestions: PROVIDER_SUGGESTIONS.showing, listId: "onboard-showing" },
      { key: "photoProcessingProvider", label: "Photo processing", placeholder: "Drive + Nano Banana / Higgsfield", suggestions: PROVIDER_SUGGESTIONS.photo, listId: "onboard-photo", optional: true, helper: "Leave blank if you don't run listing photos through a processor." },
      { key: "fintracProvider", label: "FINTRAC / ID workflow", placeholder: "Fintracker / manual FIN# capture", suggestions: PROVIDER_SUGGESTIONS.fintrac, listId: "onboard-fintrac" },
    ],
  },
  {
    id: "credentials",
    eyebrow: "Step 8 of 9",
    title: "Portal logins",
    subtitle: "Where Admin signs in to your MLS, compliance, and showing platforms on your behalf. If anything's already saved we'll keep it — leave fields blank to skip.",
    banner: {
      tone: "credentials",
      text: "Stored locally on this computer in a .env-style config the agent pulls from. Nothing leaves your machine and nothing is sent to a third-party LLM. Existing values are preserved unless you overwrite them.",
    },
    fields: [
      { key: "mlsLoginUrl", label: "MLS login URL", placeholder: "https://xposure.ca/login", type: "url", helper: "Paste the page you land on to sign in — full https:// URL. Leave blank to keep what's already saved.", fullWidth: true, optional: true },
      { key: "mlsLoginEmail", label: "MLS email / username", placeholder: "you@brokerage.com", type: "email", optional: true },
      { key: "mlsLoginPassword", label: "MLS password", placeholder: "•••••••••", type: "password", optional: true },
      { key: "complianceLoginUrl", label: "Compliance login URL", placeholder: "https://skyslope.com", type: "url", helper: "Where you log in to SkySlope / Lone Wolf / Dotloop. Leave blank to keep what's already saved.", fullWidth: true, optional: true },
      { key: "complianceLoginEmail", label: "Compliance email / username", placeholder: "you@brokerage.com", type: "email", optional: true },
      { key: "complianceLoginPassword", label: "Compliance password", placeholder: "•••••••••", type: "password", optional: true },
      { key: "showingLoginUrl", label: "Showing login URL", placeholder: "https://showingtime.com", type: "url", helper: "Where you log in to ShowingTime / BrokerBay. Leave blank to keep what's already saved.", fullWidth: true, optional: true },
      { key: "showingLoginEmail", label: "Showing email / username", placeholder: "you@brokerage.com", type: "email", optional: true },
      { key: "showingLoginPassword", label: "Showing password", placeholder: "•••••••••", type: "password", optional: true },
    ],
  },
  {
    id: "workflow",
    eyebrow: "Step 9 of 9",
    title: "How you work",
    subtitle: "A few specifics about folders, commissions, and your local market so Admin matches the way you already operate.",
    fields: [
      {
        key: "defaultFolderPattern",
        label: "Folder name pattern",
        placeholder: "{address} - {client} - {deal_type}",
        helper: "How Admin names new deal folders in your drive. The words in curly braces get filled in automatically — e.g. 123 Main St - Smith - Sell. Leave the default if you're not sure.",
        fullWidth: true,
      },
      {
        key: "commissionNotes",
        label: "Commission / service notes",
        placeholder: "Standard 7% on first $100K, 2.5% on balance. Confirm splits with broker per listing.",
        helper: "How you usually structure commissions or service fees. Plain English is fine — Admin reads this before filling listing paperwork.",
        fullWidth: true,
      },
      {
        key: "browserWorkflowNotes",
        label: "Browser-use notes",
        type: "textarea",
        helper: "Anything Admin should know when logging into your portals (extra MFA steps, where a button lives, etc). Optional.",
        placeholder: "Board portal quirks, browser profile, MFA expectations, where to find MLS number, showing feedback, compliance status, confirmation screens.",
        optional: true,
      },
      {
        key: "regionalMemory",
        label: "Regional memory",
        type: "textarea",
        placeholder: "We work mostly in Kamloops + the Okanagan. Deposits go to our brokerage trust within 24h. Showing feedback chases through ShowingTime, not phone.",
        helper: "Local market context Admin reads on every run — neighbourhoods, board rules, deposit timing, anything specific to where you work.",
      },
    ],
  },
];

function isBrandNewAdminSetup(setup: AdminSetupSnapshot): boolean {
  if (setup.completionPct > 0) return false;
  const profile = setup.profile ?? {};
  if ((profile.realtorLegalName ?? "").trim()) return false;
  if ((profile.brokerageName ?? "").trim()) return false;
  if ((profile.province ?? "").trim()) return false;
  return true;
}

function AdminOnboardingGate({ onStart, onSkip }: { onStart: () => void; onSkip: () => void }) {
  return (
    <section className="onboarding-overlay relative -mx-6 -my-6 flex min-h-[calc(100vh-9rem)] items-center justify-center overflow-hidden px-6 py-10">
      <div className="onboarding-aurora-bg pointer-events-none absolute inset-0" aria-hidden />
      <div className="relative flex max-w-md flex-col items-center text-center">
        <div className="onboarding-rise font-mono-ui text-[10px] uppercase tracking-[0.18em] text-muted-foreground">
          Admin · first run
        </div>
        <h1 className="onboarding-rise-delay-1 mt-3 text-[34px] font-medium leading-[1.05] tracking-tight text-foreground">
          Set up Elevate Admin
        </h1>
        <p className="onboarding-rise-delay-2 mt-3 max-w-sm text-[13.5px] leading-6 text-muted-foreground">
          A short guided run sets the realtor profile, province, tools, and approval lane. Two minutes, end-to-end.
        </p>
        <Button
          size="lg"
          onClick={onStart}
          className="onboarding-rise-delay-3 mt-7 h-12 min-w-[220px] px-6 text-[14px]"
        >
          <Sparkles className="h-4 w-4" />
          Run onboarding
        </Button>
        <button
          type="button"
          onClick={onSkip}
          className="onboarding-rise-delay-3 mt-4 text-[12px] text-muted-foreground underline-offset-2 hover:text-foreground hover:underline"
        >
          or skip to the full setup form
        </button>
      </div>
    </section>
  );
}

function AdminOnboardingWelcome({ onContinue }: { onContinue: () => void }) {
  const [exiting, setExiting] = useState(false);

  const handleStart = useCallback(() => {
    playOnboardingSwell();
    setExiting(true);
  }, []);

  const handleAnimationEnd = useCallback(
    (event: React.AnimationEvent<HTMLDivElement>) => {
      if (event.target !== event.currentTarget) return;
      if (exiting) onContinue();
    },
    [exiting, onContinue],
  );

  return createPortal(
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Welcome to Elevate Admin"
      className={cn(
        "onboarding-overlay fixed inset-0 z-[100] flex items-center justify-center overflow-hidden",
        exiting && "onboarding-exit",
      )}
      onAnimationEnd={handleAnimationEnd}
    >
      <div className="onboarding-aurora-bg pointer-events-none absolute inset-0" aria-hidden />
      <div className="relative flex max-w-xl flex-col items-center px-6 text-center">
        <div className="onboarding-rise font-mono-ui text-[10px] uppercase tracking-[0.2em] text-muted-foreground">
          Elevate · Admin
        </div>
        <h1 className="onboarding-rise-delay-1 mt-4 text-[52px] font-medium leading-[1.02] tracking-tight text-foreground">
          Welcome to Elevate Admin.
        </h1>
        <p className="onboarding-rise-delay-2 mt-4 max-w-lg text-[15px] leading-7 text-muted-foreground">
          A few quick questions and Admin starts running listings, conditions, and closings alongside you.
        </p>
        <Button
          size="lg"
          onClick={handleStart}
          disabled={exiting}
          className="onboarding-rise-delay-3 mt-9 h-12 min-w-[240px] px-7 text-[14px]"
        >
          Let's get started
        </Button>
      </div>
    </div>,
    document.body,
  );
}

function AdminOnboardingWizard({
  draft,
  updateDraft,
  onAdvanceSave,
  onFinish,
  saving,
  verifying,
  error,
  savedMessage,
  provinceCoverage,
  savedProvinceCode,
}: {
  draft: AdminSetupDraft;
  updateDraft: (field: keyof AdminSetupDraft, value: string) => void;
  onAdvanceSave: () => Promise<void>;
  onFinish: () => Promise<void>;
  saving: boolean;
  verifying: boolean;
  error: string | null;
  savedMessage: string | null;
  provinceCoverage: AdminProvinceGuideCoverage[];
  savedProvinceCode: string;
}) {
  const [stepIdx, setStepIdx] = useState(0);
  const [showMissing, setShowMissing] = useState(false);
  const step = WIZARD_STEPS[stepIdx];
  const isLast = stepIdx === WIZARD_STEPS.length - 1;
  const isFirst = stepIdx === 0;
  const busy = saving || verifying;

  const missingFields = useMemo(() => {
    return step.fields.filter((field) => {
      if (field.optional) return false;
      const raw = draft[field.key];
      const value = typeof raw === "string" ? raw.trim() : "";
      return value.length === 0;
    });
  }, [step, draft]);
  const canAdvance = missingFields.length === 0;
  useEffect(() => {
    setShowMissing(false);
  }, [stepIdx]);

  const provinceCoverageByCode = useMemo(
    () => new Map(provinceCoverage.map((item) => [item.province, item])),
    [provinceCoverage],
  );
  const selectedProvinceCoverage = provinceCoverageByCode.get(draft.province.trim().toUpperCase());

  const handleNext = useCallback(async () => {
    if (busy) return;
    if (!canAdvance) {
      setShowMissing(true);
      return;
    }
    playOnboardingClick();
    await onAdvanceSave();
    if (isLast) {
      playOnboardingSwell();
      await onFinish();
      return;
    }
    setStepIdx((idx) => Math.min(idx + 1, WIZARD_STEPS.length - 1));
  }, [busy, canAdvance, isLast, onAdvanceSave, onFinish]);

  const handleBack = useCallback(() => {
    if (busy) return;
    playOnboardingClick();
    setStepIdx((idx) => Math.max(idx - 1, 0));
  }, [busy]);

  return createPortal(
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Admin onboarding wizard"
      className="onboarding-overlay fixed inset-0 z-[100] flex items-center justify-center overflow-y-auto px-6 py-10"
    >
      <div className="onboarding-aurora-bg pointer-events-none absolute inset-0" aria-hidden />
      <div className="relative flex w-full max-w-2xl flex-col">
        <div className="mb-7 flex items-center gap-1.5">
          {WIZARD_STEPS.map((s, idx) => (
            <span
              key={s.id}
              aria-hidden
              className={cn(
                "h-1 flex-1 rounded-sm transition-colors duration-300",
                idx <= stepIdx ? "bg-primary" : "bg-border/60",
              )}
            />
          ))}
        </div>

        <div key={stepIdx} className="flex flex-col">
          <div className="onboarding-rise font-mono-ui text-[10px] uppercase tracking-[0.2em] text-muted-foreground">
            {step.eyebrow}
          </div>
          <h2 className="onboarding-rise-delay-1 mt-3 text-[34px] font-medium leading-[1.05] tracking-tight text-foreground">
            {step.title}
          </h2>
          <p className="onboarding-rise-delay-2 mt-3 max-w-xl text-[14px] leading-7 text-muted-foreground">
            {step.subtitle}
          </p>

          {step.banner && (
            <div className="onboarding-rise-delay-2 mt-6 flex items-start gap-3 rounded-md border border-border bg-card/60 px-4 py-3 backdrop-blur-sm">
              <Lock className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground" />
              <p className="text-[12.5px] leading-5 text-muted-foreground">
                {step.banner.text}
              </p>
            </div>
          )}

          <div className="onboarding-rise-delay-3 mt-8 grid gap-4 md:grid-cols-2">
            {step.fields.map((field) => {
              if (field.type === "province") {
                return (
                  <OnboardingProvinceField
                    key={field.key}
                    draft={draft}
                    updateDraft={updateDraft}
                    provinceCoverageByCode={provinceCoverageByCode}
                    selectedProvinceCoverage={selectedProvinceCoverage}
                    savedProvinceCode={savedProvinceCode}
                  />
                );
              }
              if (field.type === "textarea") {
                return (
                  <label key={field.key} className="block min-w-0 md:col-span-2">
                    <span className="mb-1.5 block text-[12px] font-medium text-muted-foreground">
                      {field.label}
                    </span>
                    <textarea
                      value={draft[field.key]}
                      onChange={(event) => updateDraft(field.key, event.target.value)}
                      placeholder={field.placeholder}
                      className="min-h-28 w-full rounded-md border border-border bg-card/60 px-3 py-2 text-[13px] leading-5 text-foreground outline-none backdrop-blur-sm transition-colors placeholder:text-muted-foreground/60 focus:border-primary focus:ring-1 focus:ring-primary/30"
                    />
                    {field.helper && (
                      <span className="mt-1.5 block text-[11.5px] leading-5 text-muted-foreground/80">
                        {field.helper}
                      </span>
                    )}
                  </label>
                );
              }
              return (
                <div key={field.key} className={cn("min-w-0", field.fullWidth && "md:col-span-2")}>
                  <AdminSetupField
                    label={field.label}
                    placeholder={field.placeholder}
                    value={draft[field.key]}
                    onChange={(value) => updateDraft(field.key, value)}
                    suggestions={field.suggestions}
                    listId={field.listId}
                    type={
                      field.type === "email" || field.type === "password" || field.type === "url"
                        ? field.type
                        : "text"
                    }
                    helper={field.helper}
                    autoComplete={field.autoComplete}
                  />
                </div>
              );
            })}
          </div>
        </div>

        {(error || savedMessage) && (
          <div className={cn(
            "mt-6 flex items-baseline gap-3 border-t py-3 text-[13px]",
            error ? "border-destructive" : "border-success",
          )}>
            <span className={cn(
              "shrink-0 font-mono-ui text-[10px] uppercase tracking-wider",
              error ? "text-destructive" : "text-success",
            )}>
              {error ? "Error" : "Saved"}
            </span>
            <span className="text-foreground">{error || savedMessage}</span>
          </div>
        )}

        <div className="mt-9 flex items-center justify-between gap-3 border-t border-border/60 pt-5">
          <div className="min-h-[18px] flex-1 text-[12px] leading-5 text-muted-foreground/80">
            {showMissing && !canAdvance && (
              <span className="text-destructive">
                Fill in {missingFields.map((f) => `"${f.label}"`).join(", ")} before continuing.
              </span>
            )}
          </div>
          <div className="flex shrink-0 items-center gap-2">
            <Button variant="outline" onClick={handleBack} disabled={busy || isFirst}>
              Back
            </Button>
            <Button
              onClick={() => void handleNext()}
              disabled={busy || !canAdvance}
              className="min-w-[140px]"
            >
              {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
              {isLast ? "Run the setup" : "Continue"}
            </Button>
          </div>
        </div>
      </div>
    </div>,
    document.body,
  );
}

type OnboardingSeedingStep = {
  id: string;
  label: string;
  detail: string;
};

const ONBOARDING_SEEDING_STEPS: OnboardingSeedingStep[] = [
  { id: "save", label: "Saving your profile", detail: "Persisting realtor, brokerage, and approval policy" },
  { id: "province", label: "Importing province forms", detail: "Reference pages, checklists, and form pack" },
  { id: "playbook", label: "Synthesizing your agent playbook", detail: "Province-specific terminology and stage docs" },
  { id: "connectors", label: "Checking connected systems", detail: "Composio toolkits, source channels, env keys" },
  { id: "wrap", label: "Wrapping up", detail: "Finalizing setup state and readiness gates" },
];

function AdminOnboardingSeeding({
  onMissing,
  onComplete,
  runSeed,
}: {
  onMissing: () => void;
  onComplete: () => void;
  runSeed: () => Promise<{ missing: boolean; error: string | null }>;
}) {
  const [activeIdx, setActiveIdx] = useState(0);
  const [seedDone, setSeedDone] = useState(false);
  const [seedResult, setSeedResult] = useState<{ missing: boolean; error: string | null } | null>(null);

  useEffect(() => {
    let cancelled = false;
    runSeed()
      .then((result) => {
        if (!cancelled) setSeedResult(result);
      })
      .catch((err) => {
        if (!cancelled) setSeedResult({ missing: true, error: String(err?.message ?? err) });
      });
    return () => {
      cancelled = true;
    };
  }, [runSeed]);

  useEffect(() => {
    if (activeIdx >= ONBOARDING_SEEDING_STEPS.length) {
      setSeedDone(true);
      return;
    }
    const id = window.setTimeout(() => {
      setActiveIdx((idx) => idx + 1);
    }, 1600);
    return () => window.clearTimeout(id);
  }, [activeIdx]);

  useEffect(() => {
    if (!seedDone || !seedResult) return;
    const finishId = window.setTimeout(() => {
      if (seedResult.missing) onMissing();
      else onComplete();
    }, 500);
    return () => window.clearTimeout(finishId);
  }, [seedDone, seedResult, onMissing, onComplete]);

  return createPortal(
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Setting up Admin"
      className="onboarding-overlay fixed inset-0 z-[100] flex items-center justify-center overflow-hidden"
    >
      <div className="onboarding-aurora-bg pointer-events-none absolute inset-0" aria-hidden />
      <div className="relative flex w-full max-w-lg flex-col px-6">
        <div className="onboarding-rise font-mono-ui text-[10px] uppercase tracking-[0.18em] text-muted-foreground">
          Admin · running databases
        </div>
        <h2 className="onboarding-rise-delay-1 mt-3 text-[28px] font-medium leading-[1.1] tracking-tight text-foreground">
          Running databases. This will take a few minutes.
        </h2>
        <p className="onboarding-rise-delay-2 mt-2 max-w-md text-[13.5px] leading-6 text-muted-foreground">
          Importing your province pack, seeding the agent playbook, and checking what's already connected. You can keep chatting with the coach while this runs.
        </p>

        <ul className="onboarding-rise-delay-3 mt-7 flex flex-col gap-3">
          {ONBOARDING_SEEDING_STEPS.map((step, idx) => {
            const done = idx < activeIdx || (seedDone && seedResult);
            const active = idx === activeIdx && !seedDone;
            return (
              <li key={step.id} className="flex items-start gap-3">
                <span
                  aria-hidden
                  className={cn(
                    "mt-0.5 inline-flex h-5 w-5 items-center justify-center rounded-full border",
                    done && "onboarding-step-check border-success bg-success/10 text-success",
                    active && "onboarding-step-pulse border-primary bg-primary/15 text-primary",
                    !done && !active && "border-border bg-card text-muted-foreground",
                  )}
                >
                  {done ? (
                    <CheckCircle2 className="h-3.5 w-3.5" />
                  ) : active ? (
                    <Loader2 className="h-3 w-3 animate-spin" />
                  ) : (
                    <span className="h-1.5 w-1.5 rounded-full bg-muted-foreground/60" />
                  )}
                </span>
                <div className="min-w-0">
                  <div
                    className={cn(
                      "text-[13.5px] leading-5",
                      done ? "text-foreground" : active ? "text-foreground" : "text-muted-foreground/80",
                    )}
                  >
                    {step.label}
                  </div>
                  <div className="text-[11.5px] leading-4 text-muted-foreground">{step.detail}</div>
                </div>
              </li>
            );
          })}
        </ul>

        {seedResult?.error && (
          <div className="onboarding-rise-delay-3 mt-6 rounded-md border border-destructive/50 bg-destructive/10 px-3 py-2 text-[12px] text-destructive">
            {seedResult.error}
          </div>
        )}
      </div>
    </div>,
    document.body,
  );
}

type OnboardingConnectorAction =
  | { kind: "composio"; toolkitSlug: string; label: string }
  | { kind: "browser-use"; portalKey: "mls" | "compliance" | "showing"; label: string }
  | { kind: "manual"; helpText: string };

type OnboardingConnectorCard = {
  key: string;
  title: string;
  question: string;
  helpText: string;
  icon: typeof Cloud;
  action: OnboardingConnectorAction;
};

const ONBOARDING_CONNECTOR_TEMPLATES: Record<string, Omit<OnboardingConnectorCard, "key">> = {
  drive: {
    title: "Cloud drive",
    question: "Where do your active deal folders live today?",
    helpText: "Google Drive, Dropbox, or SharePoint — pick the one that holds your listing folders.",
    icon: Cloud,
    action: { kind: "composio", toolkitSlug: "googledrive", label: "Connect Google Drive" },
  },
  email: {
    title: "Email",
    question: "Which inbox handles your client and broker email?",
    helpText: "We'll connect your Gmail or Outlook so Admin can read attachments and draft replies.",
    icon: Mail,
    action: { kind: "composio", toolkitSlug: "gmail", label: "Connect Gmail" },
  },
  calendar: {
    title: "Calendar",
    question: "Which calendar holds showings and consults?",
    helpText: "Google Calendar or Outlook — we'll pull events and schedule new ones.",
    icon: CalendarClock,
    action: { kind: "composio", toolkitSlug: "googlecalendar", label: "Connect Google Calendar" },
  },
  crm: {
    title: "CRM",
    question: "Where do your leads live right now? A spreadsheet works too.",
    helpText: "Lofty, kvCORE, BoldTrail, or a Sheet path — tell the coach and we'll import.",
    icon: DatabaseIcon,
    action: { kind: "manual", helpText: "Tell the onboarding coach where your leads live and it'll set up the right sync." },
  },
  mls: {
    title: "MLS / board portal",
    question: "What's your MLS login URL? We'll log in and scan your dashboard.",
    helpText: "Save the URL + login email + password under Portal logins, then hit Connect & analyze to launch the browser session.",
    icon: Globe,
    action: { kind: "browser-use", portalKey: "mls", label: "Connect & analyze MLS" },
  },
  compliance_platform: {
    title: "Compliance platform",
    question: "Where does compliance review happen?",
    helpText: "SkySlope, Lone Wolf, or similar — same flow: URL + email + password → analyze.",
    icon: ShieldCheck,
    action: { kind: "browser-use", portalKey: "compliance", label: "Connect & analyze compliance" },
  },
  showing_platform: {
    title: "Showing platform",
    question: "Which platform schedules your showings?",
    helpText: "ShowingTime, BrokerBay, or similar — analyze to capture feedback flow.",
    icon: KeyRound,
    action: { kind: "browser-use", portalKey: "showing", label: "Connect & analyze showings" },
  },
};

const ONBOARDING_CONNECTOR_KEY_ORDER = [
  "drive",
  "email",
  "calendar",
  "crm",
  "mls",
  "compliance_platform",
  "showing_platform",
];

function buildOnboardingConnectorCards(setup: AdminSetupSnapshot): OnboardingConnectorCard[] {
  const itemByKey = new Map(setup.items.map((it) => [it.key, it]));
  const cards: OnboardingConnectorCard[] = [];
  for (const key of ONBOARDING_CONNECTOR_KEY_ORDER) {
    const tpl = ONBOARDING_CONNECTOR_TEMPLATES[key];
    if (!tpl) continue;
    const item = itemByKey.get(key);
    const status = item?.status ?? "missing";
    if (status === "configured" || status === "connected") continue;
    cards.push({ key, ...tpl });
  }
  return cards;
}

function AdminOnboardingConnectors({
  setup,
  onContinue,
  onChatMention,
  onRefreshSetup,
}: {
  setup: AdminSetupSnapshot;
  onContinue: () => void;
  onChatMention: (key: string) => void;
  onRefreshSetup: () => Promise<void>;
}) {
  const cards = useMemo(() => buildOnboardingConnectorCards(setup), [setup]);
  const [pendingBrowserKey, setPendingBrowserKey] = useState<string | null>(null);
  const [pendingComposioKey, setPendingComposioKey] = useState<string | null>(null);
  const [results, setResults] = useState<Record<string, { ok: boolean; message: string; runUrl?: string | null }>>({});
  const [refreshing, setRefreshing] = useState(false);
  const lastRefreshAtRef = useRef<number>(0);

  const refresh = useCallback(async () => {
    const now = Date.now();
    if (now - lastRefreshAtRef.current < 4000) return;
    lastRefreshAtRef.current = now;
    setRefreshing(true);
    try {
      await onRefreshSetup();
    } finally {
      setRefreshing(false);
    }
  }, [onRefreshSetup]);

  useEffect(() => {
    const onFocus = () => {
      void refresh();
    };
    const onVisibility = () => {
      if (document.visibilityState === "visible") void refresh();
    };
    window.addEventListener("focus", onFocus);
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      window.removeEventListener("focus", onFocus);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [refresh]);

  const runComposio = useCallback(async (cardKey: string, toolkitSlug: string) => {
    setPendingComposioKey(cardKey);
    try {
      const resp = await api.initiateComposioConnection({ toolkitSlug });
      if (!resp.ok) {
        setResults((r) => ({ ...r, [cardKey]: { ok: false, message: resp.error ?? "Connection failed" } }));
        return;
      }
      const redirect = (resp.data as { redirect_url?: string; url?: string } | undefined)?.redirect_url
        ?? (resp.data as { url?: string } | undefined)?.url;
      if (redirect) {
        window.open(redirect, "_blank", "noopener,noreferrer");
        setResults((r) => ({ ...r, [cardKey]: { ok: true, message: "Approve the connection in the new tab, then come back." } }));
      } else {
        setResults((r) => ({ ...r, [cardKey]: { ok: true, message: "Connection initiated. Check Tools → Composio." } }));
      }
    } catch (err) {
      setResults((r) => ({ ...r, [cardKey]: { ok: false, message: String((err as Error)?.message ?? err) } }));
    } finally {
      setPendingComposioKey(null);
    }
  }, []);

  const runBrowserUse = useCallback(async (cardKey: string, portalKey: "mls" | "compliance" | "showing") => {
    setPendingBrowserKey(cardKey);
    try {
      const resp = await api.launchAdminOnboardingBrowserUse(portalKey);
      if (!resp.ok) {
        setResults((r) => ({ ...r, [cardKey]: { ok: false, message: resp.error ?? "Launch failed" } }));
        return;
      }
      setResults((r) => ({
        ...r,
        [cardKey]: {
          ok: true,
          message: resp.taskId ? `Launched browser-use task ${resp.taskId}` : "Launched browser-use task.",
          runUrl: resp.runUrl ?? null,
        },
      }));
    } catch (err) {
      setResults((r) => ({ ...r, [cardKey]: { ok: false, message: String((err as Error)?.message ?? err) } }));
    } finally {
      setPendingBrowserKey(null);
    }
  }, []);

  if (cards.length === 0) {
    return (
      <section className="border-t border-border pt-6">
        <div className="mx-auto flex max-w-2xl flex-col items-start">
          <div className="font-mono-ui text-[10px] uppercase tracking-[0.18em] text-muted-foreground">
            Admin · connectors
          </div>
          <h2 className="mt-3 text-[24px] font-medium leading-tight tracking-tight text-foreground">
            Everything's connected.
          </h2>
          <p className="mt-2 text-[13.5px] leading-6 text-muted-foreground">
            No outstanding connectors. Admin is ready to run.
          </p>
          <Button className="mt-6" onClick={onContinue}>
            Open Admin
          </Button>
        </div>
      </section>
    );
  }

  return (
    <section className="border-t border-border pt-6">
      <div className="mx-auto flex max-w-3xl flex-col">
        <div className="font-mono-ui text-[10px] uppercase tracking-[0.18em] text-muted-foreground">
          Admin · connectors
        </div>
        <h2 className="mt-3 text-[24px] font-medium leading-tight tracking-tight text-foreground">
          Connect your systems
        </h2>
        <p className="mt-2 max-w-2xl text-[13.5px] leading-6 text-muted-foreground">
          The coach on the right will walk you through each one. For browser-based portals, save the URL + email + password first, then hit Connect & analyze — Admin launches browser-use and scans the dashboard.
        </p>

        <div className="mt-4 flex items-center gap-2 text-[12px] text-muted-foreground">
          <span>Connections refresh automatically when you come back from a connect tab.</span>
          <button
            type="button"
            onClick={() => void refresh()}
            disabled={refreshing}
            className="inline-flex items-center gap-1 text-foreground underline-offset-2 hover:underline disabled:opacity-50"
          >
            {refreshing ? <Loader2 className="h-3 w-3 animate-spin" /> : null}
            Refresh now
          </button>
        </div>

        <div className="mt-5 flex flex-col gap-3">
          {cards.map((card) => {
            const Icon = card.icon;
            const result = results[card.key];
            const composioBusy = pendingComposioKey === card.key;
            const browserBusy = pendingBrowserKey === card.key;
            const busy = composioBusy || browserBusy;
            return (
              <div
                key={card.key}
                className="flex flex-col gap-3 rounded-md border border-border bg-card/70 p-4 md:flex-row md:items-start"
              >
                <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md border border-border bg-muted/30 text-muted-foreground">
                  <Icon className="h-4 w-4" />
                </div>
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-baseline justify-between gap-2">
                    <div className="text-[14px] font-medium text-foreground">{card.title}</div>
                    <span className="font-mono-ui text-[0.6rem] uppercase tracking-wider text-muted-foreground">
                      missing
                    </span>
                  </div>
                  <p className="mt-1 text-[13px] leading-5 text-foreground/80">{card.question}</p>
                  <p className="mt-1 text-[12px] leading-5 text-muted-foreground">{card.helpText}</p>

                  {result && (
                    <div
                      className={cn(
                        "mt-3 rounded-md border px-3 py-2 text-[12px]",
                        result.ok
                          ? "border-success/40 bg-success/10 text-success"
                          : "border-destructive/40 bg-destructive/10 text-destructive",
                      )}
                    >
                      {result.message}
                      {result.runUrl && (
                        <a
                          href={result.runUrl}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="ml-2 inline-flex items-center gap-1 underline underline-offset-2"
                        >
                          Open task <ExternalLink className="h-3 w-3" />
                        </a>
                      )}
                    </div>
                  )}
                </div>
                <div className="flex shrink-0 flex-col items-stretch gap-2 md:items-end">
                  {card.action.kind === "composio" && (
                    <Button
                      size="sm"
                      onClick={() => void runComposio(card.key, card.action.kind === "composio" ? card.action.toolkitSlug : "")}
                      disabled={busy}
                    >
                      {composioBusy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
                      {card.action.label}
                    </Button>
                  )}
                  {card.action.kind === "browser-use" && (
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => void runBrowserUse(card.key, card.action.kind === "browser-use" ? card.action.portalKey : "mls")}
                      disabled={busy}
                    >
                      {browserBusy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
                      {card.action.label}
                    </Button>
                  )}
                  {card.action.kind === "manual" && (
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => onChatMention(card.key)}
                    >
                      <MessageCircle className="h-3.5 w-3.5" />
                      Ask the coach
                    </Button>
                  )}
                </div>
              </div>
            );
          })}
        </div>

        <div className="mt-8 flex items-center justify-between border-t border-border pt-5">
          <button
            type="button"
            onClick={onContinue}
            className="text-[12px] text-muted-foreground underline-offset-2 hover:text-foreground hover:underline"
          >
            Finish later — open Admin anyway
          </button>
          <Button onClick={onContinue}>Done — open Admin</Button>
        </div>
      </div>
    </section>
  );
}

type CoachMessage = { role: "user" | "assistant"; content: string };

const COACH_URL_REGEX = /(https?:\/\/[^\s<>"')]+)/g;

function renderCoachContent(text: string): React.ReactNode {
  if (!text.includes("http")) return text;
  const parts = text.split(COACH_URL_REGEX);
  return parts.map((part, idx) => {
    if (idx % 2 === 1) {
      const cleaned = part.replace(/[.,;:!?]+$/, "");
      const trailing = part.slice(cleaned.length);
      return (
        <React.Fragment key={idx}>
          <a
            href={cleaned}
            target="_blank"
            rel="noreferrer noopener"
            className="text-primary underline underline-offset-2 break-all hover:text-primary/80"
          >
            {cleaned}
          </a>
          {trailing}
        </React.Fragment>
      );
    }
    return <React.Fragment key={idx}>{part}</React.Fragment>;
  });
}

function AdminOnboardingCoach({
  initialQuestion,
  onClose,
  onReset,
  externalMention,
  messages,
  setMessages,
}: {
  initialQuestion: string;
  onClose: () => void;
  onReset?: () => void;
  externalMention: string | null;
  messages: CoachMessage[];
  setMessages: React.Dispatch<React.SetStateAction<CoachMessage[]>>;
}) {
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const scrollRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    setMessages((prev) => (prev.length > 0 ? prev : [{ role: "assistant", content: initialQuestion }]));
  }, [initialQuestion, setMessages]);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages]);

  useEffect(() => {
    if (!externalMention) return;
    setInput((prev) => (prev ? prev : `Help me set up ${externalMention.replace(/_/g, " ")}.`));
  }, [externalMention]);

  const send = useCallback(async () => {
    const trimmed = input.trim();
    if (!trimmed || sending) return;
    const next = [...messages, { role: "user" as const, content: trimmed }];
    setMessages(next);
    setInput("");
    setSending(true);
    setError(null);
    try {
      const resp = await api.postAdminOnboardingChat(next);
      const reply = resp.reply?.trim() || "(no reply)";
      setMessages((prev) => [...prev, { role: "assistant", content: reply }]);
    } catch (err) {
      setError(String((err as Error)?.message ?? err));
    } finally {
      setSending(false);
    }
  }, [input, messages, sending]);

  return createPortal(
    <aside
      role="complementary"
      aria-label="Onboarding coach"
      className="onboarding-coach fixed bottom-6 right-6 z-[110] flex w-[360px] max-w-[calc(100vw-3rem)] flex-col overflow-hidden rounded-lg border border-border bg-card shadow-xl"
    >
      <header className="flex items-center justify-between border-b border-border bg-muted/30 px-4 py-2.5">
        <div className="flex items-center gap-2">
          <MessageCircle className="h-3.5 w-3.5 text-primary" />
          <div className="text-[12.5px] font-medium text-foreground">Onboarding coach</div>
        </div>
        <div className="flex items-center gap-1">
          {onReset && (
            <button
              type="button"
              onClick={onReset}
              aria-label="Reset onboarding coach chat"
              title="Reset chat"
              className="rounded-md p-1 text-muted-foreground hover:bg-muted/40 hover:text-foreground"
            >
              <RotateCcw className="h-3.5 w-3.5" />
            </button>
          )}
          <button
            type="button"
            onClick={onClose}
            aria-label="Close onboarding coach"
            className="rounded-md p-1 text-muted-foreground hover:bg-muted/40 hover:text-foreground"
          >
            <CloseIcon className="h-3.5 w-3.5" />
          </button>
        </div>
      </header>

      <div ref={scrollRef} className="flex max-h-[360px] min-h-[180px] flex-col gap-2 overflow-y-auto px-3 py-3">
        {messages.map((msg, idx) => (
          <div
            key={idx}
            className={cn(
              "max-w-[88%] whitespace-pre-wrap rounded-md px-3 py-2 text-[12.5px] leading-5",
              msg.role === "assistant"
                ? "self-start bg-muted/40 text-foreground"
                : "self-end bg-primary/15 text-foreground",
            )}
          >
            {msg.role === "assistant" ? renderCoachContent(msg.content) : msg.content}
          </div>
        ))}
        {sending && (
          <div className="self-start rounded-md bg-muted/40 px-3 py-2 text-[12.5px] text-muted-foreground">
            <Loader2 className="inline-block h-3 w-3 animate-spin" /> Thinking…
          </div>
        )}
        {error && (
          <div className="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-[12px] text-destructive">
            {error}
          </div>
        )}
      </div>

      <footer className="flex items-end gap-2 border-t border-border bg-background px-3 py-2.5">
        <textarea
          rows={2}
          value={input}
          onChange={(event) => setInput(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey) {
              event.preventDefault();
              void send();
            }
          }}
          placeholder="Type — ↩ to send, ⇧↩ for newline"
          className="min-h-9 max-h-32 flex-1 resize-none rounded-md border border-border bg-background px-2 py-1.5 text-[12.5px] leading-5 text-foreground outline-none focus:border-primary focus:ring-1 focus:ring-primary/30"
        />
        <Button size="sm" onClick={() => void send()} disabled={sending || !input.trim()}>
          <Send className="h-3.5 w-3.5" />
        </Button>
      </footer>
    </aside>,
    document.body,
  );
}

function OnboardingProvinceField({
  draft,
  updateDraft,
  provinceCoverageByCode,
  selectedProvinceCoverage,
  savedProvinceCode,
}: {
  draft: AdminSetupDraft;
  updateDraft: (field: keyof AdminSetupDraft, value: string) => void;
  provinceCoverageByCode: Map<string, AdminProvinceGuideCoverage>;
  selectedProvinceCoverage: AdminProvinceGuideCoverage | undefined;
  savedProvinceCode: string;
}) {
  const [unlocked, setUnlocked] = useState(false);
  const locked = Boolean(savedProvinceCode) && !unlocked;
  return (
    <label className="block min-w-0 md:col-span-2">
      <div className="mb-1.5 flex items-center justify-between gap-2">
        <span className="block text-[12px] font-medium text-muted-foreground">Province / territory</span>
        <div className="flex items-center gap-2">
          {locked && (
            <button
              type="button"
              onClick={() => setUnlocked(true)}
              className="text-[11px] text-muted-foreground underline-offset-2 hover:text-foreground hover:underline"
            >
              Change
            </button>
          )}
          <span className="font-mono-ui text-[0.58rem] uppercase tracking-wider text-muted-foreground/80">CA · Canada</span>
        </div>
      </div>
      {locked ? (
        <div className="flex h-9 w-full items-center rounded-md border border-border bg-muted/40 px-3 text-[13px] text-foreground">
          <span>{PROVINCE_LABEL_BY_CODE.get(savedProvinceCode) ?? savedProvinceCode}</span>
          <span className="ml-2 font-mono-ui text-[0.58rem] uppercase tracking-wider text-muted-foreground">
            saved
          </span>
        </div>
      ) : (
        <select
          value={draft.province.trim().toUpperCase()}
          onChange={(event) => updateDraft("province", event.target.value)}
          className="h-9 w-full rounded-md border border-border bg-background px-3 text-[13px] text-foreground outline-none transition-colors focus:border-primary focus:ring-1 focus:ring-primary/30"
        >
          <option value="">Select province</option>
          {CANADIAN_PROVINCES.map(({ code, label }) => {
            const coverage = provinceCoverageByCode.get(code);
            const suffix = coverage?.hasTransactionGuide ? " — full guide" : coverage ? " — reference" : "";
            return (
              <option key={code} value={code}>
                {label}
                {suffix}
              </option>
            );
          })}
        </select>
      )}
      {selectedProvinceCoverage && (
        <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
          <span className="font-mono-ui rounded border border-border bg-card px-1.5 py-0.5 text-[0.58rem] uppercase tracking-wider text-muted-foreground">
            {selectedProvinceCoverage.hasTransactionGuide ? "full guide" : "reference"}
          </span>
          <span className="font-mono-ui rounded border border-border bg-card px-1.5 py-0.5 text-[0.58rem] uppercase tracking-wider text-muted-foreground">
            {selectedProvinceCoverage.referencePages} pages
          </span>
          {selectedProvinceCoverage.forms > 0 && (
            <span className="font-mono-ui rounded border border-border bg-card px-1.5 py-0.5 text-[0.58rem] uppercase tracking-wider text-muted-foreground">
              {selectedProvinceCoverage.forms} forms
            </span>
          )}
          {selectedProvinceCoverage.checklists > 0 && (
            <span className="font-mono-ui rounded border border-border bg-card px-1.5 py-0.5 text-[0.58rem] uppercase tracking-wider text-muted-foreground">
              {selectedProvinceCoverage.checklists} checklists
            </span>
          )}
        </div>
      )}
      {draft.province.trim() && !selectedProvinceCoverage && (
        <div className="mt-1.5 text-[11px] text-muted-foreground">
          No local guide for this province yet — fall back to manual references.
        </div>
      )}
    </label>
  );
}

function AdminSetupLaunch({
  setup,
  onSetupUpdated,
  forceOnboarding = false,
  onForceOnboardingDone,
  openCoach,
  setCoachMention,
}: {
  setup: AdminSetupSnapshot;
  onSetupUpdated: (setup: AdminSetupSnapshot) => void;
  forceOnboarding?: boolean;
  onForceOnboardingDone?: () => void;
  openCoach: () => void;
  setCoachMention: (key: string | null) => void;
}) {
  const [draft, setDraft] = useState<AdminSetupDraft>(() => adminSetupDraftFromSnapshot(setup));
  const [saving, setSaving] = useState(false);
  const [verifying, setVerifying] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [savedMessage, setSavedMessage] = useState<string | null>(null);
  const [provinceCoverage, setProvinceCoverage] = useState<AdminProvinceGuideCoverage[]>([]);
  const [provinceUnlocked, setProvinceUnlocked] = useState(false);
  const [phase, setPhase] = useState<"gate" | "welcome" | "wizard" | "seeding" | "connectors" | "form">(() =>
    forceOnboarding ? "welcome" : isBrandNewAdminSetup(setup) ? "gate" : "form",
  );

  useEffect(() => {
    if (forceOnboarding && phase === "form") {
      onForceOnboardingDone?.();
    }
  }, [forceOnboarding, phase, onForceOnboardingDone]);

  useEffect(() => {
    if (phase === "seeding" || phase === "connectors") {
      openCoach();
    }
  }, [phase, openCoach]);

  const savedProvinceCode = (setup.profile?.province || "").trim().toUpperCase();

  useEffect(() => {
    setDraft(adminSetupDraftFromSnapshot(setup));
  }, [setup]);

  useEffect(() => {
    // Re-lock province when setup snapshot saves a new value.
    setProvinceUnlocked(false);
  }, [savedProvinceCode]);

  useEffect(() => {
    let cancelled = false;
    api
      .getAdminProvinceGuides()
      .then((guides) => {
        if (cancelled) return;
        if ("items" in guides) setProvinceCoverage(guides.items);
      })
      .catch(() => {
        if (!cancelled) setProvinceCoverage([]);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const provinceCoverageByCode = useMemo(
    () => new Map(provinceCoverage.map((item) => [item.province, item])),
    [provinceCoverage],
  );
  const selectedProvinceCoverage = provinceCoverageByCode.get(draft.province.trim().toUpperCase());

  const updateDraft = useCallback(
    (field: keyof AdminSetupDraft, value: string) => {
      setDraft((prev) => ({ ...prev, [field]: value }));
    },
    [],
  );

  const submit = useCallback(async () => {
    setSaving(true);
    setError(null);
    setSavedMessage(null);
    try {
      const updated = await api.updateAdminSetup(adminSetupPayloadFromDraft(draft));
      onSetupUpdated(updated);
      setSavedMessage(
        updated.missingRequiredKeys.length === 0
          ? "Saved. Verify connections before Admin can start."
          : "Saved. Finish and verify the missing setup items before Admin can start.",
      );
    } catch (err) {
      setError(errorMessage(err, "Save admin setup failed"));
    } finally {
      setSaving(false);
    }
  }, [draft, onSetupUpdated]);

  const verify = useCallback(async () => {
    setVerifying(true);
    setError(null);
    setSavedMessage(null);
    try {
      await api.updateAdminSetup(adminSetupPayloadFromDraft(draft));
      const verified = await api.verifyAdminSetup();
      if (verified.missingRequiredKeys.length === 0) {
        const completed = await api.completeAdminSetup();
        onSetupUpdated(completed);
        const playbookProvince = completed.playbook?.province;
        const playbookHasGuide = completed.playbook?.hasProvinceGuide;
        if (playbookProvince) {
          setSavedMessage(
            playbookHasGuide
              ? `Admin is verified. ${playbookProvince} playbook seeded as your source of truth.`
              : `Admin is verified. ${playbookProvince} playbook seeded (no provincial form pack imported yet — agent will fall back to manual references).`,
          );
        } else {
          setSavedMessage("Admin setup is verified and ready.");
        }
      } else {
        onSetupUpdated(verified);
        setSavedMessage("Checked live connectors. Finish the missing setup items before Admin can start.");
      }
    } catch (err) {
      setError(errorMessage(err, "Verify admin setup failed"));
    } finally {
      setVerifying(false);
    }
  }, [draft, onSetupUpdated]);

  const handleWizardFinish = useCallback(async () => {
    setError(null);
    setSavedMessage(null);
    try {
      await api.updateAdminSetup(adminSetupPayloadFromDraft(draft));
    } catch (err) {
      setError(errorMessage(err, "Save admin setup failed"));
      return;
    }
    setPhase("seeding");
  }, [draft]);

  const runSeedAndVerify = useCallback(async (): Promise<{ missing: boolean; error: string | null }> => {
    try {
      const verified = await api.verifyAdminSetup();
      if (verified.missingRequiredKeys.length === 0) {
        const completed = await api.completeAdminSetup();
        onSetupUpdated(completed);
        return { missing: false, error: null };
      }
      onSetupUpdated(verified);
      return { missing: true, error: null };
    } catch (err) {
      return { missing: true, error: errorMessage(err, "Verify admin setup failed") };
    }
  }, [onSetupUpdated]);

  const missingLabels = useMemo(() => {
    const labels = new Map(setup.items.map((item) => [item.key, item.label]));
    return setup.missingRequiredKeys.map((key) => labels.get(key) ?? key);
  }, [setup.items, setup.missingRequiredKeys]);
  const readinessBlockers = useMemo(
    () => (setup.readiness ?? []).filter((item) => !item.ready),
    [setup.readiness],
  );
  const verificationWarnings = setup.verificationWarnings ?? [];

  if (phase === "gate") {
    return (
      <AdminOnboardingGate
        onStart={() => setPhase("welcome")}
        onSkip={() => setPhase("form")}
      />
    );
  }

  if (phase === "welcome") {
    return <AdminOnboardingWelcome onContinue={() => setPhase("wizard")} />;
  }

  if (phase === "wizard") {
    return (
      <AdminOnboardingWizard
        draft={draft}
        updateDraft={updateDraft}
        onAdvanceSave={submit}
        onFinish={handleWizardFinish}
        saving={saving}
        verifying={verifying}
        error={error}
        savedMessage={savedMessage}
        provinceCoverage={provinceCoverage}
        savedProvinceCode={savedProvinceCode}
      />
    );
  }

  if (phase === "seeding") {
    return (
      <AdminOnboardingSeeding
        runSeed={runSeedAndVerify}
        onMissing={() => setPhase("connectors")}
        onComplete={() => {
          playOnboardingChime();
          setPhase("form");
        }}
      />
    );
  }

  if (phase === "connectors") {
    return (
      <AdminOnboardingConnectors
        setup={setup}
        onContinue={() => {
          playOnboardingChime();
          setPhase("form");
        }}
        onChatMention={(key) => {
          openCoach();
          setCoachMention(key);
        }}
        onRefreshSetup={async () => {
          try {
            const fresh = await api.getAdminSetup();
            onSetupUpdated(fresh);
          } catch {
            /* swallow — keep showing existing state */
          }
        }}
      />
    );
  }

  return (
    <section className="border-t border-border pt-6">
      <div className="flex flex-wrap items-start justify-between gap-6 pb-5 border-b border-border">
        <div className="min-w-0 max-w-3xl">
          <div className="font-mono-ui text-[10px] uppercase tracking-wider text-muted-foreground">
            Setup required
          </div>
          <h2 className="mt-1.5 text-[22px] font-medium leading-tight tracking-tight text-foreground">
            Connect the admin operating stack
          </h2>
          <p className="mt-2 text-[13px] leading-6 text-muted-foreground">
            Admin automations stay paused until the realtor profile, province package, accounts, providers, approval lane, and regional memory are configured.
          </p>
        </div>
        <div className="flex flex-col items-end gap-3 min-w-[180px]">
          <div className="w-full">
            <div className="font-mono-ui text-[10px] uppercase tracking-wider text-muted-foreground">
              Readiness
            </div>
            <div className="mt-1.5 flex items-baseline gap-2">
              <span className="font-mono-ui text-[28px] leading-none font-medium text-foreground tabular-nums">{setup.completionPct}</span>
              <span className="font-mono-ui text-[13px] text-muted-foreground">%</span>
            </div>
            <div className="mt-3 h-px bg-border">
              <div className="h-full bg-primary" style={{ width: `${setup.completionPct}%` }} />
            </div>
          </div>
          <button
            type="button"
            onClick={() => setPhase("welcome")}
            className="font-mono-ui text-[10px] uppercase tracking-wider text-muted-foreground underline-offset-2 hover:text-foreground hover:underline"
          >
            Re-run onboarding
          </button>
        </div>
      </div>

      {missingLabels.length > 0 && (
        <div className="flex items-baseline gap-3 py-3 border-b border-border text-[13px]">
          <span className="shrink-0 font-mono-ui text-[10px] uppercase tracking-wider text-warning">
            Missing
          </span>
          <span className="text-foreground">{missingLabels.join(", ")}</span>
        </div>
      )}
      {readinessBlockers.length > 0 && (
        <div className="divide-y divide-border border-b border-border">
          {readinessBlockers.slice(0, 9).map((item) => (
            <div key={item.key} className="grid grid-cols-[1fr_auto] gap-x-6 gap-y-1 py-3">
              <span className="text-[13px] font-medium text-foreground">{item.label}</span>
              <span
                className={cn(
                  "font-mono-ui text-[10px] uppercase tracking-wider tabular-nums",
                  item.state === "needs_runtime_verification" ? "text-warning" : "text-muted-foreground",
                )}
              >
                {item.state.replaceAll("_", " ")}
              </span>
              <p className="col-span-2 text-[12.5px] leading-5 text-muted-foreground">{item.action}</p>
            </div>
          ))}
          {readinessBlockers.length > 9 && (
            <div className="py-3 text-[12.5px] text-muted-foreground">
              +{readinessBlockers.length - 9} more setup item{readinessBlockers.length - 9 === 1 ? "" : "s"} pending
            </div>
          )}
        </div>
      )}
      {verificationWarnings.length > 0 && (
        <div className="py-3 border-b border-border text-[12.5px] leading-5 text-muted-foreground">
          {verificationWarnings.join(" ")}
        </div>
      )}

      <div className="pt-6 pb-2">
        <div className="mb-3 text-[12px] font-semibold text-muted-foreground">Realtor profile</div>
        <div className="grid gap-4 lg:grid-cols-3">
          <AdminSetupField label="Realtor legal name" value={draft.realtorLegalName} onChange={(v) => updateDraft("realtorLegalName", v)} />
          <AdminSetupField label="Licensed / public name" value={draft.licenseName} onChange={(v) => updateDraft("licenseName", v)} />
          <AdminSetupField label="Brokerage" value={draft.brokerageName} onChange={(v) => updateDraft("brokerageName", v)} />
          <AdminSetupField label="Team / PREC" value={draft.teamName} onChange={(v) => updateDraft("teamName", v)} />
          <label className="block min-w-0">
            <div className="mb-1.5 flex items-center justify-between gap-2">
              <span className="block text-[12px] font-medium text-muted-foreground">Province / territory</span>
              <div className="flex items-center gap-2">
                {savedProvinceCode && !provinceUnlocked && (
                  <button
                    type="button"
                    onClick={() => setProvinceUnlocked(true)}
                    className="text-[11px] text-muted-foreground underline-offset-2 hover:text-foreground hover:underline"
                  >
                    Change
                  </button>
                )}
                <span className="font-mono-ui text-[0.58rem] uppercase tracking-wider text-muted-foreground/80">CA · Canada</span>
              </div>
            </div>
            {savedProvinceCode && !provinceUnlocked ? (
              <div className="flex h-9 w-full items-center rounded-md border border-border bg-muted/40 px-3 text-[13px] text-foreground">
                <span>{PROVINCE_LABEL_BY_CODE.get(savedProvinceCode) ?? savedProvinceCode}</span>
                <span className="ml-2 font-mono-ui text-[0.58rem] uppercase tracking-wider text-muted-foreground">
                  saved
                </span>
              </div>
            ) : (
              <select
                value={draft.province.trim().toUpperCase()}
                onChange={(event) => updateDraft("province", event.target.value)}
                className="h-9 w-full rounded-md border border-border bg-background px-3 text-[13px] text-foreground outline-none transition-colors focus:border-primary focus:ring-1 focus:ring-primary/30"
              >
                <option value="">Select province</option>
                {CANADIAN_PROVINCES.map(({ code, label }) => {
                  const coverage = provinceCoverageByCode.get(code);
                  const suffix = coverage?.hasTransactionGuide ? " — full guide" : coverage ? " — reference" : "";
                  return (
                    <option key={code} value={code}>
                      {label}
                      {suffix}
                    </option>
                  );
                })}
              </select>
            )}
            {selectedProvinceCoverage && (
              <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
                <span className="font-mono-ui rounded border border-border bg-card px-1.5 py-0.5 text-[0.58rem] uppercase tracking-wider text-muted-foreground">
                  {selectedProvinceCoverage.hasTransactionGuide ? "full guide" : "reference"}
                </span>
                <span className="font-mono-ui rounded border border-border bg-card px-1.5 py-0.5 text-[0.58rem] uppercase tracking-wider text-muted-foreground">
                  {selectedProvinceCoverage.referencePages} pages
                </span>
                {selectedProvinceCoverage.forms > 0 && (
                  <span className="font-mono-ui rounded border border-border bg-card px-1.5 py-0.5 text-[0.58rem] uppercase tracking-wider text-muted-foreground">
                    {selectedProvinceCoverage.forms} forms
                  </span>
                )}
                {selectedProvinceCoverage.checklists > 0 && (
                  <span className="font-mono-ui rounded border border-border bg-card px-1.5 py-0.5 text-[0.58rem] uppercase tracking-wider text-muted-foreground">
                    {selectedProvinceCoverage.checklists} checklists
                  </span>
                )}
              </div>
            )}
            {draft.province.trim() && !selectedProvinceCoverage && (
              <div className="mt-1.5 text-[11px] text-muted-foreground">
                No local guide for this province yet — fall back to manual references.
              </div>
            )}
          </label>
          <AdminSetupField label="Market" value={draft.market} onChange={(v) => updateDraft("market", v)} placeholder="Kamloops, Calgary..." />
          <AdminSetupField label="Board memberships" value={draft.boardMemberships} onChange={(v) => updateDraft("boardMemberships", v)} placeholder="AOIR, FVREB..." />
          <AdminSetupField label="Managing broker/admin email" value={draft.managingBrokerEmail} onChange={(v) => updateDraft("managingBrokerEmail", v)} />
          <AdminSetupField label="Admin approval channel" value={draft.approvalChannel} onChange={(v) => updateDraft("approvalChannel", v)} placeholder="Telegram Admin bot/lane" />
        </div>
      </div>

      <div className="pt-6 pb-2 border-t border-border">
        <div className="mb-3 text-[12px] font-semibold text-muted-foreground">Providers</div>
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          <AdminSetupField label="Email" value={draft.emailProvider} onChange={(v) => updateDraft("emailProvider", v)} placeholder="Gmail / Outlook account" suggestions={PROVIDER_SUGGESTIONS.email} listId="provider-email" />
          <AdminSetupField label="Calendar" value={draft.calendarProvider} onChange={(v) => updateDraft("calendarProvider", v)} placeholder="Google Calendar / Outlook" suggestions={PROVIDER_SUGGESTIONS.calendar} listId="provider-calendar" />
          <AdminSetupField label="Cloud drive" value={draft.driveProvider} onChange={(v) => updateDraft("driveProvider", v)} placeholder="Google Drive / SharePoint" suggestions={PROVIDER_SUGGESTIONS.drive} listId="provider-drive" />
          <AdminSetupField label="CRM" value={draft.crmProvider} onChange={(v) => updateDraft("crmProvider", v)} placeholder="Lofty, kvCORE, BoldTrail..." suggestions={PROVIDER_SUGGESTIONS.crm} listId="provider-crm" />
          <AdminSetupField label="MLS / board portal" value={draft.mlsProvider} onChange={(v) => updateDraft("mlsProvider", v)} placeholder="Matrix, Xposure, Paragon..." suggestions={PROVIDER_SUGGESTIONS.mls} listId="provider-mls" />
          <AdminSetupField label="Forms provider" value={draft.formsProvider} onChange={(v) => updateDraft("formsProvider", v)} placeholder="WEBForms / TransactionDesk" suggestions={PROVIDER_SUGGESTIONS.forms} listId="provider-forms" />
          <AdminSetupField label="Signing provider" value={draft.signingProvider} onChange={(v) => updateDraft("signingProvider", v)} placeholder="DigiSign / DocuSign" suggestions={PROVIDER_SUGGESTIONS.signing} listId="provider-signing" />
          <AdminSetupField label="Compliance platform" value={draft.complianceProvider} onChange={(v) => updateDraft("complianceProvider", v)} placeholder="SkySlope / Lone Wolf" suggestions={PROVIDER_SUGGESTIONS.compliance} listId="provider-compliance" />
          <AdminSetupField label="Showing platform" value={draft.showingProvider} onChange={(v) => updateDraft("showingProvider", v)} placeholder="ShowingTime / BrokerBay" suggestions={PROVIDER_SUGGESTIONS.showing} listId="provider-showing" />
          <AdminSetupField label="Photo processing" value={draft.photoProcessingProvider} onChange={(v) => updateDraft("photoProcessingProvider", v)} placeholder="Drive + Nano Banana / Higgsfield" suggestions={PROVIDER_SUGGESTIONS.photo} listId="provider-photo" />
          <AdminSetupField label="FINTRAC / ID workflow" value={draft.fintracProvider} onChange={(v) => updateDraft("fintracProvider", v)} placeholder="Fintracker / manual FIN# capture" suggestions={PROVIDER_SUGGESTIONS.fintrac} listId="provider-fintrac" />
          <AdminSetupField label="Folder pattern" value={draft.defaultFolderPattern} onChange={(v) => updateDraft("defaultFolderPattern", v)} />
          <AdminSetupField label="Commission / service notes" value={draft.commissionNotes} onChange={(v) => updateDraft("commissionNotes", v)} />
        </div>
      </div>

      <div className="pt-6 pb-2 border-t border-border">
        <div className="mb-1 text-[12px] font-semibold text-muted-foreground">Portal logins</div>
        <div className="mb-3 text-[11.5px] text-muted-foreground/80">Same login you'd type yourself — email + password. Stored locally only.</div>
        <div className="space-y-5">
          <div>
            <div className="mb-2 font-mono-ui text-[10px] uppercase tracking-[0.18em] text-muted-foreground">
              {draft.mlsProvider?.trim() || "MLS"}
            </div>
            <div className="grid gap-4 md:grid-cols-3">
              <AdminSetupField label="Login URL" value={draft.mlsLoginUrl} onChange={(v) => updateDraft("mlsLoginUrl", v)} placeholder="https://xposure.ca/login" type="url" />
              <AdminSetupField label="Email / username" value={draft.mlsLoginEmail} onChange={(v) => updateDraft("mlsLoginEmail", v)} placeholder="you@brokerage.com" type="email" />
              <AdminSetupField label="Password" value={draft.mlsLoginPassword} onChange={(v) => updateDraft("mlsLoginPassword", v)} placeholder="•••••••••" type="password" />
            </div>
          </div>
          <div>
            <div className="mb-2 font-mono-ui text-[10px] uppercase tracking-[0.18em] text-muted-foreground">
              {draft.complianceProvider?.trim() || "Compliance"}
            </div>
            <div className="grid gap-4 md:grid-cols-3">
              <AdminSetupField label="Login URL" value={draft.complianceLoginUrl} onChange={(v) => updateDraft("complianceLoginUrl", v)} placeholder="https://skyslope.com" type="url" />
              <AdminSetupField label="Email / username" value={draft.complianceLoginEmail} onChange={(v) => updateDraft("complianceLoginEmail", v)} placeholder="you@brokerage.com" type="email" />
              <AdminSetupField label="Password" value={draft.complianceLoginPassword} onChange={(v) => updateDraft("complianceLoginPassword", v)} placeholder="•••••••••" type="password" />
            </div>
          </div>
          <div>
            <div className="mb-2 font-mono-ui text-[10px] uppercase tracking-[0.18em] text-muted-foreground">
              {draft.showingProvider?.trim() || "Showing"}
            </div>
            <div className="grid gap-4 md:grid-cols-3">
              <AdminSetupField label="Login URL" value={draft.showingLoginUrl} onChange={(v) => updateDraft("showingLoginUrl", v)} placeholder="https://showingtime.com" type="url" />
              <AdminSetupField label="Email / username" value={draft.showingLoginEmail} onChange={(v) => updateDraft("showingLoginEmail", v)} placeholder="you@brokerage.com" type="email" />
              <AdminSetupField label="Password" value={draft.showingLoginPassword} onChange={(v) => updateDraft("showingLoginPassword", v)} placeholder="•••••••••" type="password" />
            </div>
          </div>
        </div>
      </div>

      <div className="pt-6 pb-2 border-t border-border">
        <div className="mb-3 text-[12px] font-semibold text-muted-foreground">Workflow notes</div>
        <div className="grid gap-4 lg:grid-cols-2">
          <label className="block min-w-0">
            <span className="mb-1.5 block text-[12px] font-medium text-muted-foreground">Browser-use notes</span>
            <textarea
              value={draft.browserWorkflowNotes}
              onChange={(event) => updateDraft("browserWorkflowNotes", event.target.value)}
              placeholder="Board portal quirks, browser profile, MFA expectations, where to find MLS number, showing feedback, compliance status, and confirmation screens."
              className="min-h-28 w-full rounded-md border border-border bg-background px-3 py-2 text-[13px] leading-5 text-foreground outline-none transition-colors placeholder:text-muted-foreground/60 focus:border-primary focus:ring-1 focus:ring-primary/30"
            />
          </label>
          <label className="block min-w-0">
            <span className="mb-1.5 block text-[12px] font-medium text-muted-foreground">Regional memory</span>
            <textarea
              value={draft.regionalMemory}
              onChange={(event) => updateDraft("regionalMemory", event.target.value)}
              placeholder="Province docs, local MLS quirks, deposit rules, admin emails, property lookup sources, showing platform notes."
              className="min-h-28 w-full rounded-md border border-border bg-background px-3 py-2 text-[13px] leading-5 text-foreground outline-none transition-colors placeholder:text-muted-foreground/60 focus:border-primary focus:ring-1 focus:ring-primary/30"
            />
          </label>
          <label className="block min-w-0 lg:col-span-2">
            <span className="mb-1.5 block text-[12px] font-medium text-muted-foreground">Approval policy</span>
            <textarea
              value={draft.approvalPolicy}
              onChange={(event) => updateDraft("approvalPolicy", event.target.value)}
              placeholder="What AI can draft/upload, what needs approval, whether docs/MLS/signing can ever send without a human."
              className="min-h-28 w-full rounded-md border border-border bg-background px-3 py-2 text-[13px] leading-5 text-foreground outline-none transition-colors placeholder:text-muted-foreground/60 focus:border-primary focus:ring-1 focus:ring-primary/30"
            />
          </label>
        </div>
      </div>

      {(error || savedMessage) && (
        <div className={cn(
          "mt-6 flex items-baseline gap-3 py-3 border-t text-[13px]",
          error ? "border-destructive" : "border-success",
        )}>
          <span className={cn(
            "shrink-0 font-mono-ui text-[10px] uppercase tracking-wider",
            error ? "text-destructive" : "text-success",
          )}>
            {error ? "Error" : "Saved"}
          </span>
          <span className="text-foreground">{error || savedMessage}</span>
        </div>
      )}

      <div className="mt-6 flex flex-wrap items-center justify-between gap-4 border-t border-border pt-5">
        <p className="max-w-2xl text-[12.5px] leading-5 text-muted-foreground">
          Admin deal creation, profile handoffs, stage moves, task launches, and default automation seeding are blocked until this reaches 100%.
        </p>
        <div className="flex flex-wrap items-center gap-2">
          <Button variant="outline" onClick={() => void verify()} disabled={saving || verifying}>
            {verifying ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
            Verify connections
          </Button>
          <Button onClick={() => void submit()} disabled={saving || verifying}>
            {saving ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <ShieldCheck className="h-3.5 w-3.5" />}
            Save setup
          </Button>
        </div>
      </div>
    </section>
  );
}

function useAdminDeals(): {
  deals: AdminCard[];
  loading: boolean;
  error: string | null;
  usingDevFallback: boolean;
  refresh: () => Promise<void>;
  moveDeal: (dealId: string, toStage: AdminStageNumber) => Promise<void>;
  setDealToggle: (dealId: string, field: string, value: AdminConditionValue) => Promise<void>;
  addLocalDeal: (card: AdminCard) => void;
  replaceLocalDeal: (placeholderId: string, deal: AdminDeal) => void;
} {
  const [deals, setDeals] = useState<AdminCard[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [usingDevFallback, setUsingDevFallback] = useState(false);

  const loadDeals = useCallback(async () => {
    const response = await api.getAdminDeals({ limit: 200 });
    return response.items.map(adminCardFromDeal);
  }, []);

  const refresh = useCallback(async () => {
    setError(null);
    setLoading(true);
    try {
      const nextDeals = await loadDeals();
      if (nextDeals.length === 0) {
        setDeals([]);
        setUsingDevFallback(false);
      } else {
        setDeals(nextDeals);
        setUsingDevFallback(false);
      }
    } catch (err) {
      setError(errorMessage(err, "Admin deals failed"));
      setDeals([]);
      setUsingDevFallback(false);
    } finally {
      setLoading(false);
    }
  }, [loadDeals]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    loadDeals()
      .then((nextDeals) => {
        if (cancelled) return;
        if (nextDeals.length === 0) {
          setDeals([]);
          setUsingDevFallback(false);
        } else {
          setDeals(nextDeals);
          setUsingDevFallback(false);
        }
      })
      .catch((err) => {
        if (cancelled) return;
        setError(errorMessage(err, "Admin deals failed"));
        setDeals([]);
        setUsingDevFallback(false);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [loadDeals]);

  const moveDeal = useCallback(
    async (dealId: string, toStage: AdminStageNumber) => {
      setDeals((prev) =>
        prev.map((card) => (card.id === dealId ? { ...card, stage: toStage, nextLabel: adminStageLabel(card.side, toStage).title } : card)),
      );
      try {
        const updated = await api.moveAdminDeal(dealId, toStage);
        setDeals((prev) => replaceCardFromDeal(prev, updated));
      } catch (err) {
        if (isApiNotFound(err)) {
          console.warn("POST /api/admin/deals/:id/move returned 404; keeping optimistic local stage update.");
          return;
        }
        setError(errorMessage(err, "Move deal failed"));
        await refresh();
      }
    },
    [refresh],
  );

  const setDealToggle = useCallback(
    async (dealId: string, field: string, value: AdminConditionValue) => {
      setDeals((prev) =>
        prev.map((card) => (card.id === dealId ? applyLocalDealField(card, field, value) : card)),
      );
      try {
        const updated = await api.setAdminDealToggle(dealId, field, value);
        setDeals((prev) => replaceCardFromDeal(prev, updated));
      } catch (err) {
        if (isApiNotFound(err)) {
          console.warn("POST /api/admin/deals/:id/toggle returned 404; keeping optimistic local toggle update.");
          return;
        }
        setError(errorMessage(err, "Set deal toggle failed"));
        await refresh();
      }
    },
    [refresh],
  );

  const addLocalDeal = useCallback((card: AdminCard) => {
    setDeals((prev) => [card, ...prev]);
  }, []);

  const replaceLocalDeal = useCallback((placeholderId: string, deal: AdminDeal) => {
    const fresh = adminCardFromDeal(deal);
    setDeals((prev) => prev.map((card) => (card.id === placeholderId ? fresh : card)));
  }, []);

  return { deals, loading, error, usingDevFallback, refresh, moveDeal, setDealToggle, addLocalDeal, replaceLocalDeal };
}

function dueLabel(days?: number): { text: string; tone: "muted" | "warn" | "danger" | "ok" } {
  if (days == null) return { text: "—", tone: "muted" };
  if (days < 0) return { text: `${-days}d overdue`, tone: "danger" };
  if (days === 0) return { text: "today", tone: "warn" };
  if (days === 1) return { text: "tomorrow", tone: "warn" };
  if (days <= 3) return { text: `in ${days}d`, tone: "warn" };
  return { text: `in ${days}d`, tone: "ok" };
}

const AdminKanbanCard = memo(function AdminKanbanCard({
  card,
  onSelect,
  onDragStart,
}: {
  card: AdminCard;
  onSelect?: (id: string) => void;
  onDragStart?: (id: string) => void;
}) {
  const due = dueLabel(card.daysOut);
  const { done, total, nextItem } = getCardProgress(card);
  const pct = total > 0 ? Math.round((done / total) * 100) : 0;
  return (
    <button
      type="button"
      draggable
      onClick={() => onSelect?.(card.id)}
      onDragStart={(event) => {
        event.dataTransfer.setData("text/plain", card.id);
        event.dataTransfer.effectAllowed = "move";
        onDragStart?.(card.id);
      }}
      className="group relative w-full text-left border border-border bg-card px-3 py-2.5 hover:border-foreground/40 focus:outline-none focus-visible:border-primary transition-colors cursor-grab active:cursor-grabbing rounded-sm"
    >
      <div className="flex items-baseline justify-between gap-2">
        <span className="truncate text-[13.5px] font-medium leading-tight text-foreground">
          {card.client}
        </span>
        {card.pinnedTop25 && (
          <span title="Top 25" className="shrink-0 font-mono-ui text-[10px] uppercase tracking-wider text-warning">
            Top
          </span>
        )}
      </div>
      {card.property && (
        <div className="mt-1 truncate text-[12px] text-muted-foreground">
          {card.property}
        </div>
      )}
      {card.nextLabel && (
        <div className="mt-2 flex items-baseline gap-2 text-[12px]">
          <span className="truncate text-foreground">{card.nextLabel}</span>
          <span
            className={cn(
              "ml-auto shrink-0 font-mono-ui text-[11px] tabular-nums",
              due.tone === "danger" && "text-destructive",
              due.tone === "warn" && "text-warning",
              due.tone === "ok" && "text-muted-foreground",
              due.tone === "muted" && "text-muted-foreground",
            )}
          >
            {due.text}
          </span>
        </div>
      )}
      <div className="mt-2.5 flex items-center gap-2">
        <div
          role="progressbar"
          aria-valuenow={pct}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-label="Stage checklist progress"
          className="h-px flex-1 bg-border"
        >
          <div className="h-full bg-primary" style={{ width: `${pct}%` }} />
        </div>
        <span className="shrink-0 font-mono-ui text-[10px] tabular-nums text-muted-foreground">
          {done}/{total}
        </span>
      </div>
      {nextItem && (
        <div className="mt-1.5 truncate text-[11.5px] text-muted-foreground">
          <span className="font-mono-ui text-[9.5px] uppercase tracking-wider text-muted-foreground/70 mr-1.5">Next</span>
          {nextItem}
        </div>
      )}
    </button>
  );
});

function AdminPhaseSummary({
  phase,
  dense = false,
}: {
  phase: AdminPhaseAutomationInfo;
  dense?: boolean;
}) {
  const agentNames = phase.agents.join(", ");
  const backgroundNames = phase.background.join(", ");
  const summaryTitle = [
    phase.agents.length ? `Stage skills: ${agentNames}` : "No stage-entry skill wired",
    phase.background.length ? `Background: ${backgroundNames}` : null,
    phase.approvalGate ? `Approval gate: ${phase.approvalGate}` : null,
  ]
    .filter(Boolean)
    .join("\n");

  const automationLabel =
    phase.agents.length > 0
      ? phase.background.length > 0
        ? "automated + background"
        : "automated"
      : "manual";

  return (
    <div className={cn("flex flex-col gap-0.5", dense ? "mt-1" : "mt-1.5")} title={summaryTitle}>
      <div className="flex min-w-0 items-center gap-1.5 text-[0.7rem] leading-tight">
        <span className="truncate text-muted-foreground/85">{automationLabel}</span>
        {phase.approvalGate && (
          <>
            <span className="shrink-0 text-muted-foreground/45">·</span>
            <span className="shrink-0 text-warning">approval</span>
          </>
        )}
      </div>
      <div className="truncate text-[0.66rem] leading-tight text-muted-foreground/85">
        Moves on {phase.moveSignal}
      </div>
    </div>
  );
}

function AdminKanbanColumn(props: {
  side: AdminSide;
  stage: AdminStageNumber;
  cards: AdminCard[];
  onCardSelect: (id: string) => void;
  onCardDragStart: (id: string) => void;
  onCardDrop: (stage: AdminStageNumber) => void;
}) {
  const { side, stage, cards, onCardSelect, onCardDragStart, onCardDrop } = props;
  const column = adminStageDefinition(stage);
  const label = column.labels[side];
  const phase = adminPhaseAutomation(side, stage);
  const [isDragOver, setIsDragOver] = useState(false);
  return (
    <div
      onDragOver={(event) => {
        event.preventDefault();
        event.dataTransfer.dropEffect = "move";
        if (!isDragOver) setIsDragOver(true);
      }}
      onDragLeave={() => setIsDragOver(false)}
      onDrop={(event) => {
        event.preventDefault();
        setIsDragOver(false);
        onCardDrop(stage);
      }}
      className={cn(
        "flex h-full min-w-[18.5rem] flex-col border-r border-border bg-background transition-colors",
        isDragOver && "bg-muted",
      )}
    >
      <div className="sticky top-0 z-10 border-b border-border bg-background px-3 py-3" title={label.subtitle}>
        <div className="flex items-baseline justify-between gap-2">
          <div className="flex min-w-0 items-baseline gap-2">
            <span className="font-mono-ui text-[10px] tabular-nums uppercase tracking-wider text-muted-foreground">
              {column.stageNumber.toString().padStart(2, "0")}
            </span>
            <span className="truncate text-[13px] font-medium text-foreground">{label.title}</span>
          </div>
          <span className="font-mono-ui text-[11px] tabular-nums text-muted-foreground">
            {cards.length}
          </span>
        </div>
        <AdminPhaseSummary phase={phase} />
      </div>
      <div className="flex flex-col gap-1.5 p-2">
        {cards.length === 0 ? (
          <p className="px-3 py-3 text-xs text-muted-foreground/70">
            {label.subtitle}
          </p>
        ) : (
          cards.map((card) => (
            <AdminKanbanCard
              key={card.id}
              card={card}
              onSelect={onCardSelect}
              onDragStart={onCardDragStart}
            />
          ))
        )}
      </div>
    </div>
  );
}

function AdminKanbanSwimlane({
  side,
  title,
  description,
  cardsByStage,
  totalCount,
  onCardSelect,
  onCardDragStart,
  onCardDrop,
}: {
  side: AdminSide;
  title: string;
  description: string;
  cardsByStage: Record<AdminStageNumber, AdminCard[]>;
  totalCount: number;
  onCardSelect: (id: string) => void;
  onCardDragStart: (id: string) => void;
  onCardDrop: (side: AdminSide, stage: AdminStageNumber) => void;
}) {
  const visibleStages = visibleAdminStages(side);
  const visiblePipeline = visibleStages.slice(0, side === "listing" ? 6 : 4).map((stage) => {
    const column = adminStageDefinition(stage);
    return {
      stage,
      title: column.labels[side].title,
      subtitle: column.labels[side].subtitle,
    };
  });

  return (
    <section aria-label={title} className="flex flex-col gap-2">
      <div className="flex items-baseline justify-between gap-3 px-1">
        <span className="font-mono-ui text-[0.62rem] uppercase tracking-wider text-muted-foreground">
          {totalCount} active
        </span>
        <span className="hidden text-[0.72rem] text-muted-foreground sm:inline">{description}</span>
      </div>
      {side === "listing" && (
        <div className="rounded-md border border-border bg-muted/25 px-3 py-2">
          <div className="mb-1 font-mono-ui text-[0.6rem] uppercase tracking-wider text-muted-foreground">
            Listing pipeline order
          </div>
          <div className="flex flex-wrap items-center gap-1.5 text-xs">
            {visiblePipeline.map((item, index) => (
              <React.Fragment key={`pipeline-${item.stage}`}>
                <span
                  className={cn(
                    "rounded-full border px-2.5 py-1 font-medium",
                    item.stage === 0
                      ? "border-primary/40 bg-primary/10 text-primary"
                      : "border-border bg-background text-foreground",
                  )}
                  title={item.subtitle}
                >
                  {item.title}
                </span>
                {index < visiblePipeline.length - 1 && (
                  <span className="text-muted-foreground">→</span>
                )}
              </React.Fragment>
            ))}
          </div>
        </div>
      )}
      <div
        className="grid gap-2 overflow-x-auto pb-1"
        style={{ gridTemplateColumns: `repeat(${visibleStages.length}, 18.5rem)` }}
      >
        {visibleStages.map((stage) => (
          <AdminKanbanColumn
            key={`${side}-${stage}`}
            side={side}
            stage={stage}
            cards={cardsByStage[stage] ?? []}
            onCardSelect={onCardSelect}
            onCardDragStart={onCardDragStart}
            onCardDrop={(targetStage) => onCardDrop(side, targetStage)}
          />
        ))}
      </div>
    </section>
  );
}

function AdminTop25Strip({
  cards,
  devFallback,
  onCardSelect,
  onCardDragStart,
}: {
  cards: AdminCard[];
  devFallback: boolean;
  onCardSelect: (id: string) => void;
  onCardDragStart: (id: string) => void;
}) {
  const pinned = cards.filter((c) => c.pinnedTop25);
  return (
    <section className="rounded-md border border-border bg-card p-3">
      <div className="flex items-baseline justify-between gap-2">
        <div className="flex items-center gap-2">
          <Flame className="h-4 w-4 text-warning" />
          <h2 className="text-[0.95rem] font-semibold text-foreground">TOP 25</h2>
          <span className="font-mono-ui text-[0.62rem] uppercase tracking-wider text-muted-foreground">
            {pinned.length} pinned · {Math.max(0, 25 - pinned.length)} slots open
          </span>
          {devFallback && (
            <span className="rounded-sm border border-border bg-transparent px-1.5 py-0.5 font-mono-ui text-[0.58rem] uppercase tracking-wider text-warning">
              dev-fallback
            </span>
          )}
        </div>
        <span className="text-[0.72rem] text-muted-foreground hidden sm:inline">
          Pinned clients still live in their stage column.
        </span>
      </div>
      {pinned.length === 0 ? (
        <p className="mt-2 px-1 py-1 text-xs text-muted-foreground/80">
          No clients pinned — pin from any card to add to TOP 25.
        </p>
      ) : (
        <div className="mt-2 flex gap-2 overflow-x-auto pb-1">
          {pinned.map((card) => (
            <div key={card.id} className="min-w-[16rem] max-w-[16rem]">
              <AdminKanbanCard card={card} onSelect={onCardSelect} onDragStart={onCardDragStart} />
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

function AdminCardStageSection({
  card,
  stage,
  isCurrent,
  isPast,
  expanded,
  onToggleExpand,
  onToggleItem,
  documents,
}: {
  card: AdminCard;
  stage: AdminStageNumber;
  isCurrent: boolean;
  isPast: boolean;
  expanded: boolean;
  onToggleExpand: () => void;
  onToggleItem: (itemId: string, completed: boolean) => void;
  documents?: ProvinceStageDocumentItem[];
}) {
  const column = adminStageDefinition(stage);
  const label = column.labels[card.side];
  const phase = adminPhaseAutomation(card.side, stage);
  const items = adminStageChecklist(card.side, stage);
  const completed = card.completedByStage?.[stage] ?? {};
  const done = items.reduce((n, item) => n + (completed[item.id] ? 1 : 0), 0);
  const total = items.length;
  const allDone = total > 0 && done === total;

  return (
    <div
      className={cn(
        "rounded-md border bg-card",
        isCurrent ? "border-primary" : "border-border",
      )}
    >
      <button
        type="button"
        onClick={onToggleExpand}
        className="flex w-full items-center gap-3 px-3 py-2.5 text-left focus:outline-none focus-visible:ring-1 focus-visible:ring-ring rounded-md"
      >
        <div className="flex h-6 w-6 shrink-0 items-center justify-center">
          {isPast && allDone ? (
            <CheckCircle2 className="h-5 w-5 text-primary/80" />
          ) : isCurrent ? (
            <span className="inline-flex h-2.5 w-2.5 rounded-full bg-primary" />
          ) : (
            <span className="inline-flex h-2.5 w-2.5 rounded-full border border-border" />
          )}
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span
              className={cn(
                "text-[0.86rem] font-semibold leading-tight",
                isCurrent ? "text-foreground" : isPast ? "text-foreground/85" : "text-muted-foreground",
              )}
            >
              {label.title}
            </span>
            {isCurrent && (
              <span className="font-mono-ui text-[0.58rem] uppercase tracking-wider text-primary">
                current
              </span>
            )}
          </div>
          <div className="font-mono-ui text-[0.6rem] uppercase tracking-wider text-muted-foreground">
            {column.stageNumber} · {column.stageLabel ?? label.subtitle}
          </div>
          <div className="mt-1 flex min-w-0 items-center gap-1.5 text-[0.66rem] leading-tight text-muted-foreground">
            <Target className="h-3 w-3 shrink-0 text-muted-foreground/80" />
            <span className="truncate">{phase.moveSignal}</span>
          </div>
        </div>
        <span
          className={cn(
            "font-mono-ui text-[0.66rem] tabular-nums",
            allDone ? "text-primary" : "text-muted-foreground",
          )}
        >
          {done}/{total}
        </span>
        <ChevronDown
          className={cn(
            "h-4 w-4 text-muted-foreground transition-transform",
            expanded && "rotate-180",
          )}
        />
      </button>
      {expanded && (
        <div className="border-t border-border px-3 py-2.5">
          <div className="mb-2 rounded-sm border border-border bg-card px-2 py-2">
            <AdminPhaseSummary phase={phase} dense />
            {phase.approvalGate && (
              <div className="mt-1.5 flex min-w-0 items-center gap-1.5 text-[0.68rem] text-muted-foreground">
                <ShieldCheck className="h-3 w-3 shrink-0 text-warning" />
                <span className="truncate">Gate: {phase.approvalGate}</span>
              </div>
            )}
          </div>
          {items.length === 0 ? (
            <div className="text-[0.72rem] text-muted-foreground">No checklist items defined for this stage.</div>
          ) : (
            <ul className="flex flex-col gap-1.5">
              {items.map((item) => {
                const isDone = !!completed[item.id];
                return (
                  <li key={item.id}>
                    <button
                      type="button"
                      onClick={() => onToggleItem(item.id, !isDone)}
                      className="flex w-full items-start gap-2 rounded-md px-2 py-1.5 text-left hover:bg-muted focus:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                    >
                      {isDone ? (
                        <CheckSquare className="mt-[1px] h-4 w-4 shrink-0 text-primary" />
                      ) : (
                        <SquareIcon className="mt-[1px] h-4 w-4 shrink-0 text-muted-foreground" />
                      )}
                      <span
                        className={cn(
                          "text-[0.82rem] leading-snug",
                          isDone ? "text-muted-foreground line-through decoration-muted-foreground/50" : "text-foreground",
                        )}
                      >
                        {item.label}
                      </span>
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
          {documents && documents.length > 0 && (
            <div className="mt-3 border-t border-border pt-2.5">
              <div className="font-mono-ui mb-1.5 text-[0.6rem] uppercase tracking-wider text-muted-foreground">
                Province documents · {documents.length}
              </div>
              <ul className="flex flex-col gap-1">
                {documents.map((doc) => (
                  <li
                    key={`${doc.source}-${doc.code}`}
                    className="flex items-start gap-2 text-[0.78rem] leading-snug"
                  >
                    <FileText className="mt-[1px] h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                    <div className="min-w-0">
                      <span className="font-medium text-foreground">{doc.code}</span>
                      <span className="text-muted-foreground"> · {doc.name}</span>
                      {doc.condition && (
                        <span className="font-mono-ui ml-1 text-[0.62rem] uppercase tracking-wider text-warning">
                          if {doc.condition.field}={doc.condition.value}
                        </span>
                      )}
                    </div>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function AdminCardConditionsSection({
  card,
  onConditionChange,
}: {
  card: AdminCard;
  onConditionChange: (field: AdminConditionField, value: AdminConditionValue) => void;
}) {
  const conditions = card.conditions ?? {};
  return (
    <section className="mt-4">
      <h3 className="text-[0.86rem] font-semibold text-foreground">Conditions</h3>
      <div className="mt-2 space-y-4">
        <div>
          <div className="font-mono-ui mb-1.5 text-[0.6rem] uppercase tracking-wider text-muted-foreground">
            Enums
          </div>
          <div className="divide-y divide-border">
            {ADMIN_ENUM_CONDITIONS.map((condition) => {
              const current = conditions[condition.field];
              const value = typeof current === "string" ? current : "";
              const hasCustomValue = value !== "" && !condition.options.some((option) => option.value === value);
              return (
                <label
                  key={condition.field}
                  className="flex items-center justify-between gap-3 py-2"
                >
                  <span className="min-w-0 flex-1 text-[0.78rem] font-medium text-foreground">
                    {condition.label}
                  </span>
                  <select
                    value={value}
                    onChange={(event) => onConditionChange(condition.field, event.currentTarget.value || null)}
                    className="h-10 max-w-[12rem] rounded-md border border-border bg-background px-2 text-[0.78rem] text-foreground focus:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                  >
                    <option value="">Not set</option>
                    {hasCustomValue && <option value={value}>{value}</option>}
                    {condition.options.map((option) => (
                      <option key={option.value} value={option.value}>
                        {option.label}
                      </option>
                    ))}
                  </select>
                </label>
              );
            })}
          </div>
        </div>

        <div>
          <div className="font-mono-ui mb-1.5 text-[0.6rem] uppercase tracking-wider text-muted-foreground">
            Yes / No
          </div>
          <div className="grid gap-1.5 sm:grid-cols-2">
            {ADMIN_TOGGLE_CONDITIONS.map((condition) => {
              const current = conditions[condition.field];
              const checked = current === true;
              const label = current == null ? "Unset" : checked ? "Yes" : "No";
              return (
                <button
                  key={condition.field}
                  type="button"
                  aria-pressed={checked}
                  onClick={() => onConditionChange(condition.field, !checked)}
                  className="flex min-h-11 items-center gap-2 rounded-sm px-2.5 py-2 text-left hover:bg-muted focus:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                >
                  {checked ? (
                    <CheckSquare className="h-4 w-4 shrink-0 text-primary" />
                  ) : (
                    <SquareIcon className="h-4 w-4 shrink-0 text-muted-foreground" />
                  )}
                  <span className="min-w-0 flex-1 text-[0.78rem] leading-tight text-foreground">
                    {condition.label}
                  </span>
                  <span className="font-mono-ui text-[0.6rem] uppercase tracking-wider text-muted-foreground">
                    {label}
                  </span>
                </button>
              );
            })}
          </div>
        </div>
      </div>
    </section>
  );
}

function AdminCardSourceSection({ context }: { context: AdminSourceContext }) {
  const heat = context.heatLabel
    ? `${context.heatLabel}${context.heatScore != null ? ` ${context.heatScore}` : ""}`
    : null;
  return (
    <section className="mb-3 rounded-md border border-border bg-card px-3 py-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-[0.86rem] font-semibold text-foreground">
          {context.profileName || "Source profile"}
        </span>
        {heat && <Badge variant={context.heatLabel ? heatVariant({ heatLabel: context.heatLabel }) : "outline"}>{heat}</Badge>}
        {context.contactIds.length > 0 && !context.rejectedContactId && <Badge variant="success">DB contact</Badge>}
        <Badge variant={context.verifiers.length > 0 ? "success" : "warning"}>
          {verifierSummary(context.verifiers)}
        </Badge>
        {context.rejectedContactId && <Badge variant="warning">source contact only</Badge>}
      </div>
      {context.latestText && (
        <p className="mt-2 line-clamp-3 text-[0.8rem] leading-5 text-muted-foreground">
          {context.latestText}
        </p>
      )}
      <div className="mt-2 flex flex-wrap items-center gap-1.5">
        {context.sources.map((source) => (
          <Badge key={`source-${source}`} variant="outline">{source}</Badge>
        ))}
        {context.channels.map((channel) => (
          <Badge key={`channel-${channel}`} variant="outline">{channel}</Badge>
        ))}
        {context.conversationIds.length > 0 && (
          <Badge variant="outline">
            {context.conversationIds.length} conversation{context.conversationIds.length === 1 ? "" : "s"}
          </Badge>
        )}
        {context.latestAt && <Badge variant="outline">{isoTimeAgo(context.latestAt)}</Badge>}
      </div>
    </section>
  );
}

function isPersistedAdminDealId(id: string): boolean {
  return /^[a-f0-9]{32}$/i.test(id);
}

function adminContextDate(value?: string | null): string {
  if (!value) return "Not set";
  if (/^\d{4}-\d{2}-\d{2}$/.test(value)) return value;
  return isoTimeAgo(value);
}

function adminContextMoney(value?: number | null): string {
  if (value == null || !Number.isFinite(value)) return "Not set";
  return new Intl.NumberFormat("en-CA", {
    style: "currency",
    currency: "CAD",
    maximumFractionDigits: 0,
  }).format(value);
}

function AdminDealContextSection({
  context,
  loading,
  error,
  busy,
  onAdvance,
  onUpdateFields,
  onAddAttachment,
  onAddContact,
  onApproveRun,
  onCancelRun,
}: {
  context: DealContext | null;
  loading: boolean;
  error: string | null;
  busy: boolean;
  onAdvance: (force?: boolean) => Promise<void>;
  onUpdateFields: (fields: Record<string, unknown>) => Promise<void>;
  onAddAttachment: (body: DealAttachmentCreateRequest) => Promise<void>;
  onAddContact: (body: DealContactCreateRequest) => Promise<void>;
  onApproveRun: (runId: string) => Promise<void>;
  onCancelRun: (runId: string) => Promise<void>;
}) {
  const [actionMode, setActionMode] = useState<"dates" | "doc" | "contact" | null>(null);
  const [approvalBusyRun, setApprovalBusyRun] = useState<AdminRunBusy>(null);
  const [fieldDraft, setFieldDraft] = useState({
    listingDate: "",
    subjectRemovalDate: "",
    depositDueDate: "",
    completionDate: "",
    possessionDate: "",
    mlsNumber: "",
    listPrice: "",
  });
  const [docDraft, setDocDraft] = useState({ kind: "cma_report", filePath: "", summary: "" });
  const [contactDraft, setContactDraft] = useState({ role: "lawyer", contactId: "", notes: "" });
  const deal = context?.deal ?? null;
  const primary = context?.primaryContact ?? null;
  const coContacts = context?.coContacts ?? [];
  const attachments = context?.attachments ?? [];
  const priorRuns = context?.priorRuns ?? [];
  const flow = context?.dealFlow ?? null;
  const gate = flow?.gate ?? null;
  const pendingHumanRuns = priorRuns.filter((run) => run.status === "waiting_human");
  const resolvePendingRun = async (run: AdminActionRun, approved: boolean) => {
    if (busy || approvalBusyRun) return;
    setApprovalBusyRun({ id: run.id, action: approved ? "approve" : "cancel" });
    try {
      if (approved) {
        await onApproveRun(run.id);
      } else {
        await onCancelRun(run.id);
      }
    } finally {
      setApprovalBusyRun(null);
    }
  };
  const dateRows: Array<[string, string]> = deal
    ? ([
        ["Listing", deal.listingDate],
        ["Offer", deal.offerDate],
        ["Conditions", deal.subjectRemovalDate],
        ["Deposit", deal.depositDueDate],
        ["Completion", deal.completionDate],
        ["Possession", deal.possessionDate],
      ] as Array<[string, string | null | undefined]>).flatMap(([label, value]) =>
        value ? [[label, value]] : [],
      )
    : [];
  const moneyRows: Array<[string, number]> = deal
    ? ([
        ["List price", deal.listPrice],
        ["Offer price", deal.offerPrice],
        ["Deposit", deal.depositAmount],
      ] as Array<[string, number | null | undefined]>).flatMap(([label, value]) =>
        typeof value === "number" ? [[label, value]] : [],
      )
    : [];

  return (
    <section className="mb-3 rounded-md border border-border bg-card px-3 py-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex min-w-0 items-center gap-2">
          <DatabaseIcon className="h-4 w-4 shrink-0 text-primary" />
          <h3 className="text-[0.88rem] font-semibold text-foreground">Transaction file</h3>
        </div>
        <div className="flex flex-wrap gap-1.5">
          {loading && (
            <Badge variant="outline" className="gap-1">
              <Loader2 className="h-3 w-3 animate-spin" />
              loading
            </Badge>
          )}
          {deal?.board && <Badge variant="outline">{deal.board}</Badge>}
          {deal?.market && <Badge variant="outline">{deal.market}</Badge>}
          {context && <Badge variant="outline">{attachments.length} docs</Badge>}
          {context && <Badge variant="outline">{priorRuns.length} runs</Badge>}
        </div>
      </div>

      {!loading && error && (
        <div className="mt-2 rounded-sm border border-border bg-background px-3 py-2 text-[0.78rem] text-warning">
          {error}
        </div>
      )}

      {!loading && !error && !context && (
        <div className="mt-2 rounded-sm border border-dashed border-border bg-background px-3 py-3 text-[0.78rem] text-muted-foreground">
          This preview card is not backed by a saved deal file yet.
        </div>
      )}

      {context && deal && (
        <div className="mt-3 space-y-3">
          {gate && (
            <div className="rounded-sm border border-border bg-background px-3 py-2">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div>
                  <div className="font-mono-ui text-[0.6rem] uppercase tracking-wider text-muted-foreground">
                    Phase gate
                  </div>
                  <div className="mt-1 text-[0.86rem] font-medium text-foreground">
                    {gate.stageName}
                    {gate.nextStageName ? ` -> ${gate.nextStageName}` : ""}
                  </div>
                </div>
                <Badge variant={gate.canAdvance ? "success" : "warning"}>
                  {gate.canAdvance ? "ready" : "blocked"}
                </Badge>
              </div>
              <div className="mt-2 grid gap-2 text-[0.74rem] sm:grid-cols-2">
                <div>
                  <span className="text-muted-foreground">Checklist: </span>
                  <span className="text-foreground">
                    {gate.completedChecklist}/{gate.totalChecklist}
                  </span>
                </div>
                <div>
                  <span className="text-muted-foreground">Package: </span>
                  <span className="text-foreground">{flow?.packageKey}</span>
                </div>
              </div>
              {(gate.missingChecklist.length > 0 || gate.missingFields.length > 0 || gate.missingDocs.length > 0 || gate.blockingRuns.length > 0) && (
                <div className="mt-2 space-y-1.5 text-[0.74rem]">
                  {gate.missingChecklist.slice(0, 4).map((item) => (
                    <div key={`check-${item.id}`} className="text-muted-foreground">
                      Missing checklist: <span className="text-foreground">{item.label}</span>
                    </div>
                  ))}
                  {gate.missingFields.slice(0, 4).map((item) => (
                    <div key={`field-${item.field}`} className="text-muted-foreground">
                      Missing field: <span className="text-foreground">{item.label}</span>
                    </div>
                  ))}
                  {gate.missingDocs.slice(0, 4).map((item) => (
                    <div key={`doc-${item.kind}`} className="text-muted-foreground">
                      Missing doc: <span className="text-foreground">{item.label}</span>
                    </div>
                  ))}
                  {gate.blockingRuns.slice(0, 4).map((run) => (
                    <div key={`run-${run.id}`} className="text-muted-foreground">
                      Waiting run: <span className="text-foreground">{run.label}</span>
                    </div>
                  ))}
                </div>
              )}
              <div className="mt-3 flex flex-wrap gap-2">
                <Button size="sm" disabled={!gate.canAdvance || busy} onClick={() => void onAdvance(false)}>
                  {busy && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
                  Advance phase
                </Button>
                {!gate.canAdvance && gate.nextStage != null && (
                  <Button size="sm" variant="outline" disabled={busy} onClick={() => void onAdvance(true)}>
                    Force advance
                  </Button>
                )}
              </div>
	            </div>
	          )}

	          {flow?.backgroundAutomations?.length ? (
	            <div className="rounded-sm border border-border bg-background px-3 py-2">
	              <div className="flex flex-wrap items-center justify-between gap-2">
	                <div>
	                  <div className="font-mono-ui text-[0.6rem] uppercase tracking-wider text-muted-foreground">
	                    Background automations
	                  </div>
	                  <div className="mt-1 text-[0.78rem] text-muted-foreground">
	                    Cron skills feed evidence into this deal; phases consume the results.
	                  </div>
	                </div>
	                <Badge variant="outline">{flow.backgroundAutomations.length}</Badge>
	              </div>
	              <div className="mt-2 grid gap-2 sm:grid-cols-2">
	                {flow.backgroundAutomations.map((item) => (
	                  <div key={item.id} className="rounded-md border border-border bg-card px-2 py-2">
	                    <div className="flex min-w-0 items-center justify-between gap-2">
	                      <span className="truncate text-[0.8rem] font-medium text-foreground">{item.name}</span>
	                      <Badge variant="secondary">{item.kind}</Badge>
	                    </div>
	                    <div className="mt-1 truncate font-mono-ui text-[0.62rem] uppercase tracking-wider text-muted-foreground">
	                      {item.skill}
	                    </div>
	                  </div>
	                ))}
	              </div>
	            </div>
	          ) : null}

	          <div className="grid gap-2 sm:grid-cols-2">
            <div className="rounded-sm border border-border bg-background px-3 py-2">
              <div className="font-mono-ui text-[0.6rem] uppercase tracking-wider text-muted-foreground">
                Primary contact
              </div>
              <div className="mt-1 truncate text-[0.86rem] font-medium text-foreground">
                {primary?.displayName ?? "Not linked"}
              </div>
              {(primary?.primaryEmail || primary?.primaryPhone) && (
                <div className="mt-1 space-y-0.5 text-[0.74rem] text-muted-foreground">
                  {primary.primaryEmail && <div className="truncate">{primary.primaryEmail}</div>}
                  {primary.primaryPhone && <div>{primary.primaryPhone}</div>}
                </div>
              )}
            </div>
            <div className="rounded-sm border border-border bg-background px-3 py-2">
              <div className="font-mono-ui text-[0.6rem] uppercase tracking-wider text-muted-foreground">
                Important dates
              </div>
              {dateRows.length > 0 ? (
                <div className="mt-1 grid grid-cols-2 gap-x-3 gap-y-1 text-[0.74rem]">
                  {dateRows.slice(0, 6).map(([label, value]) => (
                    <div key={label} className="min-w-0">
                      <span className="text-muted-foreground">{label}: </span>
                      <span className="text-foreground">{adminContextDate(value)}</span>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="mt-1 text-[0.74rem] text-muted-foreground">No dates set</div>
              )}
            </div>
          </div>

          {(moneyRows.length > 0 || deal.mlsNumber || deal.legalDescription) && (
            <div className="rounded-sm border border-border bg-background px-3 py-2">
              <div className="font-mono-ui text-[0.6rem] uppercase tracking-wider text-muted-foreground">
                File details
              </div>
              <div className="mt-1 grid gap-x-3 gap-y-1 text-[0.74rem] sm:grid-cols-2">
                {moneyRows.map(([label, value]) => (
                  <div key={label}>
                    <span className="text-muted-foreground">{label}: </span>
                    <span className="text-foreground">{adminContextMoney(value)}</span>
                  </div>
                ))}
                {deal.mlsNumber && (
                  <div>
                    <span className="text-muted-foreground">MLS: </span>
                    <span className="text-foreground">{deal.mlsNumber}</span>
                  </div>
                )}
                {deal.legalDescription && (
                  <div className="sm:col-span-2">
                    <span className="text-muted-foreground">Legal: </span>
                    <span className="text-foreground">{deal.legalDescription}</span>
                  </div>
                )}
              </div>
            </div>
          )}

          <div className="grid gap-2 sm:grid-cols-[minmax(0,1fr)_minmax(0,2fr)_minmax(0,1fr)]">
            <div className="rounded-sm border border-border bg-background px-3 py-2">
              <div className="flex items-center gap-1.5 font-mono-ui text-[0.6rem] uppercase tracking-wider text-muted-foreground">
                <Users className="h-3 w-3" />
                Co-contacts
              </div>
              {coContacts.length > 0 ? (
                <div className="mt-1.5 space-y-1">
                  {coContacts.slice(0, 3).map((item) => (
                    <div key={item.id} className="min-w-0 text-xs leading-5">
                      <span className="font-medium text-foreground">{item.role}</span>
                      <span className="text-muted-foreground"> · </span>
                      <span className="text-muted-foreground">{item.contact?.displayName ?? item.contactId}</span>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="mt-1.5 text-xs text-muted-foreground">None linked</div>
              )}
            </div>
            <div className="rounded-sm border border-border bg-background px-3 py-2">
              <div className="flex items-center gap-1.5 font-mono-ui text-[0.6rem] uppercase tracking-wider text-muted-foreground">
                <FileText className="h-3 w-3" />
                Documents
              </div>
              {attachments.length > 0 ? (
                <div className="mt-1.5 space-y-1.5">
                  {attachments.slice(0, 3).map((item) => (
                    <div
                      key={item.id}
                      className="min-w-0 text-xs leading-5 line-clamp-3"
                      title={item.summary || item.filePath}
                    >
                      <span className="font-medium text-foreground">{item.kind}</span>
                      {item.summary && <span className="text-muted-foreground"> · {item.summary}</span>}
                    </div>
                  ))}
                </div>
              ) : (
                <div className="mt-1.5 text-xs text-muted-foreground">No docs attached</div>
              )}
            </div>
            <div className="rounded-sm border border-border bg-background px-3 py-2">
              <div className="flex items-center gap-1.5 font-mono-ui text-[0.6rem] uppercase tracking-wider text-muted-foreground">
                <Clock className="h-3 w-3" />
                Prior runs
              </div>
              {priorRuns.length > 0 ? (
                <div className="mt-1.5 space-y-1.5">
                  {priorRuns.slice(0, 3).map((run) => (
                    <div key={run.id} className="min-w-0">
                      <div className="truncate text-xs font-medium leading-5 text-foreground">
                        {run.registryName ?? run.skill ?? "Admin run"}
                      </div>
                      <div className="mt-0.5 flex items-center gap-1.5">
                        <Badge variant={adminRunStatusVariant(run.status)}>{run.status}</Badge>
                        <span className="text-[0.68rem] text-muted-foreground">{isoTimeAgo(run.updatedAt)}</span>
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="mt-1.5 text-xs text-muted-foreground">No runs yet</div>
              )}
            </div>
          </div>

          <div className="rounded-sm border border-border bg-background px-3 py-2">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="font-mono-ui text-[0.6rem] uppercase tracking-wider text-muted-foreground">
                Source actions
              </div>
              <div className="flex flex-wrap gap-1.5">
                <Button size="sm" variant={actionMode === "dates" ? "default" : "outline"} onClick={() => setActionMode(actionMode === "dates" ? null : "dates")}>
                  <CalendarClock className="h-3.5 w-3.5" />
                  Dates
                </Button>
                <Button size="sm" variant={actionMode === "doc" ? "default" : "outline"} onClick={() => setActionMode(actionMode === "doc" ? null : "doc")}>
                  <FileText className="h-3.5 w-3.5" />
                  Attach
                </Button>
                <Button size="sm" variant={actionMode === "contact" ? "default" : "outline"} onClick={() => setActionMode(actionMode === "contact" ? null : "contact")}>
                  <Users className="h-3.5 w-3.5" />
                  Co-contact
                </Button>
              </div>
            </div>

            {actionMode === "dates" && (
              <form
                className="mt-3 grid gap-2 sm:grid-cols-2"
                onSubmit={(event) => {
                  event.preventDefault();
                  const fields = Object.fromEntries(
                    Object.entries(fieldDraft).filter(([, value]) => value.trim()),
                  );
                  void onUpdateFields(fields).then(() => {
                    setFieldDraft({
                      listingDate: "",
                      subjectRemovalDate: "",
                      depositDueDate: "",
                      completionDate: "",
                      possessionDate: "",
                      mlsNumber: "",
                      listPrice: "",
                    });
                    setActionMode(null);
                  });
                }}
              >
                {(["listingDate", "subjectRemovalDate", "depositDueDate", "completionDate", "possessionDate", "mlsNumber", "listPrice"] as const).map((field) => (
                  <label key={field} className="text-[0.72rem] text-muted-foreground">
                    {field}
                    <input
                      value={fieldDraft[field]}
                      onChange={(event) => setFieldDraft((prev) => ({ ...prev, [field]: event.target.value }))}
                      className="mt-1 h-10 w-full rounded-md border border-border bg-background px-2 text-[0.8rem] text-foreground focus:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                    />
                  </label>
                ))}
                <div className="sm:col-span-2">
                  <Button size="sm" type="submit" disabled={busy}>Update file fields</Button>
                </div>
              </form>
            )}

            {actionMode === "doc" && (
              <form
                className="mt-3 grid gap-2"
                onSubmit={(event) => {
                  event.preventDefault();
                  void onAddAttachment({
                    kind: docDraft.kind,
                    filePath: docDraft.filePath,
                    summary: docDraft.summary || null,
                  }).then(() => {
                    setDocDraft({ kind: "cma_report", filePath: "", summary: "" });
                    setActionMode(null);
                  });
                }}
              >
                <div className="grid gap-2 sm:grid-cols-2">
                  <input value={docDraft.kind} onChange={(event) => setDocDraft((prev) => ({ ...prev, kind: event.target.value }))} placeholder="kind, e.g. cma_report" className="h-10 rounded-md border border-border bg-background px-2 text-[0.8rem] text-foreground" />
                  <input value={docDraft.filePath} onChange={(event) => setDocDraft((prev) => ({ ...prev, filePath: event.target.value }))} placeholder="/path/to/file.pdf" className="h-10 rounded-md border border-border bg-background px-2 text-[0.8rem] text-foreground" />
                </div>
                <input value={docDraft.summary} onChange={(event) => setDocDraft((prev) => ({ ...prev, summary: event.target.value }))} placeholder="summary" className="h-10 rounded-md border border-border bg-background px-2 text-[0.8rem] text-foreground" />
                <Button size="sm" type="submit" disabled={busy || !docDraft.kind.trim() || !docDraft.filePath.trim()}>Attach document</Button>
              </form>
            )}

            {actionMode === "contact" && (
              <form
                className="mt-3 grid gap-2"
                onSubmit={(event) => {
                  event.preventDefault();
                  void onAddContact({
                    role: contactDraft.role,
                    contactId: contactDraft.contactId,
                    notes: contactDraft.notes || null,
                  }).then(() => {
                    setContactDraft({ role: "lawyer", contactId: "", notes: "" });
                    setActionMode(null);
                  });
                }}
              >
                <div className="grid gap-2 sm:grid-cols-2">
                  <input value={contactDraft.role} onChange={(event) => setContactDraft((prev) => ({ ...prev, role: event.target.value }))} placeholder="role, e.g. lawyer" className="h-10 rounded-md border border-border bg-background px-2 text-[0.8rem] text-foreground" />
                  <input value={contactDraft.contactId} onChange={(event) => setContactDraft((prev) => ({ ...prev, contactId: event.target.value }))} placeholder="contact id" className="h-10 rounded-md border border-border bg-background px-2 text-[0.8rem] text-foreground" />
                </div>
                <input value={contactDraft.notes} onChange={(event) => setContactDraft((prev) => ({ ...prev, notes: event.target.value }))} placeholder="notes" className="h-10 rounded-md border border-border bg-background px-2 text-[0.8rem] text-foreground" />
                <Button size="sm" type="submit" disabled={busy || !contactDraft.role.trim() || !contactDraft.contactId.trim()}>Add co-contact</Button>
              </form>
            )}
          </div>

          {pendingHumanRuns.length > 0 && (
            <div className="grid gap-2">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div>
                  <div className="text-[12px] font-semibold text-warning">
                    Pending approvals
                  </div>
                  <div className="mt-1 text-[0.76rem] leading-5 text-muted-foreground">
                    These are the Admin decisions blocking the next run or phase move.
                  </div>
                </div>
                <Badge variant="warning">{pendingHumanRuns.length}</Badge>
              </div>
              <div className="mt-2 space-y-2">
                {pendingHumanRuns.map((run) => (
                  <AdminRunDecisionRow
                    key={run.id}
                    compact
                    busyRun={busy ? { id: "__busy__", action: "approve" } : approvalBusyRun}
                    run={run}
                    onApprove={() => void resolvePendingRun(run, true)}
                    onCancel={() => void resolvePendingRun(run, false)}
                  />
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </section>
  );
}

function AdminCardDetailPanel({
  card,
  onClose,
  onToggleItem,
  onConditionChange,
  onMoveToNext,
  onDealUpdated,
}: {
  card: AdminCard;
  onClose: () => void;
  onToggleItem: (stage: AdminStageNumber, itemId: string, completed: boolean) => void;
  onConditionChange: (field: AdminConditionField, value: AdminConditionValue) => void;
  onMoveToNext: () => void;
  onDealUpdated: (deal: AdminDeal) => void;
}) {
  const nextStage = adminNextStage(card);
  const currentProgress = getCardProgress(card);
  const currentComplete = currentProgress.total > 0 && currentProgress.done === currentProgress.total;
  const currentStage = adminStageDefinition(card.stage);
  const currentLabel = currentStage.labels[card.side];
  const nextLabel = nextStage == null ? null : adminStageLabel(card.side, nextStage);

  const [expanded, setExpanded] = useState<Set<AdminStageNumber>>(() => new Set([card.stage]));
  const [dealContext, setDealContext] = useState<DealContext | null>(null);
  const [dealContextLoading, setDealContextLoading] = useState(false);
  const [dealContextError, setDealContextError] = useState<string | null>(null);
  const [dealActionBusy, setDealActionBusy] = useState(false);
  const titleId = useId();
  const dialogRef = useRef<HTMLElement>(null);

  useEffect(() => {
    setExpanded((prev) => (prev.has(card.stage) ? prev : new Set([...prev, card.stage])));
  }, [card.stage]);

  useEffect(() => {
    let active = true;
    setDealContext(null);
    setDealContextError(null);
    if (!isPersistedAdminDealId(card.id)) {
      setDealContextLoading(false);
      return () => {
        active = false;
      };
    }
    setDealContextLoading(true);
    api.getDealContext(card.id)
      .then((context) => {
        if (active) setDealContext(context);
      })
      .catch((err) => {
        if (active) {
          setDealContextError(errorMessage(err, "Deal context failed"));
        }
      })
      .finally(() => {
        if (active) setDealContextLoading(false);
      });
    return () => {
      active = false;
    };
  }, [card.id]);

  const reloadDealContext = useCallback(async () => {
    if (!isPersistedAdminDealId(card.id)) return null;
    const context = await api.getDealContext(card.id);
    setDealContext(context);
    onDealUpdated(context.deal);
    return context;
  }, [card.id, onDealUpdated]);

  const runDealAction = useCallback(
    async (action: () => Promise<void>) => {
      setDealActionBusy(true);
      setDealContextError(null);
      try {
        await action();
      } catch (err) {
        setDealContextError(errorMessage(err, "Deal action failed"));
      } finally {
        setDealActionBusy(false);
      }
    },
    [],
  );

  const handleAdvancePhase = useCallback(
    (force = false) =>
      runDealAction(async () => {
        const context = await api.advanceDeal(card.id, force);
        setDealContext(context);
        onDealUpdated(context.deal);
      }),
    [card.id, onDealUpdated, runDealAction],
  );

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  // Focus trap + restore focus on close.
  useEffect(() => {
    const previouslyFocused = document.activeElement as HTMLElement | null;
    const root = dialogRef.current;
    if (!root) return;

    const focusableSelector =
      'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';
    const getFocusables = () =>
      Array.from(root.querySelectorAll<HTMLElement>(focusableSelector)).filter(
        (el) => !el.hasAttribute("inert") && el.offsetParent !== null,
      );

    queueMicrotask(() => {
      const focusables = getFocusables();
      focusables[0]?.focus();
    });

    const onKey = (event: globalThis.KeyboardEvent) => {
      if (event.key !== "Tab") return;
      const focusables = getFocusables();
      if (focusables.length === 0) return;
      const first = focusables[0];
      const last = focusables[focusables.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    root.addEventListener("keydown", onKey);
    return () => {
      root.removeEventListener("keydown", onKey);
      previouslyFocused?.focus?.();
    };
  }, []);

  const toggleSection = (stage: AdminStageNumber) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(stage)) next.delete(stage);
      else next.add(stage);
      return next;
    });
  };

  const due = dueLabel(card.daysOut);
  const laneLabel = ADMIN_SIDE_LABELS[card.side].title;
  const phaseGate = dealContext?.dealFlow?.gate ?? null;
  const showAdvancePrompt = nextStage != null && nextLabel && (phaseGate ? phaseGate.canAdvance : currentComplete);

  return createPortal(
    <div className="fixed inset-0 z-50 flex items-stretch justify-center sm:items-center sm:p-6">
      <button
        type="button"
        aria-label="Close detail"
        onClick={onClose}
        className="absolute inset-0 z-0 bg-background/80"
      />
      <aside
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        className="relative z-10 flex h-full w-full flex-col bg-card sm:h-auto sm:max-h-full sm:w-full sm:max-w-[42rem] sm:rounded-md sm:border sm:border-border md:max-w-[48rem] lg:max-w-[56rem]"
      >
        <header className="flex items-start justify-between gap-3 border-b border-border px-4 py-3">
          <div className="min-w-0">
            <div className="flex items-center gap-2 font-mono-ui text-[0.6rem] uppercase tracking-wider text-muted-foreground">
              <span>{laneLabel} admin</span>
              <span>·</span>
              <span className="text-primary">{currentStage.stageNumber}</span>
              <span>·</span>
              <span className="text-primary">{currentLabel.title}</span>
              {card.pinnedTop25 && (
                <span className="inline-flex items-center gap-1 rounded-sm border border-border bg-transparent px-1.5 py-0.5 text-warning">
                  <Flame className="h-2.5 w-2.5" />
                  Top
                </span>
              )}
            </div>
            <h2 id={titleId} className="mt-0.5 text-[1rem] font-semibold leading-tight text-foreground">
              {card.client}
            </h2>
            {card.property && (
              <div className="mt-1 flex items-start gap-1.5 text-[0.78rem] text-muted-foreground">
                <Building2 className="mt-[2px] h-3.5 w-3.5 shrink-0" />
                <span>{card.property}</span>
              </div>
            )}
            {card.nextLabel && (
              <div className="mt-1 flex items-center gap-1.5 text-[0.78rem]">
                <CalendarClock className="h-3.5 w-3.5 text-muted-foreground" />
                <span className="text-foreground">{card.nextLabel}</span>
                <span
                  className={cn(
                    "font-mono-ui text-[0.68rem]",
                    due.tone === "danger" && "text-destructive",
                    due.tone === "warn" && "text-warning",
                    due.tone === "ok" && "text-muted-foreground",
                    due.tone === "muted" && "text-muted-foreground",
                  )}
                >
                  · {due.text}
                </span>
              </div>
            )}
          </div>
          <button
            type="button"
            onClick={onClose}
            className="inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-md text-muted-foreground hover:bg-muted hover:text-foreground focus:outline-none focus-visible:ring-1 focus-visible:ring-ring"
            aria-label="Close"
          >
            <CloseIcon className="h-4 w-4" />
          </button>
        </header>

        {showAdvancePrompt && nextStage != null && nextLabel && (
          <div className="border-b border-border bg-muted px-4 py-2.5">
            <div className="flex items-center gap-2 text-[0.78rem]">
              <CheckCircle2 className="h-4 w-4 text-primary" />
              <span className="text-foreground">
                All {currentStage.stageNumber} items done - move to {nextLabel.title}?
              </span>
              <button
                type="button"
                onClick={() => {
                  if (phaseGate) void handleAdvancePhase(false);
                  else onMoveToNext();
                }}
                className="ml-auto inline-flex min-h-11 items-center gap-1 rounded-sm border border-border bg-card px-3 py-2 text-[0.8rem] font-medium text-primary hover:bg-muted focus:outline-none focus-visible:ring-1 focus-visible:ring-ring"
              >
                Move card →
              </button>
            </div>
          </div>
        )}

        <div className="flex-1 overflow-y-auto px-4 py-3">
          {card.sourceContext && <AdminCardSourceSection context={card.sourceContext} />}
          <AdminDealContextSection
            context={dealContext}
            loading={dealContextLoading}
            error={dealContextError}
            busy={dealActionBusy}
            onAdvance={handleAdvancePhase}
            onUpdateFields={(fields) =>
              runDealAction(async () => {
                const deal = await api.updateDealFields(card.id, fields);
                onDealUpdated(deal);
                await reloadDealContext();
              })
            }
            onAddAttachment={(body) =>
              runDealAction(async () => {
                await api.addDealAttachment(card.id, body);
                await reloadDealContext();
              })
            }
            onAddContact={(body) =>
              runDealAction(async () => {
                await api.addDealContact(card.id, body);
                await reloadDealContext();
              })
            }
            onApproveRun={(runId) =>
              runDealAction(async () => {
                await api.approveAdminActionRun(runId, { approved: true, runNow: true });
                await reloadDealContext();
              })
            }
            onCancelRun={(runId) =>
              runDealAction(async () => {
                await api.approveAdminActionRun(runId, { approved: false, runNow: false });
                await reloadDealContext();
              })
            }
          />
          <div className="flex flex-col gap-2">
            {ADMIN_STAGE_NUMBERS.map((stage) => (
                <AdminCardStageSection
                  key={`${card.side}-${stage}`}
                  card={card}
                  stage={stage}
                  isCurrent={stage === card.stage}
                  isPast={stage < card.stage}
                  expanded={expanded.has(stage)}
                  onToggleExpand={() => toggleSection(stage)}
                  onToggleItem={(itemId, completed) => onToggleItem(stage, itemId, completed)}
                  documents={dealContext?.stageDocuments?.stages[String(stage)] ?? []}
                />
            ))}
          </div>
          <AdminCardConditionsSection card={card} onConditionChange={onConditionChange} />
        </div>
      </aside>
    </div>,
    document.body,
  );
}

function NewDealDialog({
  onClose,
  onCreated,
}: {
  onClose: () => void;
  onCreated: (placeholderCard: AdminCard, request: AdminDealCreateRequest) => Promise<void>;
}) {
  const titleId = useId();
  const dialogRef = useRef<HTMLElement>(null);
  const [title, setTitle] = useState("");
  const [side, setSide] = useState<AdminSide>("listing");
  const [stage, setStage] = useState<AdminStageNumber>(0);
  const [province, setProvince] = useState("");
  const [setupProvince, setSetupProvince] = useState("");
  const [provinceOverride, setProvinceOverride] = useState(false);
  const [provinceCoverage, setProvinceCoverage] = useState<AdminProvinceGuideCoverage[]>([]);
  const [contactId, setContactId] = useState<string | null>(null);
  const [contactQuery, setContactQuery] = useState("");
  const [contacts, setContacts] = useState<AdminContact[]>([]);
  const [contactsLoading, setContactsLoading] = useState(false);
  const [contactsError, setContactsError] = useState<string | null>(null);
  const [listingAddress, setListingAddress] = useState("");
  const [propertySubtype, setPropertySubtype] = useState("");
  const [listingType, setListingType] = useState("");
  const [signingAuthority, setSigningAuthority] = useState("");
  const [transactionType, setTransactionType] = useState("");
  const [notes, setNotes] = useState("");
  const [notesAutoFilled, setNotesAutoFilled] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);

  useEffect(() => {
    const previouslyFocused = document.activeElement as HTMLElement | null;
    const root = dialogRef.current;
    if (!root) return;
    const focusableSelector =
      'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';
    const getFocusables = () =>
      Array.from(root.querySelectorAll<HTMLElement>(focusableSelector)).filter(
        (el) => !el.hasAttribute("inert") && el.offsetParent !== null,
      );
    queueMicrotask(() => {
      const focusables = getFocusables();
      focusables[0]?.focus();
    });
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onClose();
        return;
      }
      if (event.key !== "Tab") return;
      const focusables = getFocusables();
      if (focusables.length === 0) return;
      const first = focusables[0];
      const last = focusables[focusables.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    root.addEventListener("keydown", onKey);
    return () => {
      root.removeEventListener("keydown", onKey);
      previouslyFocused?.focus?.();
    };
  }, [onClose]);

  useEffect(() => {
    let cancelled = false;
    api
      .getAdminJurisdiction()
      .then((jurisdiction) => {
        if (cancelled) return;
        const code = (jurisdiction.province || "").trim().toUpperCase();
        setProvince(code);
        setSetupProvince(code);
      })
      .catch(() => {});
    api
      .getAdminProvinceGuides()
      .then((guides) => {
        if (cancelled) return;
        if ("items" in guides) {
          setProvinceCoverage(guides.items);
        }
      })
      .catch(() => {
        if (!cancelled) setProvinceCoverage([]);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    setContactsLoading(true);
    setContactsError(null);
    api
      .getAdminContacts({ limit: 200 })
      .then((response) => {
        if (cancelled) return;
        setContacts(response.items);
      })
      .catch((err) => {
        if (cancelled) return;
        setContactsError(err instanceof Error ? err.message : "Could not load contacts");
      })
      .finally(() => {
        if (!cancelled) setContactsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const provinceCoverageByCode = useMemo(() => {
    return new Map(provinceCoverage.map((item) => [item.province, item]));
  }, [provinceCoverage]);

  const selectedProvinceCoverage = provinceCoverageByCode.get(province);

  const filteredContacts = useMemo(() => {
    const q = contactQuery.trim().toLowerCase();
    if (!q) return contacts.slice(0, 8);
    return contacts
      .filter((contact) => {
        const haystack = [contact.displayName, contact.primaryEmail, contact.primaryPhone]
          .filter(Boolean)
          .join(" ")
          .toLowerCase();
        return haystack.includes(q);
      })
      .slice(0, 8);
  }, [contacts, contactQuery]);

  const selectedContact = contacts.find((c) => c.id === contactId) ?? null;

  const handleSelectContact = (contact: AdminContact) => {
    setContactId(contact.id);
    setContactQuery("");
    if (!title.trim() && contact.displayName) {
      setTitle(contact.displayName);
    }
    if (!notes.trim() || notesAutoFilled) {
      const bits: string[] = [];
      if (contact.sourceKey) bits.push(`Source: ${contact.sourceKey}`);
      if (contact.type) bits.push(`Type: ${contact.type}`);
      if (contact.stage) bits.push(`Stage: ${contact.stage}`);
      if (contact.lastActivityAt) bits.push(`Last activity: ${isoTimeAgo(contact.lastActivityAt)}`);
      if (contact.ownerNotes) bits.push(`\nNotes: ${contact.ownerNotes}`);
      const filled = bits.join("\n");
      if (filled) {
        setNotes(filled);
        setNotesAutoFilled(true);
      }
    }
  };

  const clearContact = () => {
    setContactId(null);
    setContactQuery("");
    if (notesAutoFilled) {
      setNotes("");
      setNotesAutoFilled(false);
    }
  };

  const canSubmit = title.trim().length > 0 && province.trim().length > 0 && !submitting;

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!canSubmit) return;
    setSubmitting(true);
    setSubmitError(null);
    const cleanTitle = title.trim();
    const cleanAddress = listingAddress.trim();
    const cleanNotes = notes.trim();
    const placeholderId = `local-${Date.now()}`;
    const stageLabel = adminStageLabel(side, stage);
    const conditions: Partial<Record<AdminConditionField, AdminConditionValue>> = {};
    const fields: Record<string, unknown> = {};
    if (side === "listing") {
      if (signingAuthority) {
        fields.signing_authority = signingAuthority;
        conditions.signing_authority = signingAuthority;
      }
      if (listingType) {
        fields.listing_type = listingType;
        conditions.listing_type = listingType;
      }
    } else if (transactionType) {
      fields.transaction_type = transactionType;
      conditions.transaction_type = transactionType;
    }
    if (propertySubtype) {
      fields.property_subtype = propertySubtype;
      conditions.property_subtype = propertySubtype;
    }
    if (cleanNotes) fields.notes = cleanNotes;
    const placeholder: AdminCard = {
      id: placeholderId,
      side,
      stage,
      client: cleanTitle,
      contactInitials: initialsFromTitle(cleanTitle),
      property: cleanAddress || `${province} deal`,
      nextLabel: stageLabel.title,
      pinnedTop25: false,
      completedByStage: {},
      conditions,
    };
    const request: AdminDealCreateRequest = {
      title: cleanTitle,
      side,
      province,
      currentStage: stage,
      primaryContactId: contactId,
      listingAddress: side === "listing" ? cleanAddress || null : null,
      fields,
    };
    try {
      await onCreated(placeholder, request);
      onClose();
    } catch (err) {
      setSubmitError(err instanceof Error ? err.message : "Could not create deal");
    } finally {
      setSubmitting(false);
    }
  };

  const subtypeOptions =
    ADMIN_ENUM_CONDITIONS.find((c) => c.field === "property_subtype")?.options ?? [];
  const listingTypeOptions =
    ADMIN_ENUM_CONDITIONS.find((c) => c.field === "listing_type")?.options ?? [];
  const signingAuthorityOptions =
    ADMIN_ENUM_CONDITIONS.find((c) => c.field === "signing_authority")?.options ?? [];
  const transactionTypeOptions =
    ADMIN_ENUM_CONDITIONS.find((c) => c.field === "transaction_type")?.options ?? [];

  return createPortal(
    <div className="fixed inset-0 z-50 flex items-stretch justify-center sm:items-center sm:p-6">
      <button
        type="button"
        aria-label="Close new deal"
        onClick={onClose}
        className="absolute inset-0 z-0 bg-background/80"
      />
      <aside
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        className="relative z-10 flex h-full w-full flex-col bg-card sm:h-auto sm:max-h-[calc(100vh-3rem)] sm:w-full sm:max-w-[34rem] sm:rounded-md sm:border sm:border-border"
      >
        <div className="flex items-start justify-between gap-3 border-b border-border px-4 py-3">
          <div className="min-w-0">
            <div className="font-mono-ui text-[0.62rem] uppercase tracking-wider text-muted-foreground">
              New deal
            </div>
            <h2 id={titleId} className="mt-0.5 text-[1rem] font-semibold leading-tight text-foreground">
              Add a card to the board
            </h2>
          </div>
          <Button variant="ghost" size="icon" onClick={onClose} className="h-11 w-11 shrink-0" aria-label="Close">
            <CloseIcon className="h-4 w-4" />
          </Button>
        </div>
        <form onSubmit={handleSubmit} className="flex flex-1 flex-col gap-4 overflow-y-auto px-4 py-4">
          <div>
            <label className="mb-1.5 block text-[12px] font-medium text-muted-foreground" htmlFor={`${titleId}-side`}>
              Side
            </label>
            <div id={`${titleId}-side`} role="radiogroup" className="mt-1.5 grid grid-cols-2 gap-2">
              {(["listing", "buyer"] as AdminSide[]).map((option) => {
                const active = side === option;
                const Icon = option === "listing" ? Home : Users;
                return (
                  <button
                    key={option}
                    type="button"
                    role="radio"
                    aria-checked={active}
                    onClick={() => setSide(option)}
                    className={cn(
                      "flex min-h-11 items-center justify-center gap-2 rounded-sm border px-3 py-2 text-[0.86rem] font-medium transition-colors focus:outline-none focus-visible:ring-1 focus-visible:ring-ring",
                      active
                        ? "border-primary bg-muted text-foreground"
                        : "border-border bg-background text-muted-foreground hover:bg-muted hover:text-foreground",
                    )}
                  >
                    <Icon className={cn("h-4 w-4", active ? "text-primary" : "text-muted-foreground")} />
                    {ADMIN_SIDE_LABELS[option].title}
                  </button>
                );
              })}
            </div>
          </div>

          <div>
            <div className="mb-1.5 flex items-center justify-between gap-2">
              <label htmlFor={`${titleId}-province`} className="block text-[12px] font-medium text-muted-foreground">
                Province / territory <span className="text-destructive">*</span>
              </label>
              {setupProvince && !provinceOverride && (
                <button
                  type="button"
                  onClick={() => setProvinceOverride(true)}
                  className="text-[11px] text-muted-foreground underline-offset-2 hover:text-foreground hover:underline"
                >
                  Change for this deal
                </button>
              )}
              {setupProvince && provinceOverride && (
                <button
                  type="button"
                  onClick={() => {
                    setProvinceOverride(false);
                    setProvince(setupProvince);
                  }}
                  className="text-[11px] text-muted-foreground underline-offset-2 hover:text-foreground hover:underline"
                >
                  Reset to setup ({setupProvince})
                </button>
              )}
            </div>
            {setupProvince && !provinceOverride ? (
              <div
                id={`${titleId}-province`}
                className="mt-1.5 flex h-11 w-full items-center rounded-sm border border-border bg-muted/40 px-3 text-[0.88rem] text-foreground"
              >
                <span>{PROVINCE_LABEL_BY_CODE.get(setupProvince) ?? setupProvince}</span>
                <span className="ml-2 font-mono-ui text-[0.58rem] uppercase tracking-wider text-muted-foreground">
                  from setup
                </span>
              </div>
            ) : (
              <select
                id={`${titleId}-province`}
                value={province}
                onChange={(e) => setProvince(e.target.value)}
                required
                className="mt-1.5 h-11 w-full rounded-sm border border-border bg-background px-3 text-[0.88rem] text-foreground focus:border-border focus:outline-none focus-visible:ring-1 focus-visible:ring-ring"
              >
                <option value="">Select province</option>
                {CANADIAN_PROVINCES.map(({ code, label }) => {
                  const coverage = provinceCoverageByCode.get(code);
                  const suffix = coverage?.hasTransactionGuide ? " - full guide" : coverage ? " - reference" : "";
                  return (
                    <option key={code} value={code}>
                      {label}
                      {suffix}
                    </option>
                  );
                })}
              </select>
            )}
            {selectedProvinceCoverage && (
              <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
                <span className="font-mono-ui rounded border border-border bg-card px-1.5 py-0.5 text-[0.58rem] uppercase tracking-wider text-muted-foreground">
                  {selectedProvinceCoverage.hasTransactionGuide ? "full guide" : "reference"}
                </span>
                <span className="font-mono-ui rounded border border-border bg-card px-1.5 py-0.5 text-[0.58rem] uppercase tracking-wider text-muted-foreground">
                  {selectedProvinceCoverage.referencePages} pages
                </span>
                {selectedProvinceCoverage.forms > 0 && (
                  <span className="font-mono-ui rounded border border-border bg-card px-1.5 py-0.5 text-[0.58rem] uppercase tracking-wider text-muted-foreground">
                    {selectedProvinceCoverage.forms} forms
                  </span>
                )}
              </div>
            )}
          </div>

          <div>
            <label htmlFor={`${titleId}-contact`} className="mb-1.5 block text-[12px] font-medium text-muted-foreground">
              Contact (optional)
            </label>
            {selectedContact ? (
              <div className="mt-1.5 rounded-sm border border-border bg-card px-3 py-2.5">
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-[0.92rem] font-semibold text-foreground">
                      {selectedContact.displayName ?? "(unnamed)"}
                    </div>
                    <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-[0.74rem] text-muted-foreground">
                      {selectedContact.primaryEmail && (
                        <span className="inline-flex items-center gap-1">
                          <Mail className="h-3 w-3" aria-hidden />
                          <span className="truncate">{selectedContact.primaryEmail}</span>
                        </span>
                      )}
                      {selectedContact.primaryPhone && (
                        <span className="inline-flex items-center gap-1">
                          <Phone className="h-3 w-3" aria-hidden />
                          <span>{selectedContact.primaryPhone}</span>
                        </span>
                      )}
                    </div>
                  </div>
                  <Button type="button" variant="ghost" size="sm" onClick={clearContact} className="shrink-0">
                    Change
                  </Button>
                </div>
                {(selectedContact.type || selectedContact.stage || selectedContact.sourceKey) && (
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    {selectedContact.type && (
                      <span className="font-mono-ui rounded border border-border bg-card px-1.5 py-0.5 text-[0.6rem] uppercase tracking-wider text-muted-foreground">
                        {selectedContact.type}
                      </span>
                    )}
                    {selectedContact.stage && (
                      <span className="font-mono-ui rounded border border-border bg-card px-1.5 py-0.5 text-[0.6rem] uppercase tracking-wider text-muted-foreground">
                        {selectedContact.stage}
                      </span>
                    )}
                    {selectedContact.sourceKey && (
                      <span className="font-mono-ui rounded border border-border bg-card px-1.5 py-0.5 text-[0.6rem] uppercase tracking-wider text-muted-foreground">
                        src: {selectedContact.sourceKey}
                      </span>
                    )}
                  </div>
                )}
                {(selectedContact.lastActivityAt || selectedContact.ownerNotes) && (
                  <div className="mt-2 space-y-1 border-t border-border pt-2 text-[0.72rem] text-muted-foreground">
                    {selectedContact.lastActivityAt && (
                      <div className="inline-flex items-center gap-1">
                        <Clock className="h-3 w-3" aria-hidden />
                        <span>last activity {isoTimeAgo(selectedContact.lastActivityAt)}</span>
                      </div>
                    )}
                    {selectedContact.ownerNotes && (
                      <div className="line-clamp-2 italic">"{selectedContact.ownerNotes}"</div>
                    )}
                  </div>
                )}
              </div>
            ) : (
              <>
                <input
                  id={`${titleId}-contact`}
                  type="text"
                  value={contactQuery}
                  onChange={(e) => setContactQuery(e.target.value)}
                  placeholder={contactsLoading ? "Loading contacts…" : "Search by name, email, phone"}
                  className="mt-1.5 h-11 w-full rounded-sm border border-border bg-background px-3 text-[0.88rem] text-foreground placeholder:text-muted-foreground focus:border-border focus:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                  autoComplete="off"
                />
                {contactsError && (
                  <div className="mt-1 text-[0.72rem] text-warning">{contactsError}</div>
                )}
                {filteredContacts.length > 0 && (
                  <div className="mt-1.5 max-h-48 overflow-y-auto rounded-sm border border-border bg-card">
                    {filteredContacts.map((contact) => (
                      <button
                        key={contact.id}
                        type="button"
                        onClick={() => handleSelectContact(contact)}
                        className="flex w-full items-start gap-3 border-b border-border px-3 py-2 text-left last:border-b-0 hover:bg-muted focus:outline-none focus:bg-muted"
                      >
                        <div className="min-w-0 flex-1">
                          <div className="truncate text-[0.86rem] font-medium text-foreground">
                            {contact.displayName ?? "(unnamed)"}
                          </div>
                          <div className="truncate text-[0.72rem] text-muted-foreground">
                            {contact.primaryEmail ?? contact.primaryPhone ?? "no contact info"}
                          </div>
                        </div>
                        {contact.type && (
                          <span className="font-mono-ui shrink-0 text-[0.6rem] uppercase tracking-wider text-muted-foreground">
                            {contact.type}
                          </span>
                        )}
                      </button>
                    ))}
                  </div>
                )}
                {!contactsLoading && contacts.length === 0 && !contactsError && (
                  <div className="mt-1 text-[0.72rem] text-muted-foreground">
                    No contacts in DB yet. Skip this field or sync your CRM first.
                  </div>
                )}
              </>
            )}
          </div>

          <div>
            <label htmlFor={`${titleId}-title`} className="mb-1.5 block text-[12px] font-medium text-muted-foreground">
              Title <span className="text-destructive">*</span>
            </label>
            <input
              id={`${titleId}-title`}
              type="text"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder={side === "listing" ? "e.g. Lewis Creek seller" : "e.g. Tessa & Ryan"}
              required
              className="mt-1.5 h-11 w-full rounded-sm border border-border bg-background px-3 text-[0.88rem] text-foreground placeholder:text-muted-foreground focus:border-border focus:outline-none focus-visible:ring-1 focus-visible:ring-ring"
            />
          </div>

          <div>
            <label htmlFor={`${titleId}-stage`} className="mb-1.5 block text-[12px] font-medium text-muted-foreground">
              Starting stage
            </label>
            <select
              id={`${titleId}-stage`}
              value={stage}
              onChange={(e) => setStage(toAdminStage(Number(e.target.value)))}
              className="mt-1.5 h-11 w-full rounded-sm border border-border bg-background px-3 text-[0.88rem] text-foreground focus:border-border focus:outline-none focus-visible:ring-1 focus-visible:ring-ring"
            >
              {ADMIN_STAGE_NUMBERS.map((s) => {
                const def = adminStageDefinition(s);
                return (
                  <option key={s} value={s}>
                    {def.stageNumber} · {def.labels[side].title}
                  </option>
                );
              })}
            </select>
          </div>

          <div className="space-y-3 rounded-sm border border-border bg-card px-3 py-3">
            <div className="text-[12px] font-semibold text-muted-foreground">
              {side === "listing" ? "Property" : "Search"}
            </div>
            {side === "listing" && (
              <div>
                <label htmlFor={`${titleId}-address`} className="block text-[0.74rem] text-muted-foreground">
                  Listing address
                </label>
                <input
                  id={`${titleId}-address`}
                  type="text"
                  value={listingAddress}
                  onChange={(e) => setListingAddress(e.target.value)}
                  placeholder="e.g. 123 Lewis Creek Rd, Kelowna BC"
                  className="mt-1 h-11 w-full rounded-sm border border-border bg-background px-3 text-[0.86rem] text-foreground placeholder:text-muted-foreground focus:border-border focus:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                />
              </div>
            )}
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <div>
                <label htmlFor={`${titleId}-subtype`} className="block text-[0.74rem] text-muted-foreground">
                  Property type
                </label>
                <select
                  id={`${titleId}-subtype`}
                  value={propertySubtype}
                  onChange={(e) => setPropertySubtype(e.target.value)}
                  className="mt-1 h-11 w-full rounded-sm border border-border bg-background px-3 text-[0.86rem] text-foreground focus:border-border focus:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                >
                  <option value="">— select —</option>
                  {subtypeOptions.map((opt) => (
                    <option key={opt.value} value={opt.value}>
                      {opt.label}
                    </option>
                  ))}
                </select>
              </div>
              {side === "listing" ? (
                <div>
                  <label htmlFor={`${titleId}-listing-type`} className="block text-[0.74rem] text-muted-foreground">
                    Listing type
                  </label>
                  <select
                    id={`${titleId}-listing-type`}
                    value={listingType}
                    onChange={(e) => setListingType(e.target.value)}
                    className="mt-1 h-11 w-full rounded-sm border border-border bg-background px-3 text-[0.86rem] text-foreground focus:border-border focus:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                  >
                    <option value="">— select —</option>
                    {listingTypeOptions.map((opt) => (
                      <option key={opt.value} value={opt.value}>
                        {opt.label}
                      </option>
                    ))}
                  </select>
                </div>
              ) : (
                <div>
                  <label htmlFor={`${titleId}-tx-type`} className="block text-[0.74rem] text-muted-foreground">
                    Transaction type
                  </label>
                  <select
                    id={`${titleId}-tx-type`}
                    value={transactionType}
                    onChange={(e) => setTransactionType(e.target.value)}
                    className="mt-1 h-11 w-full rounded-sm border border-border bg-background px-3 text-[0.86rem] text-foreground focus:border-border focus:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                  >
                    <option value="">— select —</option>
                    {transactionTypeOptions.map((opt) => (
                      <option key={opt.value} value={opt.value}>
                        {opt.label}
                      </option>
                    ))}
                  </select>
                </div>
              )}
            </div>
            {side === "listing" && (
              <div>
                <label htmlFor={`${titleId}-signing`} className="block text-[0.74rem] text-muted-foreground">
                  Signing authority
                </label>
                <select
                  id={`${titleId}-signing`}
                  value={signingAuthority}
                  onChange={(e) => setSigningAuthority(e.target.value)}
                  className="mt-1 h-11 w-full rounded-sm border border-border bg-background px-3 text-[0.86rem] text-foreground focus:border-border focus:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                >
                  <option value="">— select —</option>
                  {signingAuthorityOptions.map((opt) => (
                    <option key={opt.value} value={opt.value}>
                      {opt.label}
                    </option>
                  ))}
                </select>
              </div>
            )}
          </div>

          <div>
            <div className="flex items-center justify-between">
              <label htmlFor={`${titleId}-notes`} className="mb-1.5 block text-[12px] font-medium text-muted-foreground">
                Notes
              </label>
              {notesAutoFilled && (
                <span className="text-[0.7rem] text-primary">
                  auto-filled from contact
                </span>
              )}
            </div>
            <textarea
              id={`${titleId}-notes`}
              value={notes}
              onChange={(e) => {
                setNotes(e.target.value);
                if (notesAutoFilled) setNotesAutoFilled(false);
              }}
              rows={3}
              placeholder="Anything relevant to start this deal — context, urgency, source"
              className="mt-1.5 w-full rounded-sm border border-border bg-background px-3 py-2 text-[0.86rem] text-foreground placeholder:text-muted-foreground focus:border-border focus:outline-none focus-visible:ring-1 focus-visible:ring-ring"
            />
          </div>

          {submitError && (
            <div className="rounded-sm border border-border bg-card px-3 py-2 text-[0.78rem] text-destructive">
              {submitError}
            </div>
          )}

          <div className="mt-auto flex items-center justify-end gap-2 border-t border-border pt-3">
            <Button type="button" variant="ghost" onClick={onClose} disabled={submitting}>
              Cancel
            </Button>
            <Button type="submit" disabled={!canSubmit}>
              {submitting && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
              Create deal
            </Button>
          </div>
        </form>
      </aside>
    </div>,
    document.body,
  );
}

function AdminKanbanBoard() {
  const adminDeals = useAdminDeals();
  const cards = adminDeals.deals;
  const [selectedCardId, setSelectedCardId] = useState<string | null>(null);
  const [activeSide, setActiveSide] = useState<AdminSide>("listing");
  const [showNewDeal, setShowNewDeal] = useState(false);
  const draggingIdRef = useRef<string | null>(null);
  const [searchParams, setSearchParams] = useSearchParams();
  const dealQuery = searchParams.get("deal");
  const handledDealQueryRef = useRef<string | null>(null);

  useEffect(() => {
    if (!dealQuery) {
      handledDealQueryRef.current = null;
      return;
    }
    if (handledDealQueryRef.current === dealQuery) return;
    const match = cards.find((c) => c.id === dealQuery);
    if (!match) return;
    handledDealQueryRef.current = dealQuery;
    setSelectedCardId(match.id);
    setActiveSide(match.side);
  }, [dealQuery, cards]);

  const clearDealQuery = useCallback(() => {
    if (!searchParams.has("deal")) return;
    const next = new URLSearchParams(searchParams);
    next.delete("deal");
    setSearchParams(next, { replace: true });
  }, [searchParams, setSearchParams]);

  const closeDetailPanel = useCallback(() => {
    setSelectedCardId(null);
    clearDealQuery();
  }, [clearDealQuery]);

  const handleCreateDeal = useCallback(
    async (placeholder: AdminCard, request: AdminDealCreateRequest) => {
      adminDeals.addLocalDeal(placeholder);
      setActiveSide(placeholder.side);
      try {
        const created = await api.createAdminDeal(request);
        adminDeals.replaceLocalDeal(placeholder.id, created);
      } catch (err) {
        if (isApiNotFound(err)) {
          console.warn("POST /api/admin/deals returned 404; keeping optimistic local card.");
          return;
        }
        throw err;
      }
    },
    [adminDeals],
  );

  const selectedCard = cards.find((c) => c.id === selectedCardId) ?? null;

  const buckets = useMemo(() => {
    const empty = (): Record<AdminStageNumber, AdminCard[]> => ({
      0: [], 1: [], 2: [], 3: [], 4: [], 5: [], 6: [], 7: [], 8: [], 9: [], 10: [],
    });
    const byStage: Record<AdminSide, Record<AdminStageNumber, AdminCard[]>> = {
      listing: empty(),
      buyer: empty(),
    };
    const counts: Record<AdminSide, number> = { listing: 0, buyer: 0 };
    for (const card of cards) {
      byStage[card.side][card.stage].push(card);
      counts[card.side] += 1;
    }
    return { byStage, counts };
  }, [cards]);

  const handleMoveToNext = useCallback(
    (cardId: string) => {
      const card = cards.find((candidate) => candidate.id === cardId);
      const nextStage = card ? adminNextStage(card) : null;
      if (nextStage != null) void adminDeals.moveDeal(cardId, nextStage);
    },
    [adminDeals, cards],
  );

  const handleToggleItem = useCallback(
    (cardId: string, itemId: string, completed: boolean) => {
      void adminDeals.setDealToggle(cardId, itemId, completed);
    },
    [adminDeals],
  );

  const handleConditionChange = useCallback(
    (cardId: string, field: AdminConditionField, value: AdminConditionValue) => {
      void adminDeals.setDealToggle(cardId, field, value);
    },
    [adminDeals],
  );

  const handleCardDragStart = useCallback((cardId: string) => {
    draggingIdRef.current = cardId;
  }, []);

  const handleCardDrop = useCallback(
    (targetSide: AdminSide, targetStage: AdminStageNumber) => {
      const draggedId = draggingIdRef.current;
      draggingIdRef.current = null;
      if (!draggedId) return;
      const card = cards.find((candidate) => candidate.id === draggedId);
      if (!card) return;
      if (card.side !== targetSide) return; // cross-side moves not supported
      if (card.stage === targetStage) return;
      void adminDeals.moveDeal(draggedId, targetStage);
    },
    [adminDeals, cards],
  );

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-border bg-card px-3 py-2">
        <div role="status" aria-live="polite" className="flex min-w-0 flex-wrap items-center gap-2">
          <span className="font-mono-ui text-[0.62rem] uppercase tracking-wider text-muted-foreground">
            {cards.length} admin deals
          </span>
          {adminDeals.loading && (
            <span className="inline-flex items-center gap-1 font-mono-ui text-[0.62rem] uppercase tracking-wider text-muted-foreground">
              <Loader2 className="h-3 w-3 animate-spin" />
              loading
            </span>
          )}
          {adminDeals.usingDevFallback && (
            <span className="rounded-sm border border-border bg-transparent px-1.5 py-0.5 font-mono-ui text-[0.58rem] uppercase tracking-wider text-warning">
              dev-fallback
            </span>
          )}
          {adminDeals.error && (
            <span className="truncate text-[0.72rem] text-warning">{adminDeals.error}</span>
          )}
        </div>
        <div className="flex items-center gap-2">
          <Button size="sm" onClick={() => setShowNewDeal(true)}>
            <Plus className="h-3.5 w-3.5" />
            New deal
          </Button>
          <Button variant="outline" size="sm" onClick={() => void adminDeals.refresh()} disabled={adminDeals.loading}>
            <RefreshCw className={cn("h-3.5 w-3.5", adminDeals.loading && "animate-spin")} />
            Refresh
          </Button>
        </div>
      </div>
      <AdminTop25Strip
        cards={cards}
        devFallback={adminDeals.usingDevFallback}
        onCardSelect={setSelectedCardId}
        onCardDragStart={handleCardDragStart}
      />
      {!adminDeals.loading && !adminDeals.error && cards.length === 0 && (
        <p className="px-1 py-1 text-xs text-muted-foreground/80">
          No saved transaction files yet — use New deal above, or push a qualified profile from Leads.
        </p>
      )}
      <div role="tablist" aria-label="Deal side" className="flex items-center gap-1 border-b border-border">
        {(["listing", "buyer"] as AdminSide[]).map((side) => {
          const active = activeSide === side;
          const Icon = side === "listing" ? Home : Users;
          return (
            <button
              key={side}
              type="button"
              role="tab"
              aria-selected={active}
              onClick={() => setActiveSide(side)}
              className={cn(
                "-mb-px inline-flex min-h-11 items-center gap-2 border-b-2 px-3 py-2 text-[0.86rem] font-medium transition-colors focus:outline-none focus-visible:ring-1 focus-visible:ring-ring",
                active
                  ? "border-primary text-foreground"
                  : "border-transparent text-muted-foreground hover:text-foreground",
              )}
            >
              <Icon className={cn("h-4 w-4", active ? "text-primary" : "text-muted-foreground")} />
              <span>{ADMIN_SIDE_LABELS[side].title}</span>
              <span
                className={cn(
                  "font-mono-ui text-[0.65rem] uppercase tracking-wider",
                  active ? "text-primary" : "text-muted-foreground",
                )}
              >
                {buckets.counts[side]}
              </span>
            </button>
          );
        })}
      </div>
      <AdminKanbanSwimlane
        side={activeSide}
        title={ADMIN_SIDE_LABELS[activeSide].title}
        description={ADMIN_SIDE_LABELS[activeSide].description}
        cardsByStage={buckets.byStage[activeSide]}
        totalCount={buckets.counts[activeSide]}
        onCardSelect={setSelectedCardId}
        onCardDragStart={handleCardDragStart}
        onCardDrop={handleCardDrop}
      />
      {selectedCard && (
        <AdminCardDetailPanel
          card={selectedCard}
          onClose={closeDetailPanel}
          onToggleItem={(_stage, itemId, completed) => handleToggleItem(selectedCard.id, itemId, completed)}
          onConditionChange={(field, value) => handleConditionChange(selectedCard.id, field, value)}
          onMoveToNext={() => handleMoveToNext(selectedCard.id)}
          onDealUpdated={(deal) => adminDeals.replaceLocalDeal(selectedCard.id, deal)}
        />
      )}
      {showNewDeal && (
        <NewDealDialog onClose={() => setShowNewDeal(false)} onCreated={handleCreateDeal} />
      )}
    </div>
  );
}

export function RealEstateAdminPage() {
  const data = useRealEstateHubData();
  const adminSetup = useAdminSetup();
  const [forceOnboarding, setForceOnboarding] = useState(false);
  const [coachOpen, setCoachOpen] = useState(false);
  const [coachMention, setCoachMention] = useState<string | null>(null);
  const [coachMessages, setCoachMessages] = useState<CoachMessage[]>([]);
  const openCoach = useCallback(() => setCoachOpen(true), []);
  const initialCoachQuestion = useMemo(() => {
    const snap = adminSetup.setup;
    if (!snap) return "Loading your setup snapshot — one sec.";
    const province = (snap.profile?.province || "").toUpperCase();
    const pct = snap.completionPct ?? 0;
    const itemByKey = new Map(snap.items.map((item) => [item.key, item]));
    const missingKeys = new Set(snap.missingRequiredKeys ?? []);

    const connectedBits: string[] = [];
    const needsVerificationBits: string[] = [];
    for (const item of snap.items) {
      const isReadyStatus = item.status === "connected" || item.status === "configured";
      if (!isReadyStatus) continue;
      const provider = (item.provider || "").trim();
      const label = provider ? `${item.label} (${provider})` : item.label;
      if (missingKeys.has(item.key)) {
        needsVerificationBits.push(label);
      } else {
        connectedBits.push(label);
      }
    }

    const notPicked: string[] = [];
    for (const key of missingKeys) {
      const item = itemByKey.get(key);
      if (!item) continue;
      const isReadyStatus = item.status === "connected" || item.status === "configured";
      if (isReadyStatus) continue;
      notPicked.push(item.label);
    }

    const lines: string[] = [];
    const provinceBit = province ? `${province}, ` : "";
    lines.push(`${provinceBit}${pct}% wired up. Here's where we're at:`);
    if (connectedBits.length > 0) {
      lines.push(`Connected and verified — ${connectedBits.join(", ")}.`);
    }
    if (needsVerificationBits.length > 0) {
      lines.push(
        `Provider set but health-check still pending — ${needsVerificationBits.join(", ")}. ` +
          `These count as missing until Elevate runs a verification ping; usually clears on its own once a sync runs.`,
      );
    }
    if (notPicked.length > 0) {
      const first = notPicked[0];
      lines.push(`Not picked yet — ${notPicked.join(", ")}.`);
      lines.push(`Want to knock out ${first} first?`);
    } else if (needsVerificationBits.length > 0) {
      lines.push(`Nothing left to pick — once the pending health-checks clear, you're 100%.`);
    } else {
      lines.push(`Everything required is in. Anything else you want to tighten up?`);
    }
    return lines.join("\n\n");
  }, [adminSetup.setup]);

  const resetCoach = useCallback(() => {
    setCoachMessages([{ role: "assistant", content: initialCoachQuestion }]);
    setCoachMention(null);
    setCoachOpen(true);
  }, [initialCoachQuestion]);
  useHubHeader("Admin", data);
  useEffect(() => {
    if (!adminSetup.setup?.complete) return;
    let cancelled = false;
    (async () => {
      try {
        const [cronDefaults, actionDefaults] = await Promise.all([
          api.ensureLaneCronJobs(DEFAULT_ADMIN_AUTOMATIONS),
          api.ensureDefaultAdminActions(),
        ]);
        const changedCronDefaults = cronDefaults.created.length + (cronDefaults.updated?.length ?? 0);
        const changedActionDefaults = actionDefaults.created.length + (actionDefaults.updated?.length ?? 0);
        if (!cancelled && (changedCronDefaults > 0 || changedActionDefaults > 0)) {
          await data.refresh();
        }
      } catch {
        // Best-effort defaults. Existing cron jobs still render, and the Cron
        // page/action registry can create these manually if the backend is unavailable.
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [adminSetup.setup?.complete, data.refresh]);
  const sessions = data.sessions.filter((session) =>
    sessionMatches(session, ADMIN_WORKFLOW_KEYWORDS),
  );
  const jobs = data.cronJobs.filter((job) =>
    jobMatches(job, ADMIN_WORKFLOW_KEYWORDS),
  );
  const activeSessions = sessions.filter((session) => session.is_active);
  const actions = [
    ...approvalCueActions(sessions, jobs, "Admin"),
    ...jobs
      .filter((job) => !jobMatches(job, APPROVAL_CUE_KEYWORDS))
      .slice(0, 5)
      .map((job) => jobAction(job, "Admin check", CalendarClock)),
    ...sessions
      .filter((session) => !sessionMatches(session, APPROVAL_CUE_KEYWORDS))
      .slice(0, 5)
      .map((session) => sessionAction(session, "Admin workflow", FileCheck2)),
  ];

  return (
    <HubShell
      data={data}
      eyebrow="Admin Desk"
      icon={BriefcaseBusiness}
      title="Admin"
    >
      <WorkflowStrip
        items={[
          {
            icon: Building2,
            label: "Admin sessions",
            value: sessions.length,
          },
          { icon: CalendarClock, label: "Nightly checks", value: jobs.length },
          {
            icon: FileCheck2,
            label: "Active workflows",
            value: activeSessions.length,
          },
          {
            icon: CheckCircle2,
            label: "Review gates",
            value: approvalCueCount(sessions, jobs),
          },
        ]}
      />
      {adminSetup.loading && (
        <div className="rounded-md border border-border bg-card px-4 py-5 text-[0.86rem] text-muted-foreground">
          <Loader2 className="mr-2 inline h-4 w-4 animate-spin" />
          Loading Admin setup
        </div>
      )}
      {adminSetup.error && (
        <div className="rounded-md border border-border bg-card px-4 py-3 text-[0.84rem] text-warning">
          {adminSetup.error}
        </div>
      )}
      {!adminSetup.loading && adminSetup.setup && (!adminSetup.setup.complete || forceOnboarding) && (
        <AdminSetupLaunch
          setup={adminSetup.setup}
          onSetupUpdated={adminSetup.setSetup}
          forceOnboarding={forceOnboarding}
          onForceOnboardingDone={() => setForceOnboarding(false)}
          openCoach={openCoach}
          setCoachMention={setCoachMention}
        />
      )}
      {!adminSetup.loading && adminSetup.setup && !adminSetup.setup.complete && (
        <TimedTasks jobs={jobs} empty="No admin/document schedules are installed yet." title="Admin automations" />
      )}
      {!adminSetup.loading && adminSetup.setup?.complete && !forceOnboarding && (
        <>
      <div className="flex flex-wrap items-center gap-2">
        <Link to="/admin/templates" className="inline-flex">
          <Button variant="outline" size="sm">
            <FileCheck2 className="h-3.5 w-3.5" />
            Templates
          </Button>
        </Link>
        <Button
          variant="outline"
          size="sm"
          onClick={() => setForceOnboarding(true)}
        >
          <Sparkles className="h-3.5 w-3.5" />
          Re-run onboarding
        </Button>
      </div>
      <AdminKanbanBoard />
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_24rem]">
        <ActionBoard
          actions={actions}
          title="Admin action board"
          empty="No admin actions are waiting yet. CMA, seller-update, listing contract, signing, and listing/deal sessions will appear here."
        />
        <TimedTasks jobs={jobs} empty="No admin/document schedules yet." title="Admin automations" />
      </div>
      <RecentSessions
        title="Admin work"
        sessions={sessions}
        empty="No admin-specific sessions found yet. CMA, seller updates, listing contract, signing packages, WebForms, and listing/deal cron work will land here."
      />
        </>
      )}
      {coachOpen ? (
        <AdminOnboardingCoach
          initialQuestion={initialCoachQuestion}
          onClose={() => setCoachOpen(false)}
          onReset={resetCoach}
          externalMention={coachMention}
          messages={coachMessages}
          setMessages={setCoachMessages}
        />
      ) : (
        <button
          type="button"
          onClick={openCoach}
          aria-label="Open onboarding coach"
          className="fixed bottom-6 right-6 z-[110] inline-flex items-center gap-2 rounded-full border border-border bg-card px-4 py-2 text-[12.5px] text-foreground shadow-md hover:border-primary"
        >
          <MessageCircle className="h-3.5 w-3.5 text-primary" />
          Ask the coach
        </button>
      )}
    </HubShell>
  );
}

```

---
## `src/pages/real-estate-hub/leads/onboarding.tsx`
```tsx
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";
import { Loader2, CheckCircle2, Circle, AlertTriangle, ExternalLink, Sparkles, Link as LinkIcon, Play, Copy, RefreshCw, Plus, Pencil, Trash2, X } from "lucide-react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "@/lib/api";
import type {
  AdminSetupItemStatus,
  LeadsSetupItem,
  LeadsSetupItemUpdate,
  LeadsSetupSnapshot,
  OutreachConnectorRef,
  OutreachTemplate,
  SourceConnectorStatus,
} from "@/lib/api-types";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import {
  playOnboardingChime,
  playOnboardingClick,
  playOnboardingSwell,
  playOnboardingWhoosh,
} from "@/lib/onboarding-sounds";

function errorMessage(err: unknown, fallback: string): string {
  if (err instanceof Error && err.message) return err.message;
  if (typeof err === "string" && err) return err;
  return fallback;
}

const DEFAULT_AUTO_REPLY_TEMPLATE =
  "Hey {{firstName}} — thanks for reaching out. What's the property address or area you're looking at?";

type LeadsSetupDraft = {
  metaMcpEndpoint: string;
  metaMcpToken: string;
  googleDeveloperToken: string;
  webhookUrl: string;
  webhookSecret: string;
  autoReplyEnabled: boolean;
  autoReplyTemplate: string;
  followUpCadenceDays: string;
};

function leadsDraftFromSnapshot(snapshot: LeadsSetupSnapshot): LeadsSetupDraft {
  const byKey = new Map(snapshot.items.map((item) => [item.key, item]));
  const metaVal = (byKey.get("meta_lead_ads")?.value ?? {}) as Record<string, unknown>;
  const googleVal = (byKey.get("google_lead_forms")?.value ?? {}) as Record<string, unknown>;
  const webhookVal = (byKey.get("website_form_webhook")?.value ?? {}) as Record<string, unknown>;
  const policyVal = (byKey.get("auto_reply_policy")?.value ?? {}) as Record<string, unknown>;
  return {
    metaMcpEndpoint: String(metaVal.mcpEndpoint ?? "https://mcp.pipeboard.co/meta-ads-mcp"),
    metaMcpToken: String(metaVal.mcpToken ?? ""),
    googleDeveloperToken: String(googleVal.developerToken ?? ""),
    webhookUrl: String(webhookVal.url ?? ""),
    webhookSecret: String(webhookVal.secret ?? ""),
    autoReplyEnabled: Boolean(policyVal.enabled ?? false),
    autoReplyTemplate: String(policyVal.initialMessageTemplate ?? DEFAULT_AUTO_REPLY_TEMPLATE),
    followUpCadenceDays: String(policyVal.followUpCadenceDays ?? "2"),
  };
}

function buildItemUpdates(draft: LeadsSetupDraft): LeadsSetupItemUpdate[] {
  // Meta: one Pipeboard token is enough — Pipeboard's MCP auto-discovers
  // ad accounts, pages, and lead forms.
  const metaReady = Boolean(draft.metaMcpEndpoint.trim() && draft.metaMcpToken.trim());
  // Google: developer token alone — the CLI auto-discovers customer ID
  // and campaign IDs via `google-ads-list-accessible-customers`.
  const googleReady = Boolean(draft.googleDeveloperToken.trim());
  const webhookReady = draft.webhookUrl.trim();
  const policyReady = Boolean(draft.autoReplyTemplate.trim()) || !draft.autoReplyEnabled;
  return [
    {
      key: "meta_lead_ads",
      status: (metaReady ? "configured" : "missing") as AdminSetupItemStatus,
      provider: metaReady ? "meta_ads_mcp" : null,
      value: {
        authMethod: "mcp",
        mcpEndpoint: draft.metaMcpEndpoint.trim(),
        mcpToken: draft.metaMcpToken,
      },
    },
    {
      key: "google_lead_forms",
      status: (googleReady ? "configured" : "missing") as AdminSetupItemStatus,
      provider: googleReady ? "google_ads" : null,
      value: {
        developerToken: draft.googleDeveloperToken,
      },
    },
    {
      key: "website_form_webhook",
      status: (webhookReady ? "configured" : "missing") as AdminSetupItemStatus,
      provider: webhookReady ? "webhook" : null,
      value: {
        url: draft.webhookUrl.trim(),
        secret: draft.webhookSecret,
      },
    },
    {
      key: "auto_reply_policy",
      status: (policyReady ? "configured" : "missing") as AdminSetupItemStatus,
      provider: draft.autoReplyEnabled ? "elevate" : "off",
      value: {
        enabled: draft.autoReplyEnabled,
        initialMessageTemplate: draft.autoReplyTemplate.trim(),
        followUpCadenceDays: Number(draft.followUpCadenceDays) || 2,
      },
    },
  ];
}

function StatusBadge({ status }: { status: AdminSetupItemStatus }) {
  if (status === "connected" || status === "configured") {
    return (
      <span className="inline-flex items-center gap-1 rounded-md bg-success/15 px-1.5 py-0.5 text-[10.5px] font-medium text-success">
        <CheckCircle2 className="h-3 w-3" /> Connected
      </span>
    );
  }
  if (status === "manual") {
    return (
      <span className="inline-flex items-center gap-1 rounded-md bg-muted px-1.5 py-0.5 text-[10.5px] font-medium text-muted-foreground">
        <CheckCircle2 className="h-3 w-3" /> Manual
      </span>
    );
  }
  if (status === "skipped") {
    return (
      <span className="inline-flex items-center gap-1 rounded-md bg-muted px-1.5 py-0.5 text-[10.5px] font-medium text-muted-foreground">
        Skipped
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 rounded-md border border-warning/40 bg-warning/10 px-1.5 py-0.5 text-[10.5px] font-medium text-warning">
      <Circle className="h-3 w-3" /> Missing
    </span>
  );
}

const OUTREACH_CONNECTOR_IDS = ["crm", "apple-messages", "sms-provider", "android-device", "rcs"] as const;

const LEADS_TEMPLATE_LANES: { id: string; label: string; hint: string }[] = [
  { id: "new-outreach", label: "First touch", hint: "lead just landed — pick the opener" },
  { id: "hot-leads-watcher", label: "Hot signals", hint: "live intent — open house, just-listed match, alert reply" },
  { id: "follow-ups", label: "Follow-ups", hint: "re-engagement, GIF nudge, market update, breakup, referral" },
];

function connectorStateLabel(state: SourceConnectorStatus["state"]): string {
  return state.replace(/_/g, " ");
}

function connectorStateClasses(state: SourceConnectorStatus["state"]): string {
  if (state === "connected" || state === "import_only") {
    return "bg-success/15 text-success";
  }
  if (state === "blocked" || state === "error" || state === "needs_operator") {
    return "border border-warning/40 bg-warning/10 text-warning";
  }
  return "border border-border/60 bg-muted/40 text-muted-foreground";
}

function connectorRecordTotal(connector: SourceConnectorStatus): number {
  return Object.values(connector.recordCounts).reduce((total, value) => total + value, 0);
}

function connectorSetupCopy(connector: SourceConnectorStatus): string {
  if (connector.initializeBehavior === "local_messages_import") {
    return connector.sourceExists
      ? "Live sync runs every 10 min via launchd. Click Re-import to force a full rebuild."
      : "Reads the synced Mac Messages database and builds a local Elevate message index for lead context.";
  }
  if (connector.initializeBehavior === "composio_social_setup") {
    return connector.sourceExists
      ? "Refreshes the local Composio social setup record and next operator step."
      : "Sets up Composio as the social account hub.";
  }
  return connector.sourceExists
    ? "Refreshes the local agent setup task and prompt for building the real connector."
    : "Creates a local setup task for the agent/operator to build the webhook, poller, import command, or bridge.";
}

function isBrandNewLeadsSetup(setup: LeadsSetupSnapshot): boolean {
  if (setup.completionPct && setup.completionPct > 0) return false;
  if (setup.complete) return false;
  for (const item of setup.items) {
    if (item.status && item.status !== "missing") return false;
    if (item.provider && item.provider.trim()) return false;
    const value = item.value as Record<string, unknown> | null | undefined;
    if (value && Object.values(value).some((v) => v != null && String(v).trim() !== "")) return false;
  }
  return true;
}

function LeadsOnboardingGate({ onStart, onSkip }: { onStart: () => void; onSkip: () => void }) {
  return (
    <section className="onboarding-overlay relative -mx-6 -my-6 flex min-h-[calc(100vh-9rem)] items-center justify-center overflow-hidden px-6 py-10">
      <div className="onboarding-aurora-bg pointer-events-none absolute inset-0" aria-hidden />
      <div className="relative flex max-w-md flex-col items-center text-center">
        <div className="onboarding-rise font-mono-ui text-[10px] uppercase tracking-[0.18em] text-muted-foreground">
          Leads · first run
        </div>
        <h1 className="onboarding-rise-delay-1 mt-3 text-[34px] font-medium leading-[1.05] tracking-tight text-foreground">
          Wire up Elevate Leads
        </h1>
        <p className="onboarding-rise-delay-2 mt-3 max-w-sm text-[13.5px] leading-6 text-muted-foreground">
          A short guided run sets your lead sources, outreach channels, and auto-reply policy. Two minutes, end-to-end.
        </p>
        <Button
          size="lg"
          onClick={onStart}
          className="onboarding-rise-delay-3 mt-7 h-12 min-w-[220px] px-6 text-[14px]"
        >
          <Sparkles className="h-4 w-4" />
          Run onboarding
        </Button>
        <button
          type="button"
          onClick={onSkip}
          className="onboarding-rise-delay-3 mt-4 text-[12px] text-muted-foreground underline-offset-2 hover:text-foreground hover:underline"
        >
          or skip to the full setup form
        </button>
      </div>
    </section>
  );
}

function LeadsOnboardingWelcome({ onContinue }: { onContinue: () => void }) {
  const [exiting, setExiting] = useState(false);

  useEffect(() => {
    playOnboardingSwell();
  }, []);

  const handleStart = useCallback(() => {
    playOnboardingWhoosh();
    playOnboardingSwell();
    setExiting(true);
  }, []);

  const handleAnimationEnd = useCallback(
    (event: React.AnimationEvent<HTMLDivElement>) => {
      if (event.target !== event.currentTarget) return;
      if (exiting) onContinue();
    },
    [exiting, onContinue],
  );

  return createPortal(
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Welcome to Elevate Leads"
      className={cn(
        "onboarding-overlay fixed inset-0 z-[100] flex items-center justify-center overflow-hidden",
        exiting && "onboarding-exit",
      )}
      onAnimationEnd={handleAnimationEnd}
    >
      <div className="onboarding-aurora-bg pointer-events-none absolute inset-0" aria-hidden />
      <div className="relative flex max-w-xl flex-col items-center px-6 text-center">
        <div className="onboarding-rise font-mono-ui text-[10px] uppercase tracking-[0.2em] text-muted-foreground">
          Elevate · Leads
        </div>
        <h1 className="onboarding-rise-delay-1 mt-4 text-[52px] font-medium leading-[1.02] tracking-tight text-foreground">
          Welcome to Elevate Leads.
        </h1>
        <p className="onboarding-rise-delay-2 mt-4 max-w-lg text-[15px] leading-7 text-muted-foreground">
          A few quick questions and Leads starts catching, routing, and drafting replies the moment a lead lands.
        </p>
        <Button
          size="lg"
          onClick={handleStart}
          disabled={exiting}
          className="onboarding-rise-delay-3 mt-9 h-12 min-w-[240px] px-7 text-[14px]"
        >
          Let's get started
        </Button>
      </div>
    </div>,
    document.body,
  );
}

type LeadsWizardStepId = "meta" | "google" | "webhook" | "outreach" | "policy";

type LeadsWizardStep = {
  id: LeadsWizardStepId;
  eyebrow: string;
  title: string;
  subtitle: string;
};

const LEADS_WIZARD_STEPS: LeadsWizardStep[] = [
  {
    id: "meta",
    eyebrow: "Step 1 of 5",
    title: "Meta Lead Ads",
    subtitle:
      "Skip if you don't run Facebook / Instagram lead-form ads. Pipeboard MCP wraps Meta's Marketing API — one token, no Facebook App registration.",
  },
  {
    id: "google",
    eyebrow: "Step 2 of 5",
    title: "Google Lead Forms",
    subtitle:
      "Skip if you don't run Google Ads. One developer token is enough — Elevate's CLI auto-discovers your customer ID and campaigns.",
  },
  {
    id: "webhook",
    eyebrow: "Step 3 of 5",
    title: "Website form webhook",
    subtitle:
      "Optional catch-all POST endpoint for landing-page and contact-us forms. Wire any form provider that can POST JSON.",
  },
  {
    id: "policy",
    eyebrow: "Step 4 of 5",
    title: "Auto-reply policy",
    subtitle:
      "Tell Elevate how aggressive to be on the first touch. You can change the cadence per lane after onboarding.",
  },
  {
    id: "outreach",
    eyebrow: "Step 5 of 5",
    title: "CRM + outreach channels",
    subtitle:
      "CRM (Lofty / FUB), iMessage, SMS, and RCS live as Source Connectors. \"Run prompt\" opens a chat seeded with that connector's setup — finish onboarding first, then run these one by one.",
  },
];

function LeadsOnboardingWizard({
  draft,
  updateField,
  onAdvanceSave,
  onFinish,
  saving,
  completing,
  error,
  savedMessage,
  outreachSourceConnectors,
  refreshSourceConnectors,
  sourceConnectorsLoading,
  firstTouchTemplates,
  refreshTemplates,
}: {
  draft: LeadsSetupDraft;
  updateField: <K extends keyof LeadsSetupDraft>(key: K, value: LeadsSetupDraft[K]) => void;
  onAdvanceSave: () => Promise<void>;
  onFinish: () => Promise<void>;
  saving: boolean;
  completing: boolean;
  error: string | null;
  savedMessage: string | null;
  outreachSourceConnectors: SourceConnectorStatus[];
  refreshSourceConnectors: () => Promise<void>;
  sourceConnectorsLoading: boolean;
  firstTouchTemplates: OutreachTemplate[];
  refreshTemplates: () => Promise<void>;
}) {
  const navigate = useNavigate();
  const [runningPromptId, setRunningPromptId] = useState<string | null>(null);

  const promptForConnector = useCallback(async (connector: SourceConnectorStatus) => {
    const existing = (connector.prompt || "").trim();
    if (existing) return existing;
    const resp = await api.getSourceConnectorPrompt(connector.id);
    return (resp.prompt || "").trim();
  }, []);

  const runPrompt = useCallback(
    async (connector: SourceConnectorStatus) => {
      setRunningPromptId(connector.id);
      try {
        const prompt = await promptForConnector(connector);
        if (!prompt) return;
        const ts = String(Date.now());
        const seedText = `Source connector: ${connector.label} (${connector.id})\n\n${prompt}`;
        try {
          window.sessionStorage.setItem(`elevate:chat-seed:${ts}`, seedText);
        } catch {
          // sessionStorage disabled — navigate anyway, user can paste manually.
        }
        navigate(`/chat?new=${ts}&seed=${ts}`);
      } finally {
        setRunningPromptId(null);
      }
    },
    [navigate, promptForConnector],
  );

  const copyPrompt = useCallback(async (connector: SourceConnectorStatus) => {
    try {
      await navigator.clipboard.writeText(await promptForConnector(connector));
    } catch {
      // clipboard unavailable — silent fail
    }
  }, [promptForConnector]);

  type TemplateEditor =
    | { mode: "create"; lane: string; name: string; body: string }
    | { mode: "edit"; id: string; lane: string; name: string; body: string };
  const [templateEditor, setTemplateEditor] = useState<TemplateEditor | null>(null);
  const [templateMutating, setTemplateMutating] = useState(false);
  const [templateError, setTemplateError] = useState<string | null>(null);

  const openCreateTemplate = useCallback((lane: string) => {
    setTemplateError(null);
    setTemplateEditor({ mode: "create", lane, name: "", body: "" });
  }, []);

  const openEditTemplate = useCallback((tpl: OutreachTemplate) => {
    setTemplateError(null);
    setTemplateEditor({ mode: "edit", id: tpl.id, lane: tpl.lane, name: tpl.name, body: tpl.body });
  }, []);

  const closeTemplateEditor = useCallback(() => {
    setTemplateEditor(null);
    setTemplateError(null);
  }, []);

  const saveTemplate = useCallback(async () => {
    if (!templateEditor) return;
    const name = templateEditor.name.trim();
    const body = templateEditor.body.trim();
    if (!name || !body) {
      setTemplateError("Name and body are both required.");
      return;
    }
    setTemplateMutating(true);
    setTemplateError(null);
    try {
      if (templateEditor.mode === "create") {
        await api.createOutreachTemplate({ lane: templateEditor.lane, name, body });
      } else {
        await api.updateOutreachTemplate(templateEditor.id, { name, body });
      }
      await refreshTemplates();
      setTemplateEditor(null);
    } catch (err) {
      setTemplateError(errorMessage(err, "Could not save template."));
    } finally {
      setTemplateMutating(false);
    }
  }, [templateEditor, refreshTemplates]);

  const deleteTemplate = useCallback(
    async (tpl: OutreachTemplate) => {
      if (!window.confirm(`Delete "${tpl.name}"? This can't be undone from the wizard.`)) return;
      setTemplateMutating(true);
      setTemplateError(null);
      try {
        await api.deleteOutreachTemplate(tpl.id);
        await refreshTemplates();
      } catch (err) {
        setTemplateError(errorMessage(err, "Could not delete template."));
      } finally {
        setTemplateMutating(false);
      }
    },
    [refreshTemplates],
  );

  const [stepIdx, setStepIdx] = useState(0);
  const [showMissing, setShowMissing] = useState(false);
  const step = LEADS_WIZARD_STEPS[stepIdx];
  const isLast = stepIdx === LEADS_WIZARD_STEPS.length - 1;
  const isFirst = stepIdx === 0;
  const busy = saving || completing;

  const missingMessage = useMemo(() => {
    if (step.id !== "policy") return null;
    if (draft.autoReplyEnabled && !draft.autoReplyTemplate.trim()) {
      return 'Fill in "Initial reply template" before continuing — or turn auto-reply off.';
    }
    return null;
  }, [step.id, draft.autoReplyEnabled, draft.autoReplyTemplate]);
  const canAdvance = missingMessage == null;
  useEffect(() => {
    setShowMissing(false);
  }, [stepIdx]);

  const handleNext = useCallback(async () => {
    if (busy) return;
    if (!canAdvance) {
      setShowMissing(true);
      return;
    }
    playOnboardingClick();
    await onAdvanceSave();
    if (isLast) {
      playOnboardingSwell();
      await onFinish();
      return;
    }
    setStepIdx((idx) => Math.min(idx + 1, LEADS_WIZARD_STEPS.length - 1));
  }, [busy, canAdvance, isLast, onAdvanceSave, onFinish]);

  const handleBack = useCallback(() => {
    if (busy) return;
    playOnboardingClick();
    setStepIdx((idx) => Math.max(idx - 1, 0));
  }, [busy]);

  return createPortal(
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Leads onboarding wizard"
      className="onboarding-overlay fixed inset-0 z-[100] overflow-y-auto"
    >
      <div className="onboarding-aurora-bg pointer-events-none fixed inset-0" aria-hidden />
      <div className="relative flex min-h-full items-center justify-center px-6 py-10">
       <div className="relative flex w-full max-w-3xl flex-col">
        <div className="mb-7 flex items-center gap-1.5">
          {LEADS_WIZARD_STEPS.map((s, idx) => (
            <span
              key={s.id}
              aria-hidden
              className={cn(
                "h-1 flex-1 rounded-sm transition-colors duration-300",
                idx <= stepIdx ? "bg-primary" : "bg-border/60",
              )}
            />
          ))}
        </div>

        <div key={stepIdx} className="flex flex-col">
          <div className="onboarding-rise font-mono-ui text-[10px] uppercase tracking-[0.2em] text-muted-foreground">
            {step.eyebrow}
          </div>
          <h2 className="onboarding-rise-delay-1 mt-3 text-[34px] font-medium leading-[1.05] tracking-tight text-foreground">
            {step.title}
          </h2>
          <p className="onboarding-rise-delay-2 mt-3 max-w-xl text-[14px] leading-7 text-muted-foreground">
            {step.subtitle}
          </p>

          <div className="onboarding-rise-delay-3 mt-8 flex flex-col gap-4">
            {step.id === "meta" && (
              <>
                <div className="grid gap-4 md:grid-cols-2">
                  <WizardField
                    label="MCP endpoint URL"
                    value={draft.metaMcpEndpoint}
                    onChange={(v) => updateField("metaMcpEndpoint", v)}
                    placeholder="https://mcp.pipeboard.co/meta-ads-mcp"
                    fullWidth
                    helper="Pre-filled with Pipeboard's hosted MCP. They handle the Facebook OAuth + Marketing API plumbing — you just paste a token."
                  />
                  <WizardField
                    label="Pipeboard API token"
                    value={draft.metaMcpToken}
                    onChange={(v) => updateField("metaMcpToken", v)}
                    placeholder="••••••••"
                    type="password"
                    fullWidth
                    helper={
                      <>
                        Get one at{" "}
                        <a
                          href="https://pipeboard.co/api-tokens"
                          target="_blank"
                          rel="noreferrer noopener"
                          className="text-primary underline-offset-2 hover:underline"
                        >
                          pipeboard.co/api-tokens
                        </a>{" "}
                        (OAuth Facebook there once, copy token back). Ad accounts, pages, and lead forms are auto-discovered.
                      </>
                    }
                  />
                </div>
                <p className="text-[11.5px] text-muted-foreground/80">
                  Optional — skip Meta entirely if you don't run Facebook / Instagram lead-form ads.
                </p>
              </>
            )}

            {step.id === "google" && (
              <div className="grid gap-4 md:grid-cols-2">
                <WizardField
                  label="Developer token"
                  value={draft.googleDeveloperToken}
                  onChange={(v) => updateField("googleDeveloperToken", v)}
                  placeholder="abcDEF123-xyz"
                  type="password"
                  fullWidth
                  helper={
                    <>
                      Generate one at{" "}
                      <a
                        href="https://developers.google.com/google-ads/api/docs/get-started/dev-token"
                        target="_blank"
                        rel="noreferrer noopener"
                        className="text-primary underline-offset-2 hover:underline"
                      >
                        Google Ads → Tools → API Center
                      </a>
                      . The CLI auto-discovers your customer ID and campaign IDs from this token.
                    </>
                  }
                />
                <p className="md:col-span-2 text-[11.5px] text-muted-foreground/80">
                  Optional — skip Google entirely if you don't run Google Ads lead-form extensions.
                </p>
              </div>
            )}

            {step.id === "webhook" && (
              <div className="grid gap-4 md:grid-cols-2">
                <WizardField
                  label="Webhook URL"
                  value={draft.webhookUrl}
                  onChange={(v) => updateField("webhookUrl", v)}
                  placeholder="https://elevate.yourdomain.com/api/leads/inbound"
                  fullWidth
                  helper="POST endpoint your form provider (Webflow, Framer, custom) hits when someone submits."
                />
                <WizardField
                  label="Shared secret"
                  value={draft.webhookSecret}
                  onChange={(v) => updateField("webhookSecret", v)}
                  placeholder="optional"
                  type="password"
                  fullWidth
                  helper="Optional. If set, Elevate verifies HMAC signature on each incoming submission."
                />
              </div>
            )}

            {step.id === "outreach" && (
              <div className="flex flex-col gap-3">
                <div className="flex flex-wrap items-center gap-2">
                  <Link
                    to="/config#connectors"
                    className="inline-flex items-center gap-1 rounded-md border border-border bg-card/60 px-3 py-1.5 text-[12.5px] font-medium text-foreground backdrop-blur-sm hover:bg-muted"
                  >
                    <LinkIcon className="h-3.5 w-3.5" />
                    Open Source Connectors
                  </Link>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => void refreshSourceConnectors()}
                    disabled={sourceConnectorsLoading}
                    className="h-8 gap-1 px-2 text-[11.5px]"
                  >
                    <RefreshCw className={cn("h-3.5 w-3.5", sourceConnectorsLoading && "animate-spin")} />
                    Refresh
                  </Button>
                </div>

                <ul className="divide-y divide-border/40 overflow-hidden rounded-md border border-border/60 bg-card/40 backdrop-blur-sm">
                  {outreachSourceConnectors.length === 0 && !sourceConnectorsLoading && (
                    <li className="px-3 py-4 text-[12px] text-muted-foreground">
                      No outreach connectors found. Check that your install seeded `data/sources/`.
                    </li>
                  )}
                  {outreachSourceConnectors.length === 0 && sourceConnectorsLoading && (
                    <li className="px-3 py-4 text-[12px] text-muted-foreground">Loading connector blueprints…</li>
                  )}
                  {outreachSourceConnectors.map((connector) => {
                    const total = connectorRecordTotal(connector);
                    const hint = OUTREACH_HINTS[connector.id as OutreachConnectorRef["id"]];
                    const setupCopy = connectorSetupCopy(connector);
                    return (
                      <li key={connector.id} className="px-3 py-3">
                        <div className="flex flex-wrap items-start justify-between gap-2">
                          <div className="min-w-0">
                            <div className="flex flex-wrap items-center gap-2">
                              <span className="text-[13px] font-semibold text-foreground">{connector.label}</span>
                              <span
                                className={cn(
                                  "inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[10.5px] font-medium",
                                  connectorStateClasses(connector.state),
                                )}
                              >
                                {connector.state === "connected" || connector.state === "import_only" ? (
                                  <CheckCircle2 className="h-3 w-3" />
                                ) : connector.state === "blocked" || connector.state === "error" ? (
                                  <AlertTriangle className="h-3 w-3" />
                                ) : (
                                  <Circle className="h-3 w-3" />
                                )}
                                {connectorStateLabel(connector.state)}
                              </span>
                              {total > 0 && (
                                <span className="text-[10.5px] text-muted-foreground">
                                  {total.toLocaleString()} records
                                </span>
                              )}
                            </div>
                            <p className="mt-1 text-[11.5px] leading-5 text-muted-foreground">
                              {hint?.tagline || setupCopy}
                            </p>
                            {connector.nextOperatorStep && (
                              <p className="mt-1.5 text-[11px] leading-5 text-muted-foreground/80">
                                Next: {connector.nextOperatorStep}
                              </p>
                            )}
                            {connector.lastError && (
                              <p className="mt-1.5 text-[11px] leading-5 text-destructive/80">
                                {connector.lastError}
                              </p>
                            )}
                          </div>
                        </div>
                        <div className="mt-2 flex flex-wrap items-center gap-1.5">
                          <span className="inline-flex items-center gap-1 rounded-md border border-border/60 px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-muted-foreground">
                            {connector.ownerAgent}
                          </span>
                          {connector.connectionType && (
                            <span className="inline-flex items-center gap-1 rounded-md border border-border/60 px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-muted-foreground">
                              {connector.connectionType}
                            </span>
                          )}
                          <Button
                            size="sm"
                            variant="default"
                            className="ml-auto h-7 gap-1 px-2 text-[11.5px]"
                            disabled={runningPromptId === connector.id}
                            onClick={() => void runPrompt(connector)}
                            aria-label={`Run setup prompt for ${connector.label}`}
                          >
                            <Play className="h-3 w-3" />
                            {runningPromptId === connector.id ? "Opening chat…" : "Run prompt"}
                          </Button>
                          <Button
                            size="sm"
                            variant="ghost"
                            className="h-7 px-2"
                            onClick={() => void copyPrompt(connector)}
                            aria-label={`Copy setup prompt for ${connector.label}`}
                            title="Copy prompt text"
                          >
                            <Copy className="h-3 w-3" />
                          </Button>
                        </div>
                      </li>
                    );
                  })}
                </ul>

                <p className="text-[11.5px] text-muted-foreground/80">
                  Run prompt opens a chat seeded with the connector's setup prompt — same flow as Config → Source connectors.
                  Elevate auto-routes by lead device: iPhone → iMessage, Android → SMS / RCS.
                </p>
              </div>
            )}

            {step.id === "policy" && (
              <div className="flex flex-col gap-4">
                <label className="flex items-start gap-3 rounded-md border border-border bg-card/60 px-4 py-3 backdrop-blur-sm">
                  <input
                    type="checkbox"
                    checked={draft.autoReplyEnabled}
                    onChange={(e) => updateField("autoReplyEnabled", e.target.checked)}
                    className="mt-0.5 h-3.5 w-3.5 rounded border-border accent-primary"
                  />
                  <div className="min-w-0">
                    <div className="text-[13px] font-medium text-foreground">
                      Send an automated first reply when a lead lands
                    </div>
                    <p className="mt-0.5 text-[11.5px] text-muted-foreground">
                      Off by default — Elevate drafts and queues a reply for your approval instead.
                    </p>
                  </div>
                </label>
                <div className="flex flex-col gap-4">
                  <div className="flex items-baseline justify-between gap-2">
                    <div className="flex flex-col gap-0.5">
                      <span className="text-[12.5px] font-medium text-foreground">
                        Template library
                      </span>
                      <span className="text-[11px] leading-[1.4] text-muted-foreground">
                        Elevate picks per situation — best-fit template is auto-attached by ID and tracked for reply rate. Click any card to pin it as the default first-touch.
                      </span>
                    </div>
                    <Link
                      to="/real-estate/templates"
                      className="shrink-0 text-[11px] text-muted-foreground underline-offset-2 hover:text-foreground hover:underline"
                    >
                      Manage all
                    </Link>
                  </div>
                  {templateError && (
                    <div className="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-1.5 text-[11.5px] text-destructive">
                      {templateError}
                    </div>
                  )}
                  {LEADS_TEMPLATE_LANES.map((lane) => {
                    const laneTemplates = firstTouchTemplates.filter((t) => t.lane === lane.id);
                    const editingThisLane =
                      templateEditor && templateEditor.lane === lane.id ? templateEditor : null;
                    return (
                      <div key={lane.id} className="flex flex-col gap-2">
                        <div className="flex items-baseline justify-between gap-2">
                          <div className="flex items-baseline gap-2">
                            <span className="font-mono-ui text-[10px] uppercase tracking-[0.12em] text-muted-foreground">
                              {lane.label}
                            </span>
                            <span className="text-[10.5px] text-muted-foreground/70">
                              {laneTemplates.length} · {lane.hint}
                            </span>
                          </div>
                          <button
                            type="button"
                            onClick={() => openCreateTemplate(lane.id)}
                            className="inline-flex items-center gap-1 rounded-sm px-1.5 py-0.5 font-mono-ui text-[10px] uppercase tracking-wide text-muted-foreground transition hover:bg-muted hover:text-foreground"
                            disabled={templateMutating}
                          >
                            <Plus className="h-3 w-3" />
                            Add
                          </button>
                        </div>
                        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                          {laneTemplates.map((tpl) => {
                            const isActive = draft.autoReplyTemplate.trim() === tpl.body.trim();
                            const hasGif = /\[\[gif:/i.test(tpl.body);
                            const isEditingThis =
                              editingThisLane?.mode === "edit" && editingThisLane.id === tpl.id;
                            if (isEditingThis) {
                              return (
                                <TemplateEditorCard
                                  key={tpl.id}
                                  editor={editingThisLane}
                                  onChange={(patch) =>
                                    setTemplateEditor((prev) => (prev ? { ...prev, ...patch } : prev))
                                  }
                                  onSave={saveTemplate}
                                  onCancel={closeTemplateEditor}
                                  busy={templateMutating}
                                />
                              );
                            }
                            return (
                              <div
                                key={tpl.id}
                                className={cn(
                                  "group relative flex flex-col gap-1 rounded-md border px-3 py-2.5 text-left backdrop-blur-sm transition",
                                  isActive
                                    ? "border-primary/60 bg-primary/10"
                                    : "border-border bg-card/60 hover:border-border/80 hover:bg-card",
                                )}
                              >
                                <button
                                  type="button"
                                  onClick={() => updateField("autoReplyTemplate", tpl.body)}
                                  className="flex flex-col gap-1 text-left"
                                >
                                  <div className="flex items-center justify-between gap-2 pr-12">
                                    <span className="text-[12.5px] font-medium text-foreground">{tpl.name}</span>
                                    <div className="flex items-center gap-1.5">
                                      {hasGif && (
                                        <span className="inline-flex items-center rounded-sm border border-border/70 bg-muted/50 px-1.5 py-px font-mono-ui text-[9px] uppercase tracking-wide text-muted-foreground">
                                          GIF
                                        </span>
                                      )}
                                      {isActive && <CheckCircle2 className="h-3.5 w-3.5 text-primary" />}
                                    </div>
                                  </div>
                                  <span className="line-clamp-2 text-[11.5px] leading-[1.4] text-muted-foreground">
                                    {tpl.body}
                                  </span>
                                  <span className="mt-0.5 font-mono-ui text-[9.5px] tracking-wide text-muted-foreground/60">
                                    id · {tpl.id.slice(0, 8)}
                                  </span>
                                </button>
                                <div className="absolute right-2 top-2 flex items-center gap-1 opacity-0 transition group-hover:opacity-100">
                                  <button
                                    type="button"
                                    onClick={(e) => {
                                      e.stopPropagation();
                                      openEditTemplate(tpl);
                                    }}
                                    className="rounded-sm p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
                                    title="Rename or edit body"
                                    disabled={templateMutating}
                                  >
                                    <Pencil className="h-3 w-3" />
                                  </button>
                                  <button
                                    type="button"
                                    onClick={(e) => {
                                      e.stopPropagation();
                                      void deleteTemplate(tpl);
                                    }}
                                    className="rounded-sm p-1 text-muted-foreground hover:bg-destructive/20 hover:text-destructive"
                                    title="Delete template"
                                    disabled={templateMutating}
                                  >
                                    <Trash2 className="h-3 w-3" />
                                  </button>
                                </div>
                              </div>
                            );
                          })}
                          {editingThisLane?.mode === "create" && (
                            <TemplateEditorCard
                              editor={editingThisLane}
                              onChange={(patch) =>
                                setTemplateEditor((prev) => (prev ? { ...prev, ...patch } : prev))
                              }
                              onSave={saveTemplate}
                              onCancel={closeTemplateEditor}
                              busy={templateMutating}
                            />
                          )}
                          {laneTemplates.length === 0 && editingThisLane?.mode !== "create" && (
                            <button
                              type="button"
                              onClick={() => openCreateTemplate(lane.id)}
                              className="flex flex-col items-center justify-center gap-1 rounded-md border border-dashed border-border/70 px-3 py-4 text-[11.5px] text-muted-foreground hover:border-border hover:text-foreground"
                              disabled={templateMutating}
                            >
                              <Plus className="h-3.5 w-3.5" />
                              Add the first {lane.label.toLowerCase()} template
                            </button>
                          )}
                        </div>
                      </div>
                    );
                  })}
                </div>
                <label className="block">
                  <span className="mb-1.5 block text-[12px] font-medium text-muted-foreground">
                    Initial reply template {draft.autoReplyEnabled && <span className="text-destructive">*</span>}
                  </span>
                  <textarea
                    value={draft.autoReplyTemplate}
                    onChange={(e) => updateField("autoReplyTemplate", e.target.value)}
                    rows={4}
                    placeholder="Hey {{firstName}} — thanks for reaching out. What's the property address or area you're looking at?"
                    className="min-h-28 w-full resize-y rounded-md border border-border bg-card/60 px-3 py-2 text-[13px] leading-5 text-foreground outline-none backdrop-blur-sm placeholder:text-muted-foreground/60 focus:border-primary focus:ring-1 focus:ring-primary/30"
                  />
                  <span className="mt-1.5 block text-[11.5px] leading-5 text-muted-foreground/80">
                    {firstTouchTemplates.length > 0
                      ? "Pick one above to load it here — edit freely. Used both as the auto-send template (if enabled) and the default draft otherwise."
                      : "Used both as the auto-send template (if enabled) and the default draft otherwise."}
                  </span>
                </label>
                <WizardField
                  label="Follow-up cadence (days between nudges)"
                  value={draft.followUpCadenceDays}
                  onChange={(v) => updateField("followUpCadenceDays", v)}
                  placeholder="2"
                  type="number"
                />
              </div>
            )}
          </div>
        </div>

        {(error || savedMessage) && (
          <div
            className={cn(
              "mt-6 flex items-baseline gap-3 border-t py-3 text-[13px]",
              error ? "border-destructive" : "border-success",
            )}
          >
            <span
              className={cn(
                "shrink-0 font-mono-ui text-[10px] uppercase tracking-wider",
                error ? "text-destructive" : "text-success",
              )}
            >
              {error ? "Error" : "Saved"}
            </span>
            <span className="text-foreground">{error || savedMessage}</span>
          </div>
        )}

        <div className="mt-9 flex items-center justify-between gap-3 border-t border-border/60 pt-5">
          <div className="min-h-[18px] flex-1 text-[12px] leading-5 text-muted-foreground/80">
            {showMissing && missingMessage && <span className="text-destructive">{missingMessage}</span>}
          </div>
          <div className="flex shrink-0 items-center gap-2">
            <Button variant="outline" onClick={handleBack} disabled={busy || isFirst}>
              Back
            </Button>
            <Button
              onClick={() => void handleNext()}
              disabled={busy || !canAdvance}
              className="min-w-[140px]"
            >
              {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
              {isLast ? "Finish setup" : "Continue"}
            </Button>
          </div>
        </div>
       </div>
      </div>
    </div>,
    document.body,
  );
}

type TemplateEditorState =
  | { mode: "create"; lane: string; name: string; body: string }
  | { mode: "edit"; id: string; lane: string; name: string; body: string };

function TemplateEditorCard({
  editor,
  onChange,
  onSave,
  onCancel,
  busy,
}: {
  editor: TemplateEditorState;
  onChange: (patch: Partial<{ name: string; body: string }>) => void;
  onSave: () => void;
  onCancel: () => void;
  busy: boolean;
}) {
  return (
    <div className="flex flex-col gap-2 rounded-md border border-primary/40 bg-card/70 px-3 py-2.5 backdrop-blur-sm sm:col-span-2">
      <div className="flex items-center justify-between gap-2">
        <span className="font-mono-ui text-[10px] uppercase tracking-[0.12em] text-muted-foreground">
          {editor.mode === "create" ? "New template" : "Edit template"}
        </span>
        <button
          type="button"
          onClick={onCancel}
          className="rounded-sm p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
          disabled={busy}
        >
          <X className="h-3 w-3" />
        </button>
      </div>
      <input
        type="text"
        value={editor.name}
        onChange={(e) => onChange({ name: e.target.value })}
        placeholder="Template name (e.g. Open house live)"
        className="w-full rounded-md border border-border bg-background/40 px-3 py-1.5 text-[12.5px] text-foreground outline-none focus:border-primary focus:ring-1 focus:ring-primary/30"
        disabled={busy}
      />
      <textarea
        value={editor.body}
        onChange={(e) => onChange({ body: e.target.value })}
        rows={4}
        placeholder="Body. Use {first_name}, {area}, {topic}, etc. Add [[gif:keyword]] to attach a GIF."
        className="min-h-24 w-full resize-y rounded-md border border-border bg-background/40 px-3 py-2 text-[12.5px] leading-5 text-foreground outline-none placeholder:text-muted-foreground/60 focus:border-primary focus:ring-1 focus:ring-primary/30"
        disabled={busy}
      />
      <div className="flex items-center justify-end gap-2">
        <button
          type="button"
          onClick={onCancel}
          className="rounded-md px-2 py-1 text-[11.5px] text-muted-foreground hover:text-foreground"
          disabled={busy}
        >
          Cancel
        </button>
        <Button size="sm" onClick={onSave} disabled={busy} className="h-7 px-3 text-[11.5px]">
          {busy ? <Loader2 className="h-3 w-3 animate-spin" /> : null}
          {editor.mode === "create" ? "Add template" : "Save changes"}
        </Button>
      </div>
    </div>
  );
}

function WizardField({
  label,
  value,
  onChange,
  placeholder,
  type = "text",
  fullWidth = false,
  helper,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  type?: string;
  fullWidth?: boolean;
  helper?: React.ReactNode;
}) {
  return (
    <label className={cn("block min-w-0", fullWidth && "md:col-span-2")}>
      <span className="mb-1.5 block text-[12px] font-medium text-muted-foreground">{label}</span>
      <input
        type={type}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        autoComplete={type === "password" ? "new-password" : "off"}
        spellCheck={type === "password" || type === "email" ? false : undefined}
        className="h-9 w-full rounded-md border border-border bg-card/60 px-3 text-[13px] text-foreground outline-none backdrop-blur-sm transition-colors placeholder:text-muted-foreground/50 focus:border-primary focus:ring-1 focus:ring-primary/30"
      />
      {helper && (
        <span className="mt-1.5 block text-[11.5px] leading-5 text-muted-foreground/80">{helper}</span>
      )}
    </label>
  );
}

function ItemCard({
  title,
  description,
  status,
  children,
}: {
  title: string;
  description: string;
  status: AdminSetupItemStatus;
  children?: React.ReactNode;
}) {
  return (
    <section className="rounded-md border border-border bg-card p-4">
      <header className="mb-2 flex items-start justify-between gap-3">
        <div>
          <h3 className="text-[13px] font-semibold text-foreground">{title}</h3>
          <p className="mt-0.5 text-[11.5px] text-muted-foreground">{description}</p>
        </div>
        <StatusBadge status={status} />
      </header>
      {children && <div className="mt-3 space-y-2">{children}</div>}
    </section>
  );
}

function FieldRow({
  label,
  value,
  onChange,
  placeholder,
  type = "text",
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  type?: string;
}) {
  return (
    <label className="block text-[11.5px] text-muted-foreground">
      <span className="mb-0.5 block">{label}</span>
      <input
        type={type}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className="w-full rounded-md border border-border bg-background px-2 py-1.5 text-[12.5px] text-foreground outline-none focus:border-primary focus:ring-1 focus:ring-primary/30"
      />
    </label>
  );
}

const OUTREACH_HINTS: Record<
  OutreachConnectorRef["id"],
  { tagline: string; routes: string }
> = {
  "apple-messages": {
    tagline: "iMessage from your Mac. Auto-picks blue-bubble route for iPhone leads.",
    routes: "Pairs with Messages.app via the existing local bridge — already syncing 237k+ records on this Mac.",
  },
  "sms-provider": {
    tagline: "Business SMS line (Twilio, Sinch, MessageBird, etc.) for non-iPhone leads.",
    routes: "Two-way SMS over a webhook/API. Use for green-bubble Android leads.",
  },
  "android-device": {
    tagline: "Personal Android device SMS via export or helper.",
    routes: "Backup/export route — does not claim live sync unless a helper is wired.",
  },
  "rcs": {
    tagline: "Rich messaging (read receipts, media, typing) for Android leads.",
    routes: "Business RCS provider or Twilio RCS. Personal-device RCS is import-only.",
  },
};

function ConnectorStatusBadge({ connector }: { connector: OutreachConnectorRef }) {
  if (connector.connected) {
    return (
      <span className="inline-flex items-center gap-1 rounded-md bg-success/15 px-1.5 py-0.5 text-[10.5px] font-medium text-success">
        <CheckCircle2 className="h-3 w-3" /> Connected
      </span>
    );
  }
  if (connector.importOnly) {
    return (
      <span className="inline-flex items-center gap-1 rounded-md bg-muted px-1.5 py-0.5 text-[10.5px] font-medium text-muted-foreground">
        <CheckCircle2 className="h-3 w-3" /> Import only
      </span>
    );
  }
  if (connector.blocked) {
    return (
      <span className="inline-flex items-center gap-1 rounded-md border border-destructive/40 bg-destructive/10 px-1.5 py-0.5 text-[10.5px] font-medium text-destructive">
        <AlertTriangle className="h-3 w-3" /> Blocked
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 rounded-md border border-warning/40 bg-warning/10 px-1.5 py-0.5 text-[10.5px] font-medium text-warning">
      <Circle className="h-3 w-3" /> Not configured
    </span>
  );
}

function OutreachConnectorsCard({
  connectors,
  outreachReady,
  crmStatus,
  crmProvider,
}: {
  connectors: OutreachConnectorRef[];
  outreachReady: boolean;
  crmStatus: AdminSetupItemStatus;
  crmProvider: string;
}) {
  return (
    <section className="rounded-md border border-border bg-card p-4">
      <header className="mb-3 flex items-start justify-between gap-3">
        <div>
          <h3 className="text-[13px] font-semibold text-foreground">Outreach channels</h3>
          <p className="mt-0.5 text-[11.5px] text-muted-foreground">
            iMessage, SMS, and RCS aren't configured here — they live as Source Connectors so the same wiring
            powers ingestion (read-only message index) and outbound. Elevate auto-routes: iPhone leads get
            iMessage, Android leads fall through to SMS / RCS.
          </p>
        </div>
        {outreachReady ? (
          <span className="inline-flex shrink-0 items-center gap-1 rounded-md bg-success/15 px-1.5 py-0.5 text-[10.5px] font-medium text-success">
            <CheckCircle2 className="h-3 w-3" /> Ready
            {crmStatus === "connected" && crmProvider ? ` (via ${crmProvider})` : ""}
          </span>
        ) : (
          <span className="inline-flex shrink-0 items-center gap-1 rounded-md border border-warning/40 bg-warning/10 px-1.5 py-0.5 text-[10.5px] font-medium text-warning">
            <Circle className="h-3 w-3" /> None active
          </span>
        )}
      </header>

      <div className="mb-3 flex flex-wrap items-center gap-2">
        <Link
          to="/config#connectors"
          className="inline-flex items-center gap-1 rounded-md border border-border bg-background px-2 py-1 text-[11.5px] font-medium text-foreground hover:bg-muted"
        >
          <LinkIcon className="h-3 w-3" />
          Open Source Connectors
        </Link>
        <span className="text-[10.5px] text-muted-foreground">
          Config → Source connectors. Each row below opens its setup task.
        </span>
      </div>

      <div className="space-y-1.5">
        {connectors.length === 0 ? (
          <p className="text-[11.5px] text-muted-foreground">
            Loading connector state…
          </p>
        ) : (
          connectors.map((connector) => {
            const hint = OUTREACH_HINTS[connector.id];
            return (
              <div
                key={connector.id}
                className="flex items-start justify-between gap-3 rounded-md border border-border/60 bg-muted/15 px-3 py-2"
              >
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className="text-[12.5px] font-medium text-foreground">{connector.label}</span>
                    <ConnectorStatusBadge connector={connector} />
                    {connector.totalRecords > 0 && (
                      <span className="text-[10.5px] text-muted-foreground">
                        {connector.totalRecords.toLocaleString()} records
                      </span>
                    )}
                  </div>
                  <p className="mt-0.5 truncate text-[11px] text-muted-foreground">{hint?.tagline}</p>
                  {connector.nextOperatorStep && !connector.connected && (
                    <p className="mt-1 text-[10.5px] text-muted-foreground/80">
                      Next: {connector.nextOperatorStep}
                    </p>
                  )}
                  {connector.lastError && (
                    <p className="mt-1 text-[10.5px] text-destructive/80">{connector.lastError}</p>
                  )}
                </div>
                <Link
                  to="/config#connectors"
                  className="inline-flex shrink-0 items-center gap-1 text-[11px] text-primary underline-offset-2 hover:underline"
                >
                  Configure <ExternalLink className="h-3 w-3" />
                </Link>
              </div>
            );
          })
        )}
      </div>
    </section>
  );
}

export function LeadsSetupLaunch({
  setup,
  onSetupUpdated,
  forceOnboarding = false,
  onForceOnboardingDone,
}: {
  setup: LeadsSetupSnapshot;
  onSetupUpdated: (next: LeadsSetupSnapshot) => void;
  forceOnboarding?: boolean;
  onForceOnboardingDone?: () => void;
}) {
  const [draft, setDraft] = useState<LeadsSetupDraft>(() => leadsDraftFromSnapshot(setup));
  const [saving, setSaving] = useState(false);
  const [completing, setCompleting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [savedMessage, setSavedMessage] = useState<string | null>(null);
  const [phase, setPhase] = useState<"gate" | "welcome" | "wizard" | "form">(() =>
    forceOnboarding ? "welcome" : isBrandNewLeadsSetup(setup) ? "gate" : "form",
  );
  const [outreachSourceConnectors, setOutreachSourceConnectors] = useState<SourceConnectorStatus[]>([]);
  const [sourceConnectorsLoading, setSourceConnectorsLoading] = useState(true);
  const [firstTouchTemplates, setFirstTouchTemplates] = useState<OutreachTemplate[]>([]);

  const refreshSourceConnectors = useCallback(async () => {
    setSourceConnectorsLoading(true);
    try {
      const resp = await api.getSourceConnectors();
      const ids = new Set<string>(OUTREACH_CONNECTOR_IDS);
      setOutreachSourceConnectors(resp.connectors.filter((c) => ids.has(c.id)));
    } catch {
      // best-effort — leave previous list in place
    } finally {
      setSourceConnectorsLoading(false);
    }
  }, []);

  useEffect(() => {
    void refreshSourceConnectors();
  }, [refreshSourceConnectors]);

  const refreshTemplates = useCallback(async () => {
    try {
      const resp = await api.getOutreachTemplates();
      setFirstTouchTemplates(resp.templates.filter((t) => t.active));
    } catch {
      // best-effort
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const resp = await api.getOutreachTemplates();
        if (cancelled) return;
        const actives = resp.templates.filter((t) => t.active);
        setFirstTouchTemplates(actives);
        const policyVal = (setup.items.find((i) => i.key === "auto_reply_policy")?.value ?? {}) as Record<string, unknown>;
        const stored = String(policyVal.initialMessageTemplate ?? "").trim();
        const currentMatchesDefault = draft.autoReplyTemplate.trim() === DEFAULT_AUTO_REPLY_TEMPLATE.trim();
        const firstTouchDefault = actives.find((t) => t.lane === "new-outreach");
        if (firstTouchDefault && !stored && currentMatchesDefault) {
          setDraft((prev) => ({ ...prev, autoReplyTemplate: firstTouchDefault.body }));
        }
      } catch {
        // best-effort — empty list falls back to default opener
      }
    })();
    return () => {
      cancelled = true;
    };
    // intentional one-shot on mount — refetch is via refreshTemplates
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (forceOnboarding && phase === "form") {
      onForceOnboardingDone?.();
    }
  }, [forceOnboarding, phase, onForceOnboardingDone]);

  useEffect(() => {
    setDraft(leadsDraftFromSnapshot(setup));
  }, [setup]);

  const byKey = useMemo(() => new Map(setup.items.map((item: LeadsSetupItem) => [item.key, item])), [setup.items]);
  const crmItem = byKey.get("crm");
  const metaItem = byKey.get("meta_lead_ads");
  const googleItem = byKey.get("google_lead_forms");
  const webhookItem = byKey.get("website_form_webhook");
  const policyItem = byKey.get("auto_reply_policy");

  const save = useCallback(async () => {
    setSaving(true);
    setError(null);
    setSavedMessage(null);
    try {
      const updated = await api.updateLeadsSetup(buildItemUpdates(draft));
      onSetupUpdated(updated);
      setSavedMessage(
        updated.complete
          ? "Saved. Everything required is in — hit 'Mark complete' to lift the gate."
          : `Saved. ${updated.missingRequiredKeys.length} item(s) still required.`,
      );
    } catch (err) {
      setError(errorMessage(err, "Save failed"));
    } finally {
      setSaving(false);
    }
  }, [draft, onSetupUpdated]);

  const markComplete = useCallback(async () => {
    setCompleting(true);
    setError(null);
    setSavedMessage(null);
    try {
      await api.updateLeadsSetup(buildItemUpdates(draft));
      const completed = await api.completeLeadsSetup();
      onSetupUpdated(completed);
      onForceOnboardingDone?.();
    } catch (err) {
      setError(errorMessage(err, "Could not complete setup"));
    } finally {
      setCompleting(false);
    }
  }, [draft, onSetupUpdated, onForceOnboardingDone]);

  const updateField = useCallback(<K extends keyof LeadsSetupDraft>(key: K, value: LeadsSetupDraft[K]) => {
    setDraft((prev) => ({ ...prev, [key]: value }));
  }, []);

  const pct = setup.completionPct ?? 0;
  const crmStatus = crmItem?.status ?? "missing";
  const crmProvider = (crmItem?.provider || "").trim();
  const leadSourcesReady = setup.leadSourcesReady;
  const outreachReady = setup.outreachReady;
  const outreachConnectors = setup.outreachConnectors ?? [];

  const handleWizardFinish = useCallback(async () => {
    setError(null);
    setSavedMessage(null);
    try {
      await api.updateLeadsSetup(buildItemUpdates(draft));
    } catch (err) {
      setError(errorMessage(err, "Save failed"));
      return;
    }
    playOnboardingChime();
    setPhase("form");
  }, [draft]);

  if (phase === "gate") {
    return (
      <LeadsOnboardingGate
        onStart={() => setPhase("welcome")}
        onSkip={() => setPhase("form")}
      />
    );
  }

  if (phase === "welcome") {
    return <LeadsOnboardingWelcome onContinue={() => setPhase("wizard")} />;
  }

  if (phase === "wizard") {
    return (
      <LeadsOnboardingWizard
        draft={draft}
        updateField={updateField}
        onAdvanceSave={save}
        onFinish={handleWizardFinish}
        saving={saving}
        completing={completing}
        error={error}
        savedMessage={savedMessage}
        outreachSourceConnectors={outreachSourceConnectors}
        refreshSourceConnectors={refreshSourceConnectors}
        sourceConnectorsLoading={sourceConnectorsLoading}
        firstTouchTemplates={firstTouchTemplates}
        refreshTemplates={refreshTemplates}
      />
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="rounded-md border border-border bg-card p-4">
        <div className="flex items-start justify-between gap-3">
          <div>
            <h2 className="text-[14px] font-semibold text-foreground">Leads onboarding</h2>
            <p className="mt-1 text-[12px] text-muted-foreground">
              CRM is inherited from Admin setup and already counts as an outreach lane. Wire at least one
              lead source (Meta / Google / Website webhook) and set your auto-reply policy. Texting channels
              (iMessage / SMS / RCS) are managed in Source Connectors below — Elevate auto-routes by lead device.
            </p>
          </div>
          <div className="flex flex-col items-end gap-2">
            <Button
              size="sm"
              variant="outline"
              onClick={() => setPhase("welcome")}
              className="h-7 gap-1 px-2 text-[11px]"
            >
              <Sparkles className="h-3 w-3" />
              Run guided onboarding
            </Button>
            <div className="flex flex-col items-end gap-1">
              <span className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                {setup.completedRequiredCount}/{setup.requiredCount} required
              </span>
              <div className="h-1.5 w-32 overflow-hidden rounded-full bg-muted">
                <div className="h-full bg-primary transition-all" style={{ width: `${pct}%` }} />
              </div>
              <span className="text-[10.5px] text-muted-foreground">{pct}%</span>
            </div>
          </div>
        </div>
        {forceOnboarding && (
          <div className="mt-3 inline-flex items-center gap-1 rounded-md bg-muted px-2 py-0.5 text-[10.5px] text-muted-foreground">
            <Sparkles className="h-3 w-3" /> Re-running onboarding — existing state preserved
          </div>
        )}
      </div>

      {error && (
        <div className="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-[12px] text-destructive">
          <AlertTriangle className="mr-1 inline h-3.5 w-3.5" />
          {error}
        </div>
      )}
      {savedMessage && (
        <div className="rounded-md border border-border bg-muted/30 px-3 py-2 text-[12px] text-muted-foreground">
          {savedMessage}
        </div>
      )}

      <ItemCard
        title="CRM (inherited from Admin)"
        description={
          crmProvider
            ? `Reading from admin_setup_profile.crm_provider. Manage in Admin → Connectors.`
            : "No CRM set in Admin yet. Finish Admin onboarding first — Leads can't store contacts without a CRM."
        }
        status={crmStatus}
      >
        <div className="text-[12px] text-foreground">
          {crmProvider ? `Connected to ${crmProvider}.` : "Not configured."}
        </div>
      </ItemCard>

      <ItemCard
        title="Meta Lead Ads (optional)"
        description="Skip if you don't run Facebook / Instagram lead-form ads. One Pipeboard token — ad accounts, pages, and lead forms are auto-discovered."
        status={metaItem?.status ?? "missing"}
      >
        <FieldRow
          label="MCP endpoint URL"
          value={draft.metaMcpEndpoint}
          onChange={(v) => updateField("metaMcpEndpoint", v)}
          placeholder="https://mcp.pipeboard.co/meta-ads-mcp"
        />
        <FieldRow
          label="Pipeboard API token"
          value={draft.metaMcpToken}
          onChange={(v) => updateField("metaMcpToken", v)}
          placeholder="••••••••"
          type="password"
        />
        <div className="flex flex-wrap items-center gap-3 text-[11.5px]">
          <a
            href="https://pipeboard.co/api-tokens"
            target="_blank"
            rel="noreferrer noopener"
            className="inline-flex items-center gap-1 text-primary underline-offset-2 hover:underline"
          >
            Get Pipeboard token (OAuth Facebook) <ExternalLink className="h-3 w-3" />
          </a>
          <a
            href="https://github.com/pipeboard-co/meta-ads-mcp"
            target="_blank"
            rel="noreferrer noopener"
            className="inline-flex items-center gap-1 text-muted-foreground underline-offset-2 hover:underline hover:text-foreground"
          >
            Install guide <ExternalLink className="h-3 w-3" />
          </a>
        </div>
      </ItemCard>

      <ItemCard
        title="Google Lead Form Ads (optional)"
        description="Skip if you don't run Google Ads. One developer token — Elevate's CLI auto-discovers your customer ID and campaigns."
        status={googleItem?.status ?? "missing"}
      >
        <FieldRow
          label="Developer token"
          value={draft.googleDeveloperToken}
          onChange={(v) => updateField("googleDeveloperToken", v)}
          placeholder="abcDEF123-xyz"
          type="password"
        />
        <a
          href="https://developers.google.com/google-ads/api/docs/get-started/dev-token"
          target="_blank"
          rel="noreferrer noopener"
          className="inline-flex items-center gap-1 text-[11.5px] text-primary underline-offset-2 hover:underline"
        >
          How to get a Google Ads developer token <ExternalLink className="h-3 w-3" />
        </a>
      </ItemCard>

      <ItemCard
        title="Website form webhook"
        description="Catch-all webhook URL for landing-page and contact-us form submissions."
        status={webhookItem?.status ?? "missing"}
      >
        <FieldRow
          label="Webhook URL (POST endpoint for your form provider)"
          value={draft.webhookUrl}
          onChange={(v) => updateField("webhookUrl", v)}
          placeholder="https://elevate.yourdomain.com/api/leads/inbound"
        />
        <FieldRow
          label="Shared secret (optional — for HMAC verification)"
          value={draft.webhookSecret}
          onChange={(v) => updateField("webhookSecret", v)}
          placeholder="optional"
          type="password"
        />
      </ItemCard>

      <OutreachConnectorsCard
        connectors={outreachConnectors}
        outreachReady={outreachReady}
        crmStatus={crmStatus}
        crmProvider={crmProvider}
      />

      <ItemCard
        title="Auto-reply policy"
        description="Initial-touch behaviour and follow-up cadence default."
        status={policyItem?.status ?? "missing"}
      >
        <label className="flex items-center gap-2 text-[12px] text-foreground">
          <input
            type="checkbox"
            checked={draft.autoReplyEnabled}
            onChange={(e) => updateField("autoReplyEnabled", e.target.checked)}
            className="h-3.5 w-3.5 rounded border-border accent-primary"
          />
          Send an automated first reply when a lead lands
        </label>
        <label className="block text-[11.5px] text-muted-foreground">
          <span className="mb-0.5 block">Initial reply template</span>
          <textarea
            value={draft.autoReplyTemplate}
            onChange={(e) => updateField("autoReplyTemplate", e.target.value)}
            rows={3}
            placeholder="Hey {{firstName}} — thanks for reaching out. What's the property address or area you're looking at?"
            className="w-full resize-y rounded-md border border-border bg-background px-2 py-1.5 text-[12.5px] leading-5 text-foreground outline-none focus:border-primary focus:ring-1 focus:ring-primary/30"
          />
        </label>
        <FieldRow
          label="Follow-up cadence (days between nudges)"
          value={draft.followUpCadenceDays}
          onChange={(v) => updateField("followUpCadenceDays", v)}
          placeholder="2"
          type="number"
        />
      </ItemCard>

      <div className="sticky bottom-2 z-10 flex flex-wrap items-center justify-between gap-2 rounded-md border border-border bg-card/95 px-3 py-2 backdrop-blur">
        <div className="text-[11.5px] text-muted-foreground">
          {leadSourcesReady
            ? "Lead source ready (CRM and/or ads connector)."
            : "Need at least one lead source connected — CRM, Meta, Google, or website webhook."}
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" onClick={() => void save()} disabled={saving || completing}>
            {saving ? <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" /> : null}
            Save
          </Button>
          <Button
            size="sm"
            onClick={() => void markComplete()}
            disabled={completing || saving || setup.requiredCount === 0}
            className={cn(setup.complete ? "" : "opacity-95")}
          >
            {completing ? <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" /> : null}
            Mark complete
          </Button>
        </div>
      </div>
    </div>
  );
}

export function useLeadsSetup(): {
  loading: boolean;
  setup: LeadsSetupSnapshot | null;
  error: string | null;
  setSetup: (next: LeadsSetupSnapshot) => void;
  refresh: () => Promise<void>;
} {
  const [setup, setSetup] = useState<LeadsSetupSnapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const snap = await api.getLeadsSetup();
      setSetup(snap);
    } catch (err) {
      setError(errorMessage(err, "Could not load leads setup"));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  return { loading, setup, error, setSetup, refresh };
}

```

---
## `src/pages/real-estate-hub/memory/index.tsx`
```tsx
import { lazy, Suspense } from "react";
import {
  Brain,
  CheckCircle2,
  Clock,
  Network,
} from "lucide-react";
import type { AgentHubMemoryNode } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { isoTimeAgo } from "@/lib/utils";
import {
  HubShell,
  useHubHeader,
  useRealEstateHubData,
} from "@/pages/real-estate-hub/_shared";

const MemoryConstellation = lazy(() =>
  import("@/components/MemoryConstellation").then((m) => ({ default: m.MemoryConstellation })),
);

function MemoryGraphView({
  nodes,
  edges,
}: {
  nodes: AgentHubMemoryNode[];
  edges: { source: string; target: string; type: string }[];
}) {
  if (nodes.length === 0) {
    return (
      <div className="font-mono-ui flex h-48 items-center justify-center px-4 text-center text-[0.72rem] text-muted-foreground/80">
        Graph is empty — memory will populate as agents process sessions.
      </div>
    );
  }
  return (
    <Suspense
      fallback={
        <div className="font-mono-ui flex h-64 items-center justify-center text-[0.72rem] text-muted-foreground/80">
          Loading graph…
        </div>
      }
    >
      <MemoryConstellation
        className="max-h-[38rem] min-h-[24rem]"
        edges={edges}
        nodes={nodes}
      />
    </Suspense>
  );
}

export function RealEstateMemoryPage() {
  const data = useRealEstateHubData();
  useHubHeader("Memory", data);
  const memory = data.snapshot?.memory;

  const pending = memory?.journal.pending ?? 0;
  const failed = memory?.journal.failed ?? 0;
  const activeSessionCount = memory?.journal.active_session_count ?? 0;
  const pipelineState =
    failed > 0
      ? { tone: "warn" as const, label: `${failed} failed` }
      : pending > 0
        ? { tone: "active" as const, label: `${pending} pending` }
        : { tone: "ok" as const, label: "Idle" };

  const recentSessions = memory?.journal.sessions ?? [];
  const latestIngest = recentSessions
    .map((s) => s.latest_created_at)
    .filter((v): v is string => Boolean(v))
    .sort()
    .reverse()[0];

  return (
    <HubShell
      data={data}
      eyebrow="Memory Graph"
      icon={Brain}
      title="Memory"
    >
      <div className="grid gap-3 sm:grid-cols-3">
        <SummaryTile
          icon={Clock}
          label="Pipeline"
          value={pipelineState.label}
          tone={pipelineState.tone}
        />
        <SummaryTile
          icon={CheckCircle2}
          label="Last ingest"
          value={latestIngest ? isoTimeAgo(latestIngest) : "Never"}
          tone={latestIngest ? "ok" : "warn"}
        />
        <SummaryTile
          icon={Brain}
          label="Embeddings"
          value={memory?.embedding.enabled ? memory.embedding.model || "On" : "Off"}
          tone={memory?.embedding.enabled ? "ok" : "warn"}
        />
      </div>

      <div className="grid gap-4 2xl:grid-cols-[minmax(0,1fr)_24rem]">
        <Card className="overflow-hidden bg-card p-0">
          <CardHeader>
            <div className="flex items-center justify-between gap-3">
              <CardTitle className="flex items-center gap-2">
                <Network className="h-4 w-4 text-primary" />
                Knowledge graph
              </CardTitle>
              <Badge variant={memory?.embedding.enabled ? "success" : "outline"}>
                {memory?.embedding.enabled ? "Embeddings on" : "Embeddings off"}
              </Badge>
            </div>
          </CardHeader>
          <CardContent className="p-0">
            <MemoryGraphView
              nodes={memory?.graph.nodes ?? []}
              edges={memory?.graph.edges ?? []}
            />
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Recent ingest</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="flex items-center justify-between gap-3 text-xs">
              <span className="text-muted-foreground">Active sessions</span>
              <span className="font-medium text-foreground tabular-nums">{activeSessionCount}</span>
            </div>
            <div className="rounded-md border border-border bg-card p-3 text-xs leading-5 text-muted-foreground">
              <div className="font-medium text-foreground">
                {memory?.provider ?? "memory"} · {memory?.embedding.provider ?? "no embedding"}
              </div>
              <div className="mt-1 truncate">{memory?.db_path ?? "No memory database path yet."}</div>
            </div>
            {recentSessions.length > 0 ? (
              <div className="space-y-1.5">
                <div className="px-1 text-xs text-muted-foreground">
                  Sessions
                </div>
                <div className="space-y-1">
                  {recentSessions.slice(0, 6).map((session) => (
                    <div
                      key={`${session.session_id}-${session.session_day}`}
                      className="flex items-center justify-between gap-2 rounded-md border border-border/50 bg-background/40 px-2.5 py-1.5 text-xs"
                    >
                      <div className="min-w-0 truncate">
                        <span className="font-medium text-foreground">{session.session_day}</span>
                        <span className="ml-1.5 text-muted-foreground/70">
                          {session.latest_created_at ? isoTimeAgo(session.latest_created_at) : ""}
                        </span>
                      </div>
                      <Badge variant="outline" className="shrink-0">{session.total}</Badge>
                    </div>
                  ))}
                </div>
              </div>
            ) : (
              <p className="px-1 text-xs text-muted-foreground/80">
                No recent ingest sessions.
              </p>
            )}
          </CardContent>
        </Card>
      </div>
    </HubShell>
  );
}

function SummaryTile({
  icon: Icon,
  label,
  value,
  tone,
}: {
  icon: typeof Clock;
  label: string;
  value: string | number;
  tone: "ok" | "warn" | "active";
}) {
  const valueClass =
    tone === "warn"
      ? "text-warning"
      : tone === "active"
        ? "text-primary"
        : "text-foreground";
  return (
    <div className="rounded-lg border border-border bg-card px-4 py-3">
      <div className="flex items-center gap-2 text-xs font-medium uppercase tracking-wider text-muted-foreground">
        <Icon className="h-3.5 w-3.5" />
        {label}
      </div>
      <div className={`mt-1 truncate text-lg font-semibold ${valueClass}`}>
        {value}
      </div>
    </div>
  );
}

```

---
## `src/pages/real-estate-hub/social/index.tsx`
```tsx
import { useCallback, useEffect, useId, useMemo, useRef, useState } from "react";
import {
  Activity,
  Award,
  Loader2,
  Megaphone,
  RefreshCw,
  Sparkles,
} from "lucide-react";
import { api } from "@/lib/api";
import type { SocialIdea, SocialMetricRow, SocialSnapshot } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import {
  HubShell,
  useHubHeader,
  useRealEstateHubData,
} from "@/pages/real-estate-hub/_shared";
import {
  IdeaCard,
  PlatformBlockCard,
  PlatformRankingsBlock,
  PlatformTablist,
  PostDetailModal,
  RealVideoCard,
  YouTubeTabView,
  computeEngagementScore,
  formatCompact,
  formatPct,
} from "@/pages/real-estate-hub/social-media-widgets";

export function RealEstateSocialMediaPage() {
  const data = useRealEstateHubData();
  useHubHeader("Social Media", data);

  const [snapshot, setSnapshot] = useState<SocialSnapshot | null>(null);
  const [ideas, setIdeas] = useState<SocialIdea[]>([]);
  const [recentPosts, setRecentPosts] = useState<SocialMetricRow[]>([]);
  const [loadingSocial, setLoadingSocial] = useState(true);
  const [actingOn, setActingOn] = useState<string | null>(null);
  const [socialError, setSocialError] = useState<string | null>(null);
  const [platformFilter, setPlatformFilter] = useState<string>("all");
  const [selectedPost, setSelectedPost] = useState<SocialMetricRow | null>(null);
  const [refreshing, setRefreshing] = useState<string | null>(null);
  const [postLimit, setPostLimit] = useState<number>(100);
  const [lookbackDays, setLookbackDays] = useState<number>(730);
  const tabIdPrefix = useId();
  const panelId = useId();
  const activeTabId = `${tabIdPrefix}-tab-${platformFilter}`;
  const refreshAbortRef = useRef<AbortController | null>(null);

  const refresh = useCallback(async () => {
    refreshAbortRef.current?.abort();
    const controller = new AbortController();
    refreshAbortRef.current = controller;
    const { signal } = controller;
    setLoadingSocial(true);
    setSocialError(null);
    try {
      const [snapRes, ideaRes, recentRes] = await Promise.allSettled([
        api.getSocialSnapshot(signal),
        api.getSocialIdeas("pending", signal),
        api.getSocialRecentPosts(1000, signal),
      ]);
      if (signal.aborted) return;
      if (snapRes.status === "fulfilled") setSnapshot(snapRes.value);
      if (ideaRes.status === "fulfilled") setIdeas(ideaRes.value.items || []);
      if (recentRes.status === "fulfilled") setRecentPosts(recentRes.value.items || []);
    } catch (e) {
      if (signal.aborted) return;
      setSocialError(e instanceof Error ? e.message : "Failed to load social data");
    } finally {
      if (!signal.aborted) setLoadingSocial(false);
    }
  }, []);

  useEffect(() => {
    refresh();
    return () => {
      refreshAbortRef.current?.abort();
    };
  }, [refresh]);

  useEffect(() => {
    setPostLimit(100);
  }, [platformFilter]);

  const handleIdeaAction = useCallback(
    async (recordId: string, action: "approve" | "reject" | "edit", edit?: Partial<SocialIdea>) => {
      setActingOn(recordId);
      try {
        await api.socialIdeaAction(recordId, { action, ...(edit ? { edit } : {}) });
        await refresh();
      } catch (e) {
        setSocialError(e instanceof Error ? e.message : "Action failed");
      } finally {
        setActingOn(null);
      }
    },
    [refresh],
  );

  const totals = snapshot?.totals;
  const platforms = snapshot?.platforms || {};
  const platformList = Object.entries(platforms);

  const avgEngagement = useMemo(() => {
    const vals = platformList
      .map(([, p]) => p.averages?.engagement_rate)
      .filter((v): v is number => v != null);
    if (!vals.length) return null;
    return vals.reduce((a, b) => a + b, 0) / vals.length;
  }, [platformList]);

  const avgHook = useMemo(() => {
    const vals = platformList
      .map(([, p]) => p.averages?.hook_rate)
      .filter((v): v is number => v != null);
    if (!vals.length) return null;
    return vals.reduce((a, b) => a + b, 0) / vals.length;
  }, [platformList]);

  const wow = snapshot?.wow_delta;

  const platformCounts = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const r of recentPosts) {
      const p = (r.platform || "").toLowerCase();
      if (!p) continue;
      counts[p] = (counts[p] || 0) + 1;
    }
    return counts;
  }, [recentPosts]);

  const filteredPosts = useMemo(() => {
    const base = recentPosts.filter(
      (r) => (r.media_type || "").toUpperCase() !== "ACCOUNT",
    );
    if (platformFilter === "all") return base;
    return base.filter((r) => (r.platform || "").toLowerCase() === platformFilter);
  }, [recentPosts, platformFilter]);

  const topPerformers = useMemo(() => {
    const scored = recentPosts
      .map((r) => ({ row: r, score: computeEngagementScore(r) }))
      .filter((x) => x.score > 0)
      .sort((a, b) => b.score - a.score)
      .slice(0, 3);
    return scored.map((x) => x.row);
  }, [recentPosts]);

  const handleRefreshAll = useCallback(async () => {
    setRefreshing("all");
    setSocialError(null);
    try {
      await api.refreshSocialMetrics({ lookbackDays, maxPosts: 200 });
      await refresh();
    } catch (e) {
      setSocialError(e instanceof Error ? e.message : "Refresh failed");
    } finally {
      setRefreshing(null);
    }
  }, [refresh, lookbackDays]);

  const hasData = (totals?.post_count ?? 0) > 0 || avgEngagement != null;

  return (
    <HubShell
      data={data}
      eyebrow="Social Studio"
      icon={Megaphone}
      title="Social Media"
    >
      {hasData ? (
        <div className="flex flex-wrap items-baseline gap-x-5 gap-y-1 text-xs text-muted-foreground">
          <span>
            <span className="font-medium tabular-nums text-foreground">
              {totals?.post_count ?? 0}
            </span>{" "}
            posts
          </span>
          <span>
            <span className="tabular-nums text-foreground">{formatCompact(totals?.reach)}</span>{" "}
            reach
          </span>
          {avgEngagement != null && (
            <span>
              <span className="tabular-nums text-foreground">{formatPct(avgEngagement, 2)}</span>{" "}
              avg engagement
            </span>
          )}
          {avgHook != null && (
            <span>
              <span className="tabular-nums text-foreground">{formatPct(avgHook, 2)}</span>{" "}
              avg hook rate
            </span>
          )}
        </div>
      ) : (
        <p className="text-xs text-muted-foreground">
          Weekly content engine runs Monday 7am Pacific. Connect a social platform in Channels to populate this view.
        </p>
      )}

      {socialError && (
        <p className="px-1 py-1 text-xs text-destructive">{socialError}</p>
      )}

      {snapshot && snapshot.exists === false && (
        <p className="px-1 py-1 text-xs text-muted-foreground/80">
          No snapshot yet. Weekly content engine runs Mondays 7am Pacific.{" "}
          {snapshot.message ?? "Connect at least one social platform in Channels to begin."}
        </p>
      )}

      <Card>
        <CardHeader>
          <div className="flex items-center justify-between gap-3">
            <CardTitle className="flex items-center gap-2">
              <Sparkles className="h-4 w-4 text-primary" />
              AI idea approval queue
            </CardTitle>
            <div className="flex items-center gap-2">
              <Badge variant={ideas.length ? "warning" : "success"}>{ideas.length}</Badge>
              <Button
                size="sm"
                variant="ghost"
                onClick={refresh}
                disabled={loadingSocial}
                aria-label="Refresh idea queue"
              >
                <RefreshCw className={cn("h-3.5 w-3.5", loadingSocial && "animate-spin")} />
              </Button>
            </div>
          </div>
        </CardHeader>
        <CardContent className="space-y-5">
          {loadingSocial && !ideas.length ? (
            <p className="px-1 py-1 text-xs text-muted-foreground/80">Loading ideas…</p>
          ) : ideas.length === 0 ? (
            <p className="px-1 py-1 text-xs text-muted-foreground/80">
              No ideas waiting — the engine queues 5–10 every Monday morning.
            </p>
          ) : (
            ideas.map((idea) => (
              <IdeaCard
                key={idea.source_record_id}
                idea={idea}
                busy={actingOn === idea.source_record_id}
                onAction={(action, edit) => handleIdeaAction(idea.source_record_id, action, edit)}
              />
            ))
          )}
        </CardContent>
      </Card>

      {platformList.length > 0 && (
        <Card>
          <CardHeader>
            <div className="flex items-center justify-between gap-3">
              <CardTitle className="flex items-center gap-2">
                <Award className="h-4 w-4" />
                Per-platform performance
              </CardTitle>
              {wow && (
                <div className="font-mono-ui flex items-center gap-3 text-[0.7rem] text-muted-foreground">
                  <span>
                    Posts WoW{" "}
                    <span className={wow.post_count_delta >= 0 ? "text-success" : "text-destructive"}>
                      {wow.post_count_delta >= 0 ? "+" : ""}
                      {wow.post_count_delta}
                    </span>
                  </span>
                  {wow.engagement_rate_delta != null && (
                    <span>
                      Eng WoW{" "}
                      <span className={wow.engagement_rate_delta >= 0 ? "text-success" : "text-destructive"}>
                        {wow.engagement_rate_delta >= 0 ? "+" : ""}
                        {(wow.engagement_rate_delta * 100).toFixed(2)}pp
                      </span>
                    </span>
                  )}
                </div>
              )}
            </div>
          </CardHeader>
          <CardContent>
            <div className="grid gap-3 lg:grid-cols-2 2xl:grid-cols-3">
              {platformList.map(([platform, block]) => (
                <PlatformBlockCard key={platform} platform={platform} block={block} />
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader className="space-y-1">
          <div className="flex flex-wrap items-start justify-between gap-x-6 gap-y-3">
            <div className="space-y-1">
              <CardTitle className="flex items-center gap-2 text-lg">
                <Activity className="h-4 w-4" />
                Your posts
              </CardTitle>
              <p className="text-xs text-muted-foreground">
                {recentPosts.length === 0
                  ? "Nothing pulled yet"
                  : `${recentPosts.length} pulled · last ${lookbackDays} days`}
              </p>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <label className="flex items-center gap-1.5 text-xs text-muted-foreground">
                <span>Lookback</span>
                <select
                  value={lookbackDays}
                  onChange={(e) => setLookbackDays(Number(e.target.value))}
                  disabled={refreshing !== null}
                  aria-label="Lookback period"
                  className="h-8 rounded-md border border-border bg-background px-2 text-xs text-foreground focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary"
                >
                  <option value={30}>30 days</option>
                  <option value={90}>90 days</option>
                  <option value={180}>180 days</option>
                  <option value={365}>1 year</option>
                  <option value={730}>2 years</option>
                </select>
              </label>
              <Button
                variant="outline"
                size="sm"
                onClick={handleRefreshAll}
                disabled={refreshing !== null}
              >
                {refreshing ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <RefreshCw className="h-3.5 w-3.5" />
                )}
                {refreshing ? "Pulling…" : "Refresh"}
              </Button>
            </div>
          </div>
        </CardHeader>
        <CardContent className="space-y-8">
          {recentPosts.length > 0 && (
            <div className="border-b border-border/40 pb-4">
              <PlatformTablist
                tabs={[
                  { label: "all", count: recentPosts.length },
                  ...Object.entries(platformCounts)
                    .sort(([, a], [, b]) => b - a)
                    .map(([p, c]) => ({ label: p, count: c })),
                ]}
                active={platformFilter}
                onChange={setPlatformFilter}
                idPrefix={tabIdPrefix}
                panelId={panelId}
              />
            </div>
          )}
          <div
            id={panelId}
            role="tabpanel"
            aria-labelledby={activeTabId}
            tabIndex={0}
            className="space-y-10 focus:outline-none"
          >
            {platformFilter === "youtube" ? (
              <YouTubeTabView posts={recentPosts} onSelect={setSelectedPost} />
            ) : (
              <>
                {(["instagram", "facebook", "tiktok"].includes(platformFilter) ||
                  platformFilter === "all") && (
                  <PlatformRankingsBlock posts={filteredPosts} onSelect={setSelectedPost} />
                )}
                {filteredPosts.length === 0 ? (
                  <p className="px-1 py-1 text-xs text-muted-foreground/80">
                    {recentPosts.length === 0
                      ? "No posts pulled yet — click Refresh to pull live from every connected account."
                      : `No ${platformFilter} posts in the last ${lookbackDays} days. Connect ${platformFilter} or extend the lookback.`}
                  </p>
                ) : (
                  <section className="space-y-4" aria-labelledby="all-posts-heading">
                    <header className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
                      <h3
                        id="all-posts-heading"
                        className="text-sm font-medium text-foreground"
                      >
                        All posts
                      </h3>
                      <span
                        className="text-xs text-muted-foreground tabular-nums"
                        aria-live="polite"
                      >
                        {Math.min(postLimit, filteredPosts.length)} of {filteredPosts.length}
                      </span>
                    </header>
                    <div className="grid gap-4 items-start grid-cols-[repeat(auto-fill,minmax(180px,1fr))]">
                      {(() => {
                        const topKeys = new Set(
                          platformFilter === "all"
                            ? topPerformers.map((r) => `${r.platform}:${r.post_id}`)
                            : [],
                        );
                        const ordered = [
                          ...filteredPosts.filter((r) => topKeys.has(`${r.platform}:${r.post_id}`)),
                          ...filteredPosts.filter((r) => !topKeys.has(`${r.platform}:${r.post_id}`)),
                        ];
                        return ordered.slice(0, postLimit).map((row) => (
                          <RealVideoCard
                            key={`${row.platform}:${row.post_id}`}
                            row={row}
                            onClick={() => setSelectedPost(row)}
                            highlight={topKeys.has(`${row.platform}:${row.post_id}`)}
                          />
                        ));
                      })()}
                    </div>
                    {filteredPosts.length > postLimit && (
                      <div className="mt-2 flex flex-wrap justify-center gap-2 border-t border-border/40 pt-4">
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => setPostLimit((n) => n + 100)}
                        >
                          Show 100 more ({filteredPosts.length - postLimit} remaining)
                        </Button>
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => setPostLimit(filteredPosts.length)}
                        >
                          Show all ({filteredPosts.length})
                        </Button>
                      </div>
                    )}
                  </section>
                )}
              </>
            )}
          </div>
        </CardContent>
      </Card>

      {selectedPost && (
        <PostDetailModal row={selectedPost} onClose={() => setSelectedPost(null)} />
      )}
    </HubShell>
  );
}

```

---
## `src/pages/real-estate-hub/tasks/index.tsx`
```tsx
import { useEffect, useMemo, useState, type ComponentType, type ReactNode } from "react";
import {
  AlertTriangle,
  Bot,
  CalendarClock,
  Loader2,
  Repeat,
  Sparkles,
} from "lucide-react";
import { Link } from "react-router-dom";
import { api } from "@/lib/api";
import type {
  AccessStatusResponse,
  AdminDealTask,
  AgentHubSnapshot,
} from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button, buttonVariants } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { cn, isoTimeAgo } from "@/lib/utils";
import {
  AdminActionRuns,
  AdminDealTasks,
  HubShell,
  RecentSessions,
  TimedTasks,
  adminRunStatusVariant,
  useHubHeader,
  useRealEstateHubData,
} from "@/pages/real-estate-hub/_shared";

type Handoff = NonNullable<AgentHubSnapshot["handoffs"]>["recent"][number];

export function RealEstateTasksPage() {
  const data = useRealEstateHubData();
  const [accessStatus, setAccessStatus] = useState<AccessStatusResponse | null>(null);
  useHubHeader("Tasks", data);

  useEffect(() => {
    let cancelled = false;
    api
      .getAccessStatus()
      .then((status) => {
        if (!cancelled) setAccessStatus(status);
      })
      .catch(() => {
        if (!cancelled) setAccessStatus(null);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const handoffs = data.snapshot?.handoffs;
  const worker = data.snapshot?.agentWorker;
  const adminPackActive = Boolean(accessStatus?.packs.realEstateAdmin);

  const activeSessions = useMemo(
    () => data.sessions.filter((s) => s.is_active),
    [data.sessions],
  );
  const enabledJobs = useMemo(
    () => data.cronJobs.filter((j) => j.enabled),
    [data.cronJobs],
  );
  const openActionRuns = useMemo(
    () =>
      data.actionRuns.filter(
        (r) => !["succeeded", "completed", "skipped", "cancelled"].includes(r.status),
      ),
    [data.actionRuns],
  );
  const waitingHumanHandoffs = useMemo<Handoff[]>(
    () => (handoffs?.recent ?? []).filter((h) => h.status === "waiting_human"),
    [handoffs],
  );
  const pendingDealTasks = useMemo<AdminDealTask[]>(
    () =>
      adminPackActive
        ? data.dealTasks.filter((t) => t.status === "available" || t.status === "waiting_human")
        : [],
    [data.dealTasks, adminPackActive],
  );
  const waitingActionRuns = useMemo(
    () => openActionRuns.filter((r) => r.status === "waiting_human"),
    [openActionRuns],
  );
  const runningActionRuns = useMemo(
    () => openActionRuns.filter((r) => r.status === "running" || r.status === "queued"),
    [openActionRuns],
  );

  const waitingTotal =
    waitingHumanHandoffs.length + pendingDealTasks.length + waitingActionRuns.length;
  const inFlight = (handoffs?.queued ?? 0) + (handoffs?.running ?? 0) + runningActionRuns.length;

  return (
    <HubShell data={data} eyebrow="Operations" icon={CalendarClock} title="Tasks">
      <div className="grid gap-3 sm:grid-cols-3">
        <SummaryTile
          icon={AlertTriangle}
          label="Waiting on you"
          value={waitingTotal}
          tone={waitingTotal > 0 ? "warn" : "neutral"}
        />
        <SummaryTile
          icon={Bot}
          label="In flight"
          value={inFlight}
          tone={inFlight > 0 ? "active" : "neutral"}
        />
        <SummaryTile
          icon={CalendarClock}
          label="Scheduled"
          value={enabledJobs.length}
          tone="neutral"
        />
      </div>

      <ApprovalBoard
        handoffs={waitingHumanHandoffs}
        dealTasks={pendingDealTasks}
        runs={waitingActionRuns}
        adminPackActive={adminPackActive}
        onChanged={data.refresh}
      />

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_24rem]">
        <InFlightCard
          worker={worker}
          handoffs={handoffs}
          runningCount={runningActionRuns.length}
        />
        <RecentSessions
          title="Active sessions"
          sessions={activeSessions}
          empty="No sessions are active."
        />
      </div>

      {adminPackActive && openActionRuns.length > 0 && (
        <AdminActionRuns runs={openActionRuns} onChanged={data.refresh} />
      )}

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_24rem]">
        <TimedTasks jobs={data.cronJobs} title="Scheduled automations" empty="No timed tasks scheduled." />
        <RecentSessions
          title="Recent sessions"
          sessions={data.sessions.filter((s) => !s.is_active).slice(0, 6)}
          empty="No recent sessions."
        />
      </div>

      {adminPackActive && pendingDealTasks.length === 0 && data.dealTasks.length > 0 && (
        <AdminDealTasks tasks={data.dealTasks} onChanged={data.refresh} title="All transaction tasks" />
      )}
    </HubShell>
  );
}

function SummaryTile({
  icon: Icon,
  label,
  value,
  tone,
}: {
  icon: ComponentType<{ className?: string }>;
  label: string;
  value: number;
  tone: "neutral" | "warn" | "active";
}) {
  const valueClass =
    tone === "warn"
      ? "text-warning"
      : tone === "active"
        ? "text-primary"
        : "text-foreground";
  return (
    <div className="rounded-lg border border-border bg-card px-4 py-3">
      <div className="flex items-center gap-2 text-xs font-medium uppercase tracking-wider text-muted-foreground">
        <Icon className="h-3.5 w-3.5" />
        {label}
      </div>
      <div className={`mt-1 text-2xl font-semibold tabular-nums ${valueClass}`}>
        {value}
      </div>
    </div>
  );
}

function ApprovalBoard({
  handoffs,
  dealTasks,
  runs,
  adminPackActive,
  onChanged,
}: {
  handoffs: Handoff[];
  dealTasks: AdminDealTask[];
  runs: ReturnType<typeof useRealEstateHubData>["actionRuns"];
  adminPackActive: boolean;
  onChanged: () => void | Promise<void>;
}) {
  const total = handoffs.length + dealTasks.length + runs.length;
  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between gap-3">
          <CardTitle className="flex items-center gap-2">
            <AlertTriangle className="h-4 w-4 text-warning" />
            Waiting on you
          </CardTitle>
          <Badge variant={total ? "warning" : "outline"}>{total}</Badge>
        </div>
      </CardHeader>
      <CardContent>
        {total === 0 ? (
          <p className="px-1 py-2 text-xs text-muted-foreground/80">
            Nothing waiting on a human — agents will surface items here when they need a decision or input.
          </p>
        ) : (
          <div className="grid gap-3 xl:grid-cols-3">
            <ApprovalColumn label="Handoffs" count={handoffs.length}>
              {handoffs.length === 0 ? (
                <ColumnEmpty>No agent handoffs waiting.</ColumnEmpty>
              ) : (
                handoffs.map((h) => <HandoffRow key={h.id} handoff={h} />)
              )}
            </ApprovalColumn>
            <ApprovalColumn label="Deal tasks" count={dealTasks.length}>
              {!adminPackActive ? (
                <ColumnEmpty>Admin pack not active.</ColumnEmpty>
              ) : dealTasks.length === 0 ? (
                <ColumnEmpty>No transaction tasks need input.</ColumnEmpty>
              ) : (
                dealTasks.slice(0, 8).map((task) => (
                  <DealTaskRow key={task.id} task={task} onChanged={onChanged} />
                ))
              )}
            </ApprovalColumn>
            <ApprovalColumn label="Admin runs" count={runs.length}>
              {runs.length === 0 ? (
                <ColumnEmpty>No admin runs waiting on input.</ColumnEmpty>
              ) : (
                runs.slice(0, 8).map((run) => (
                  <div key={run.id} className="rounded-md border border-border/50 bg-background/40 p-3">
                    <div className="flex items-start justify-between gap-2">
                      <span className="min-w-0 truncate text-sm font-medium text-foreground">
                        {run.registryName || run.skill || "Admin run"}
                      </span>
                      <Badge variant={adminRunStatusVariant(run.status)}>
                        {run.status.replace(/_/g, " ")}
                      </Badge>
                    </div>
                    <div className="mt-1 text-[0.72rem] text-muted-foreground">
                      {isoTimeAgo(run.createdAt)}
                    </div>
                  </div>
                ))
              )}
            </ApprovalColumn>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function ApprovalColumn({
  label,
  count,
  children,
}: {
  label: string;
  count: number;
  children: ReactNode;
}) {
  return (
    <div className="min-w-0">
      <div className="mb-2 flex items-baseline gap-2">
        <h4 className="text-sm font-medium text-foreground">{label}</h4>
        <span className="font-mono-ui text-[0.7rem] tabular-nums text-muted-foreground/80">
          {count}
        </span>
      </div>
      <div className="space-y-2">{children}</div>
    </div>
  );
}

function ColumnEmpty({ children }: { children: React.ReactNode }) {
  return (
    <p className="px-1 py-1 text-xs text-muted-foreground/70">{children}</p>
  );
}

function humanizeAgentId(id: string): string {
  if (!id) return "agent";
  const parts = id.replace(/[_-]+/g, " ").trim().split(/\s+/);
  if (parts.length === 0) return id;
  return parts.map((p, i) => (i === 0 ? p[0].toUpperCase() + p.slice(1) : p)).join(" ");
}

function HandoffRow({ handoff }: { handoff: Handoff }) {
  return (
    <div className="rounded-md border border-border/50 bg-background/40 p-3">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          <div className="truncate text-sm font-medium text-foreground">
            {handoff.title}
          </div>
          <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-[0.72rem] text-muted-foreground">
            <span>{humanizeAgentId(handoff.fromAgentId)}</span>
            <span>→</span>
            <span>{humanizeAgentId(handoff.toAgentId)}</span>
            <span className="text-muted-foreground/70">{isoTimeAgo(handoff.updatedAt)}</span>
          </div>
        </div>
        <Badge variant="warning">waiting</Badge>
      </div>
    </div>
  );
}

function DealTaskRow({
  task,
  onChanged,
}: {
  task: AdminDealTask;
  onChanged: () => void | Promise<void>;
}) {
  const [running, setRunning] = useState(false);
  const runAi = async () => {
    if (!task.canRunWithAi || !task.skill || running) return;
    setRunning(true);
    try {
      await api.runAdminDealTask({
        dealId: task.dealId,
        skill: task.skill,
        title: task.title,
        sourceTaskId: task.id,
        runNow: true,
      });
      await onChanged();
    } finally {
      setRunning(false);
    }
  };

  return (
    <div className="rounded-md border border-border/50 bg-background/40 p-3">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          <div className="flex min-w-0 items-center gap-1.5">
            <span className="truncate text-sm font-medium text-foreground">{task.title}</span>
            {task.canRunWithAi && (
              <Badge variant="success" className="gap-1 px-1.5 py-0">
                <Bot className="h-3 w-3" />
                AI
              </Badge>
            )}
          </div>
          <div className="mt-1 truncate text-[0.72rem] text-muted-foreground">
            {task.dealTitle} · {task.side} · {task.stageName || `Stage ${task.currentStage + 1}`}
          </div>
        </div>
        <Badge variant={adminRunStatusVariant(task.status)}>
          {task.status.replace(/_/g, " ")}
        </Badge>
      </div>
      <div className="mt-2 flex flex-wrap justify-end gap-1.5">
        {task.canRunWithAi && task.skill && task.status === "available" && (
          <Button size="sm" variant="outline" disabled={running} onClick={runAi}>
            {running ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Sparkles className="h-3.5 w-3.5" />
            )}
            Run AI
          </Button>
        )}
        <Link
          to={`/admin?deal=${encodeURIComponent(task.dealId)}`}
          className={cn(buttonVariants({ size: "sm", variant: "ghost" }))}
        >
          Open deal
        </Link>
      </div>
    </div>
  );
}

function InFlightCard({
  worker,
  handoffs,
  runningCount,
}: {
  worker?: AgentHubSnapshot["agentWorker"];
  handoffs?: AgentHubSnapshot["handoffs"];
  runningCount: number;
}) {
  const loopRunning = worker?.loop?.running ?? false;
  const heartbeat = worker?.heartbeat;
  const wake = worker?.wake;
  const queued = handoffs?.queued ?? 0;
  const running = handoffs?.running ?? 0;
  const total = queued + running + runningCount;

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between gap-3">
          <CardTitle className="flex items-center gap-2">
            <Repeat className="h-4 w-4 text-primary" />
            In flight
          </CardTitle>
          <Badge variant={total > 0 ? "secondary" : "outline"}>{total}</Badge>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="grid grid-cols-3 gap-3">
          <Stat label="Queued" value={queued} />
          <Stat label="Running" value={running + runningCount} />
          <Stat label="Wakes" value={wake?.count ?? 0} />
        </div>
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[0.72rem] text-muted-foreground">
          <span className="inline-flex items-center gap-1.5">
            <Dot ok={Boolean(worker?.enabled)} />
            worker {worker?.enabled ? worker?.state : "disabled"}
          </span>
          <span className="inline-flex items-center gap-1.5">
            <Dot ok={loopRunning} />
            loop {loopRunning ? "on" : "off"}
          </span>
          <span className="inline-flex items-center gap-1.5">
            <Dot ok={Boolean(heartbeat?.enabled)} />
            heartbeat
            {heartbeat?.intervalSeconds ? ` ${heartbeat.intervalSeconds}s` : ""}
          </span>
          {worker?.lastError && (
            <span className="text-warning">{worker.lastError}</span>
          )}
        </div>
        {wake?.lastReason && (
          <p className="truncate text-[0.72rem] text-muted-foreground/80">
            Last wake — {wake.lastReason}
          </p>
        )}
      </CardContent>
    </Card>
  );
}

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <div>
      <div className="text-[0.65rem] uppercase tracking-wider text-muted-foreground">
        {label}
      </div>
      <div className="mt-0.5 text-lg font-semibold tabular-nums text-foreground">
        {value}
      </div>
    </div>
  );
}

function Dot({ ok }: { ok: boolean }) {
  return (
    <span
      aria-hidden="true"
      className={`inline-block h-1.5 w-1.5 rounded-full ${ok ? "bg-success" : "bg-warning"}`}
    />
  );
}


```

---
## `src/pages/real-estate-hub/today/day-shape.tsx`
```tsx
import type { DayBucket, HourBucket } from "./data";

export function DayShape({
  hourBuckets,
  dayBuckets,
}: {
  hourBuckets: HourBucket[];
  dayBuckets: DayBucket[];
}) {
  return (
    <section aria-label="Day shape" className="grid gap-3 lg:grid-cols-2">
      <TodayHourly buckets={hourBuckets} />
      <WeekRollup buckets={dayBuckets} />
    </section>
  );
}

function TodayHourly({ buckets }: { buckets: HourBucket[] }) {
  const max = Math.max(1, ...buckets.map((b) => b.leadsIn + b.repliesOut));
  const width = 320;
  const height = 88;
  const padX = 4;
  const stepX = (width - padX * 2) / Math.max(1, buckets.length - 1);
  const leadsLine = buckets
    .map((b, i) => `${padX + i * stepX},${height - (b.leadsIn / max) * (height - 8) - 4}`)
    .join(" ");
  const repliesLine = buckets
    .map((b, i) => `${padX + i * stepX},${height - (b.repliesOut / max) * (height - 8) - 4}`)
    .join(" ");
  const totalLeads = buckets.reduce((sum, b) => sum + b.leadsIn, 0);
  const totalReplies = buckets.reduce((sum, b) => sum + b.repliesOut, 0);
  const noActivity = totalLeads === 0 && totalReplies === 0;

  return (
    <div className="rounded-md border border-border bg-card p-3.5">
      <header className="mb-2 flex items-baseline justify-between gap-3">
        <div>
          <h3 className="text-[0.9rem] font-semibold leading-tight tracking-[-0.005em] text-foreground">
            Today, hour by hour
          </h3>
          <p className="mt-0.5 text-xs text-muted-foreground">
            Inbound vs outbound
          </p>
        </div>
        <div className="flex items-center gap-2.5 text-[0.7rem]">
          <Legend swatch="var(--primary)" label={`${totalLeads} in`} />
          <Legend swatch="var(--muted-foreground)" label={`${totalReplies} out`} />
        </div>
      </header>
      <svg
        aria-hidden="true"
        className="w-full"
        viewBox={`0 0 ${width} ${height}`}
        preserveAspectRatio="none"
      >
        {/* gridlines */}
        {[0.25, 0.5, 0.75].map((p) => (
          <line
            key={p}
            x1={padX}
            x2={width - padX}
            y1={height - p * (height - 8) - 4}
            y2={height - p * (height - 8) - 4}
            stroke="var(--border)"
            strokeDasharray="2 3"
            strokeWidth={0.6}
          />
        ))}
        {!noActivity && (
          <>
            <polyline
              fill="none"
              points={repliesLine}
              stroke="var(--muted-foreground)"
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={1.25}
            />
            <polyline
              fill="none"
              points={leadsLine}
              stroke="var(--primary)"
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={1.75}
            />
          </>
        )}
        {noActivity && (
          <text
            fill="var(--muted-foreground)"
            fontSize={9}
            textAnchor="middle"
            x={width / 2}
            y={height / 2 + 2}
          >
            No activity today yet
          </text>
        )}
      </svg>
      <div className="font-mono-ui mt-1 flex justify-between text-[0.58rem] uppercase tracking-[0.12em] text-muted-foreground">
        {[0, 6, 12, 18, 23].map((h) => (
          <span key={h}>{buckets[h]?.label ?? ""}</span>
        ))}
      </div>
    </div>
  );
}

function WeekRollup({ buckets }: { buckets: DayBucket[] }) {
  const max = Math.max(
    1,
    ...buckets.map((b) => b.leadsIn + b.repliesOut + b.dealsAdvanced),
  );
  const width = 320;
  const height = 88;
  const padX = 6;
  const padY = 4;
  const colCount = buckets.length;
  const colWidth = (width - padX * 2) / colCount;
  const barWidth = Math.max(8, colWidth * 0.6);

  return (
    <div className="rounded-md border border-border bg-card p-3.5">
      <header className="mb-2 flex items-baseline justify-between gap-3">
        <div>
          <h3 className="text-[0.9rem] font-semibold leading-tight tracking-[-0.005em] text-foreground">
            Last 7 days
          </h3>
          <p className="mt-0.5 text-xs text-muted-foreground">
            Leads · replies · deals advanced
          </p>
        </div>
        <div className="flex items-center gap-2.5 text-[0.7rem]">
          <Legend swatch="var(--primary)" label="In" />
          <Legend swatch="var(--muted-foreground)" label="Out" />
          <Legend swatch="var(--success)" label="Deals" />
        </div>
      </header>
      <svg
        aria-hidden="true"
        className="w-full"
        viewBox={`0 0 ${width} ${height}`}
        preserveAspectRatio="none"
      >
        {buckets.map((bucket, i) => {
          const total = bucket.leadsIn + bucket.repliesOut + bucket.dealsAdvanced;
          const colX = padX + i * colWidth + (colWidth - barWidth) / 2;
          const usableHeight = height - padY * 2 - 10;
          const inH = total > 0 ? (bucket.leadsIn / max) * usableHeight : 0;
          const outH = total > 0 ? (bucket.repliesOut / max) * usableHeight : 0;
          const dealH = total > 0 ? (bucket.dealsAdvanced / max) * usableHeight : 0;
          let yCursor = height - padY - 10;
          const inY = yCursor - inH;
          yCursor = inY;
          const outY = yCursor - outH;
          yCursor = outY;
          const dealY = yCursor - dealH;
          const isToday = i === buckets.length - 1;
          return (
            <g key={bucket.iso}>
              {bucket.dealsAdvanced > 0 && (
                <rect
                  x={colX}
                  y={dealY}
                  width={barWidth}
                  height={dealH}
                  fill="var(--success)"
                  opacity={0.85}
                  rx={1}
                />
              )}
              {bucket.repliesOut > 0 && (
                <rect
                  x={colX}
                  y={outY}
                  width={barWidth}
                  height={outH}
                  fill="var(--muted-foreground)"
                  opacity={0.6}
                  rx={1}
                />
              )}
              {bucket.leadsIn > 0 && (
                <rect
                  x={colX}
                  y={inY}
                  width={barWidth}
                  height={inH}
                  fill="var(--primary)"
                  rx={1}
                />
              )}
              <text
                fill={isToday ? "var(--foreground)" : "var(--muted-foreground)"}
                fontFamily="var(--font-mono)"
                fontSize={8}
                fontWeight={isToday ? 600 : 400}
                textAnchor="middle"
                x={colX + barWidth / 2}
                y={height - 1}
              >
                {bucket.label.toUpperCase()}
              </text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}

function Legend({ swatch, label }: { swatch: string; label: string }) {
  return (
    <span className="inline-flex items-center gap-1 text-muted-foreground">
      <span
        aria-hidden="true"
        className="inline-block h-2 w-2 rounded-sm"
        style={{ backgroundColor: swatch }}
      />
      <span className="text-[0.7rem] tabular-nums">{label}</span>
    </span>
  );
}

```

---
## `src/pages/real-estate-hub/today/index.tsx`
```tsx
import { useMemo } from "react";
import { Home } from "lucide-react";
import { HubShell, useHubHeader, useRealEstateHubData } from "../_shared";
import { AdminTaskDrawerProvider } from "../admin-task-drawer";
import { ThreadDrawerProvider } from "../thread-drawer";
import { buildTodayData } from "./data";
import { DayShape } from "./day-shape";
import { PriorityQueue } from "./priority-queue";
import { PulseStrip } from "./pulse-strip";
import { RunningStrip } from "./running-strip";

export function RealEstateTodayPage() {
  const data = useRealEstateHubData();
  useHubHeader("Today", data);

  const view = useMemo(
    () =>
      buildTodayData({
        sourceInbox: data.sourceInbox,
        actionRuns: data.actionRuns,
        dealTasks: data.dealTasks,
        cronJobs: data.cronJobs,
        sessions: data.sessions,
      }),
    [data.sourceInbox, data.actionRuns, data.dealTasks, data.cronJobs, data.sessions],
  );

  return (
    <ThreadDrawerProvider data={data}>
      <AdminTaskDrawerProvider data={data}>
        <HubShell
          data={data}
          eyebrow="Operations"
          icon={Home}
          title="Today"
        >
          <div className="space-y-4">
            <PulseStrip stats={view.pulse} />
            <PriorityQueue items={view.priority} />
            <DayShape hourBuckets={view.hourBuckets} dayBuckets={view.dayBuckets} />
            <RunningStrip scheduled={view.scheduled} live={view.live} running={view.running} />
          </div>
        </HubShell>
      </AdminTaskDrawerProvider>
    </ThreadDrawerProvider>
  );
}

```

---
## `src/pages/real-estate-hub/today/priority-queue.tsx`
```tsx
import { ArrowUpRight, Clock, FileCheck, Flame, ServerCog } from "lucide-react";
import { Link } from "react-router-dom";
import { cn } from "@/lib/utils";
import { useAdminTaskDrawer } from "../admin-task-drawer";
import { useThreadDrawer } from "../thread-drawer";
import type { UrgentItem } from "./data";

const ICON_MAP: Record<UrgentItem["kind"], React.ComponentType<{ className?: string }>> = {
  draft: FileCheck,
  "hot-lead": Flame,
  "deal-task": ServerCog,
  "action-run": ServerCog,
};

const KIND_LABEL: Record<UrgentItem["kind"], string> = {
  draft: "Draft",
  "hot-lead": "Lead",
  "deal-task": "Admin",
  "action-run": "Action",
};

export function PriorityQueue({ items }: { items: UrgentItem[] }) {
  return (
    <section
      aria-label="Needs you now"
      className="rounded-md border border-border bg-card"
    >
      <header className="flex items-baseline justify-between gap-3 border-b border-border px-3.5 py-2.5">
        <div>
          <h2 className="text-[0.95rem] font-semibold leading-tight tracking-[-0.005em] text-foreground">
            Needs you now
          </h2>
          <p className="mt-0.5 text-xs text-muted-foreground">
            {items.length === 0 ? "Inbox is clear" : `${items.length} waiting`}
          </p>
        </div>
        <Link
          to="/leads"
          className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
        >
          Open leads
          <ArrowUpRight className="h-3 w-3" />
        </Link>
      </header>
      {items.length === 0 ? (
        <p className="px-3.5 py-3 text-xs text-muted-foreground/80">
          Nothing waiting on you. Drafts auto-approve when nothing is flagged.
        </p>
      ) : (
        <ul className="divide-y divide-border">
          {items.map((item) => (
            <PriorityRow key={item.id} item={item} />
          ))}
        </ul>
      )}
    </section>
  );
}

function PriorityRow({ item }: { item: UrgentItem }) {
  const Icon = ICON_MAP[item.kind];
  const threadDrawer = useThreadDrawer();
  const adminDrawer = useAdminTaskDrawer();

  const inlineHandler = (() => {
    if ((item.kind === "draft" || item.kind === "hot-lead") && threadDrawer && item.sourceId && item.threadId) {
      const sourceId = item.sourceId;
      const threadId = item.threadId;
      return () => threadDrawer.openThread(sourceId, threadId);
    }
    if (item.kind === "deal-task" && adminDrawer && item.taskId) {
      const taskId = item.taskId;
      return () => adminDrawer.openDealTask(taskId);
    }
    if (item.kind === "action-run" && adminDrawer && item.runId) {
      const runId = item.runId;
      return () => adminDrawer.openActionRun(runId);
    }
    return null;
  })();

  const rowClasses = cn(
    "group flex w-full items-start gap-3 px-3.5 py-2.5 text-left",
    "transition-colors hover:bg-muted/40 focus-visible:bg-muted/40",
    "focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring",
  );

  const inner = (
    <>
      <span
        className={cn(
          "mt-0.5 inline-flex h-6 w-6 shrink-0 items-center justify-center rounded",
          item.tone === "danger" && "bg-destructive/15 text-destructive",
          item.tone === "warn" && "bg-warning/15 text-warning",
          item.tone === "neutral" && "bg-muted text-muted-foreground",
        )}
      >
        <Icon className="h-3.5 w-3.5" />
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex items-baseline justify-between gap-2">
          <span className="truncate text-[0.88rem] font-medium leading-5 text-foreground">
            {item.title}
          </span>
          <span className="font-mono-ui shrink-0 text-[0.6rem] uppercase tracking-[0.14em] text-muted-foreground">
            {KIND_LABEL[item.kind]}
          </span>
        </div>
        <div className="mt-0.5 flex items-center gap-2">
          <span className="truncate text-[0.78rem] leading-4 text-muted-foreground">
            {item.meta}
          </span>
          {item.waitedMinutes != null && (
            <span
              className={cn(
                "font-mono-ui inline-flex shrink-0 items-center gap-0.5 text-[0.62rem] tabular-nums",
                item.tone === "danger" && "text-destructive",
                item.tone === "warn" && "text-warning",
                item.tone === "neutral" && "text-muted-foreground",
              )}
            >
              <Clock className="h-2.5 w-2.5" />
              {formatWait(item.waitedMinutes)}
            </span>
          )}
        </div>
      </div>
    </>
  );

  if (inlineHandler) {
    return (
      <li>
        <button type="button" className={rowClasses} onClick={inlineHandler}>
          {inner}
        </button>
      </li>
    );
  }

  return (
    <li>
      <Link to={item.to} className={rowClasses}>
        {inner}
      </Link>
    </li>
  );
}

function formatWait(minutes: number): string {
  if (minutes < 1) return "now";
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h`;
  const days = Math.floor(hours / 24);
  return `${days}d`;
}

```

---
## `src/pages/real-estate-hub/today/pulse-strip.tsx`
```tsx
import { useMemo } from "react";
import { cn } from "@/lib/utils";
import type { PulseStat } from "./data";

export function PulseStrip({ stats }: { stats: PulseStat[] }) {
  const greeting = useMemo(() => greetingForNow(), []);
  return (
    <section aria-label="Today pulse" className="space-y-3">
      <div className="flex items-baseline justify-between gap-3 px-1">
        <div>
          <h2 className="text-[1.05rem] font-semibold leading-tight tracking-[-0.005em] text-foreground">
            {greeting}
          </h2>
          <p className="mt-0.5 text-xs text-muted-foreground">
            Today at a glance
          </p>
        </div>
      </div>
      <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5">
        {stats.map((stat) => (
          <PulseCard key={stat.label} stat={stat} />
        ))}
      </div>
    </section>
  );
}

function PulseCard({ stat }: { stat: PulseStat }) {
  return (
    <div
      className={cn(
        "flex flex-col gap-2 rounded-md border border-border bg-card px-3 py-2.5",
        "transition-colors",
      )}
    >
      <div className="flex items-center justify-between gap-2">
        <span className="font-mono-ui truncate text-[0.62rem] uppercase tracking-[0.14em] text-muted-foreground">
          {stat.label}
        </span>
        {stat.deltaLabel && (
          <span
            className={cn(
              "font-mono-ui text-[0.62rem] tabular-nums",
              stat.delta == null && "text-muted-foreground",
              stat.delta != null && stat.delta > 0 && "text-success",
              stat.delta != null && stat.delta < 0 && "text-warning",
              stat.delta === 0 && "text-muted-foreground",
            )}
          >
            {stat.deltaLabel}
          </span>
        )}
      </div>
      <div className="flex items-end justify-between gap-2">
        <span
          className={cn(
            "text-[1.4rem] font-semibold leading-none tabular-nums tracking-[-0.01em]",
            stat.tone === "danger" && "text-destructive",
            stat.tone === "warn" && "text-warning",
            stat.tone === "good" && "text-foreground",
            stat.tone === "neutral" && "text-foreground",
          )}
        >
          {stat.value}
        </span>
        <Sparkline values={stat.spark} tone={stat.tone} />
      </div>
    </div>
  );
}

function Sparkline({ values, tone }: { values: number[]; tone: PulseStat["tone"] }) {
  const width = 64;
  const height = 20;
  const safe = values.length > 0 ? values : [0];
  const max = Math.max(1, ...safe);
  const stepX = safe.length > 1 ? width / (safe.length - 1) : width;
  const points = safe
    .map((v, i) => {
      const x = safe.length === 1 ? width / 2 : i * stepX;
      const y = height - (v / max) * (height - 2) - 1;
      return `${x.toFixed(2)},${y.toFixed(2)}`;
    })
    .join(" ");
  const areaPoints = `0,${height} ${points} ${width},${height}`;
  const stroke =
    tone === "danger"
      ? "var(--destructive)"
      : tone === "warn"
        ? "var(--warning)"
        : tone === "good"
          ? "var(--success)"
          : "var(--muted-foreground)";
  return (
    <svg
      aria-hidden="true"
      className="shrink-0"
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      width={width}
    >
      <polygon fill={stroke} opacity={0.12} points={areaPoints} />
      <polyline fill="none" points={points} stroke={stroke} strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.25} />
    </svg>
  );
}

function greetingForNow(): string {
  const hour = new Date().getHours();
  if (hour < 5) return "Late night";
  if (hour < 12) return "Good morning";
  if (hour < 17) return "Good afternoon";
  if (hour < 21) return "Good evening";
  return "Late night";
}

```

---
## `src/pages/real-estate-hub/today/running-strip.tsx`
```tsx
import { Activity, CalendarClock, MessageSquare } from "lucide-react";
import { Link } from "react-router-dom";
import type { AdminActionRun, CronJob, SessionInfo } from "@/lib/api";
import { isoTimeAgo, timeAgo } from "@/lib/utils";
import { sessionTitle } from "../_shared/agent-widgets";
import { cn } from "@/lib/utils";

export function RunningStrip({
  scheduled,
  live,
  running,
}: {
  scheduled: CronJob[];
  live: SessionInfo[];
  running: AdminActionRun[];
}) {
  return (
    <section aria-label="What's running" className="grid gap-3 lg:grid-cols-2">
      <ScheduledCard jobs={scheduled} />
      <LiveCard live={live} running={running} />
    </section>
  );
}

function ScheduledCard({ jobs }: { jobs: CronJob[] }) {
  return (
    <Card
      icon={CalendarClock}
      title="Scheduled · next 24h"
      meta={jobs.length === 0 ? "Nothing queued" : `${jobs.length} upcoming`}
      to="/cron"
    >
      {jobs.length === 0 ? (
        <EmptyRow message="No timed tasks set to fire today." />
      ) : (
        <ul className="divide-y divide-border">
          {jobs.map((job) => (
            <li key={job.id} className="flex items-start gap-2.5 px-3 py-2">
              <span className="mt-0.5 inline-flex h-1.5 w-1.5 shrink-0 rounded-full bg-primary" />
              <div className="min-w-0 flex-1">
                <div className="truncate text-[0.85rem] leading-5 text-foreground">
                  {job.name || job.prompt.slice(0, 80)}
                </div>
                <div className="font-mono-ui mt-0.5 truncate text-[0.6rem] uppercase tracking-[0.12em] text-muted-foreground">
                  {job.next_run_at ? `Fires ${isoTimeAgo(job.next_run_at)}` : job.schedule_display}
                </div>
              </div>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

function LiveCard({ live, running }: { live: SessionInfo[]; running: AdminActionRun[] }) {
  const total = live.length + running.length;
  return (
    <Card
      icon={Activity}
      title="In flight"
      meta={total === 0 ? "Idle" : `${total} running`}
      to="/tasks"
    >
      {total === 0 ? (
        <EmptyRow message="No live sessions or running actions." />
      ) : (
        <ul className="divide-y divide-border">
          {live.map((session) => (
            <li key={`s-${session.id}`} className="flex items-start gap-2.5 px-3 py-2">
              <span className="mt-0.5 inline-flex h-1.5 w-1.5 shrink-0 rounded-full bg-success" />
              <div className="min-w-0 flex-1">
                <div className="flex items-baseline gap-1.5">
                  <MessageSquare className="h-3 w-3 shrink-0 text-muted-foreground" />
                  <Link
                    to={`/chat?resume=${encodeURIComponent(session.id)}`}
                    className="truncate text-[0.85rem] leading-5 text-foreground hover:underline"
                  >
                    {sessionTitle(session)}
                  </Link>
                </div>
                <div className="font-mono-ui mt-0.5 truncate text-[0.6rem] uppercase tracking-[0.12em] text-muted-foreground">
                  Active {timeAgo(session.last_active)}
                </div>
              </div>
            </li>
          ))}
          {running.map((run) => (
            <li key={`r-${run.id}`} className="flex items-start gap-2.5 px-3 py-2">
              <span
                className={cn(
                  "mt-0.5 inline-flex h-1.5 w-1.5 shrink-0 rounded-full",
                  run.status === "running" || run.status === "in_progress"
                    ? "bg-warning animate-pulse"
                    : "bg-muted-foreground",
                )}
              />
              <div className="min-w-0 flex-1">
                <div className="truncate text-[0.85rem] leading-5 text-foreground">
                  {run.registryName || run.skill || "Action run"}
                </div>
                <div className="font-mono-ui mt-0.5 truncate text-[0.6rem] uppercase tracking-[0.12em] text-muted-foreground">
                  {run.status}
                  {run.startedAt ? ` · ${isoTimeAgo(run.startedAt)}` : ""}
                </div>
              </div>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

function Card({
  icon: Icon,
  title,
  meta,
  to,
  children,
}: {
  icon: React.ComponentType<{ className?: string }>;
  title: string;
  meta: string;
  to: string;
  children: React.ReactNode;
}) {
  return (
    <div className="rounded-md border border-border bg-card">
      <header className="flex items-baseline justify-between gap-3 border-b border-border px-3 py-2">
        <div className="flex items-baseline gap-2">
          <Icon className="h-3.5 w-3.5 self-center text-muted-foreground" />
          <h3 className="text-[0.85rem] font-semibold leading-tight tracking-[-0.005em] text-foreground">
            {title}
          </h3>
          <span className="font-mono-ui text-[0.6rem] uppercase tracking-[0.12em] text-muted-foreground">
            {meta}
          </span>
        </div>
        <Link
          to={to}
          className="text-xs text-muted-foreground hover:text-foreground"
        >
          Open
        </Link>
      </header>
      {children}
    </div>
  );
}

function EmptyRow({ message }: { message: string }) {
  return <p className="px-3 py-2 text-xs text-muted-foreground/80">{message}</p>;
}

```

---
## `src/pages/real-estate-hub/today/data.ts`
```ts
import type {
  AdminActionRun,
  AdminDealTask,
  CronJob,
  SessionInfo,
  SourceInboxDraft,
  SourceInboxResponse,
  SourceInboxThread,
} from "@/lib/api";

const HOUR_MS = 60 * 60 * 1000;
const DAY_MS = 24 * HOUR_MS;

export type HourBucket = {
  hour: number;
  label: string;
  leadsIn: number;
  repliesOut: number;
};

export type DayBucket = {
  iso: string;
  label: string;
  leadsIn: number;
  repliesOut: number;
  dealsAdvanced: number;
};

export type PulseStat = {
  label: string;
  value: string;
  rawValue: number;
  delta: number | null;
  deltaLabel: string | null;
  spark: number[];
  tone: "neutral" | "good" | "warn" | "danger";
};

export type UrgentItem = {
  id: string;
  kind: "draft" | "hot-lead" | "deal-task" | "action-run";
  title: string;
  meta: string;
  waitedMinutes: number | null;
  tone: "neutral" | "warn" | "danger";
  to: string;
  sourceId?: string;
  threadId?: string;
  taskId?: string;
  runId?: string;
};

function parseTs(value: string | null | undefined): number | null {
  if (!value) return null;
  const t = Date.parse(value);
  return Number.isFinite(t) ? t : null;
}

function startOfLocalDay(d = new Date()): number {
  const x = new Date(d);
  x.setHours(0, 0, 0, 0);
  return x.getTime();
}

function isSameLocalDay(a: number, b: number): boolean {
  return startOfLocalDay(new Date(a)) === startOfLocalDay(new Date(b));
}

export function bucketThreadsByHour(threads: SourceInboxThread[]): HourBucket[] {
  const todayStart = startOfLocalDay();
  const buckets: HourBucket[] = Array.from({ length: 24 }, (_, hour) => ({
    hour,
    label: hour === 0 ? "12a" : hour === 12 ? "12p" : hour < 12 ? `${hour}a` : `${hour - 12}p`,
    leadsIn: 0,
    repliesOut: 0,
  }));

  for (const thread of threads) {
    const ts = parseTs(thread.latestAt);
    if (ts == null || ts < todayStart) continue;
    const hour = new Date(ts).getHours();
    const bucket = buckets[hour];
    if (!bucket) continue;
    if (thread.direction === "inbound") bucket.leadsIn += 1;
    else if (thread.direction === "outbound") bucket.repliesOut += 1;
  }

  return buckets;
}

export function bucketThreadsByDay(
  threads: SourceInboxThread[],
  actionRuns: AdminActionRun[] = [],
): DayBucket[] {
  const dayLabels = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
  const today = startOfLocalDay();
  const buckets: DayBucket[] = [];
  for (let i = 6; i >= 0; i -= 1) {
    const dayStart = today - i * DAY_MS;
    const d = new Date(dayStart);
    buckets.push({
      iso: d.toISOString().slice(0, 10),
      label: dayLabels[d.getDay()] ?? "",
      leadsIn: 0,
      repliesOut: 0,
      dealsAdvanced: 0,
    });
  }

  const bucketFor = (ts: number): DayBucket | null => {
    const idx = buckets.findIndex((b) => isSameLocalDay(Date.parse(`${b.iso}T12:00:00`), ts));
    return idx >= 0 ? buckets[idx]! : null;
  };

  for (const thread of threads) {
    const ts = parseTs(thread.latestAt);
    if (ts == null) continue;
    const bucket = bucketFor(ts);
    if (!bucket) continue;
    if (thread.direction === "inbound") bucket.leadsIn += 1;
    else if (thread.direction === "outbound") bucket.repliesOut += 1;
  }

  for (const run of actionRuns) {
    const completed = parseTs(run.completedAt);
    if (completed == null) continue;
    if (run.status !== "completed" && run.status !== "success" && run.status !== "approved") continue;
    const bucket = bucketFor(completed);
    if (bucket) bucket.dealsAdvanced += 1;
  }

  return buckets;
}

function activityForDay(threads: SourceInboxThread[], dayStart: number) {
  const dayEnd = dayStart + DAY_MS;
  let leadsIn = 0;
  let repliesOut = 0;
  let waiting = 0;
  const responseTimes: number[] = [];
  for (const thread of threads) {
    const ts = parseTs(thread.latestAt);
    if (ts == null) continue;
    if (ts < dayStart || ts >= dayEnd) continue;
    if (thread.direction === "inbound") {
      leadsIn += 1;
      if (thread.status === "open") waiting += 1;
    } else if (thread.direction === "outbound") {
      repliesOut += 1;
    }
  }
  return { leadsIn, repliesOut, waiting, responseTimes };
}

function fmtDelta(today: number, yesterday: number): { delta: number | null; label: string | null } {
  if (yesterday === 0 && today === 0) return { delta: null, label: null };
  if (yesterday === 0) return { delta: today, label: `+${today}` };
  const diff = today - yesterday;
  if (diff === 0) return { delta: 0, label: "flat" };
  return { delta: diff, label: diff > 0 ? `+${diff}` : `${diff}` };
}

export function computePulseStats(
  threads: SourceInboxThread[],
  drafts: SourceInboxDraft[],
  hourBuckets: HourBucket[],
  dayBuckets: DayBucket[],
): PulseStat[] {
  const todayStart = startOfLocalDay();
  const yesterdayStart = todayStart - DAY_MS;
  const today = activityForDay(threads, todayStart);
  const yesterday = activityForDay(threads, yesterdayStart);

  const pendingDraftsCount = drafts.filter((d) => d.status === "pending").length;
  const waitingDelta = fmtDelta(today.waiting, yesterday.waiting);
  const responseMinutes = medianResponseMinutes(threads, todayStart);
  const responseMinutesYesterday = medianResponseMinutes(threads, yesterdayStart);
  const responseDelta = responseMinutes != null && responseMinutesYesterday != null
    ? { delta: responseMinutes - responseMinutesYesterday, label: `${responseMinutes - responseMinutesYesterday > 0 ? "+" : ""}${responseMinutes - responseMinutesYesterday}m` }
    : { delta: null as number | null, label: null as string | null };

  const dayLeadsIn = dayBuckets.map((b) => b.leadsIn);
  const dayRepliesOut = dayBuckets.map((b) => b.repliesOut);
  const todayHourly = hourBuckets.map((b) => b.leadsIn + b.repliesOut);
  const draftsSpark = drafts.slice(-7).map(() => pendingDraftsCount);

  const inDelta = fmtDelta(today.leadsIn, yesterday.leadsIn);
  const outDelta = fmtDelta(today.repliesOut, yesterday.repliesOut);

  return [
    {
      label: "Leads in today",
      value: String(today.leadsIn),
      rawValue: today.leadsIn,
      delta: inDelta.delta,
      deltaLabel: inDelta.label,
      spark: dayLeadsIn,
      tone: "neutral",
    },
    {
      label: "Replies out today",
      value: String(today.repliesOut),
      rawValue: today.repliesOut,
      delta: outDelta.delta,
      deltaLabel: outDelta.label,
      spark: dayRepliesOut,
      tone: today.repliesOut === 0 && today.leadsIn > 0 ? "warn" : "neutral",
    },
    {
      label: "Drafts waiting",
      value: String(pendingDraftsCount),
      rawValue: pendingDraftsCount,
      delta: null,
      deltaLabel: null,
      spark: draftsSpark.length ? draftsSpark : todayHourly,
      tone: pendingDraftsCount >= 5 ? "warn" : pendingDraftsCount > 0 ? "neutral" : "good",
    },
    {
      label: "Threads waiting on you",
      value: String(today.waiting),
      rawValue: today.waiting,
      delta: waitingDelta.delta,
      deltaLabel: waitingDelta.label,
      spark: dayLeadsIn,
      tone: today.waiting >= 5 ? "danger" : today.waiting > 0 ? "warn" : "good",
    },
    {
      label: "Median response",
      value: responseMinutes != null ? `${responseMinutes}m` : "—",
      rawValue: responseMinutes ?? 0,
      delta: responseDelta.delta,
      deltaLabel: responseDelta.label,
      spark: todayHourly,
      tone: responseMinutes != null && responseMinutes >= 30 ? "danger" : responseMinutes != null && responseMinutes >= 10 ? "warn" : "good",
    },
  ];
}

function medianResponseMinutes(threads: SourceInboxThread[], dayStart: number): number | null {
  const dayEnd = dayStart + DAY_MS;
  const samples: number[] = [];
  for (const thread of threads) {
    const ts = parseTs(thread.latestAt);
    if (ts == null) continue;
    if (ts < dayStart || ts >= dayEnd) continue;
    if (thread.direction !== "outbound") continue;
    if (thread.inboundCount === 0) continue;
    const proxy = Math.max(1, Math.round(((thread.outboundCount || 1) > 0 ? 5 : 30)));
    samples.push(proxy);
  }
  if (!samples.length) return null;
  samples.sort((a, b) => a - b);
  const mid = Math.floor(samples.length / 2);
  return samples.length % 2 === 0 ? Math.round((samples[mid - 1]! + samples[mid]!) / 2) : samples[mid]!;
}

export function pendingDrafts(drafts: SourceInboxDraft[]): SourceInboxDraft[] {
  return drafts.filter((d) => d.status === "pending");
}

export function hotLeadsWaiting(threads: SourceInboxThread[]): SourceInboxThread[] {
  return threads.filter(
    (t) => t.status === "open" && t.direction === "inbound" && (t.heatLabel === "hot" || t.heatLabel === "warm"),
  );
}

export function urgentAdminTasks(
  dealTasks: AdminDealTask[],
  actionRuns: AdminActionRun[],
): UrgentItem[] {
  const now = Date.now();
  const items: UrgentItem[] = [];

  for (const task of dealTasks) {
    if (task.status === "done" || task.status === "completed") continue;
    const updated = parseTs(task.updatedAt) ?? parseTs(task.createdAt);
    const waited = updated ? Math.round((now - updated) / 60000) : null;
    const tone: UrgentItem["tone"] = waited != null && waited > 60 * 24 ? "danger" : waited != null && waited > 60 * 4 ? "warn" : "neutral";
    items.push({
      id: `task-${task.id}`,
      kind: "deal-task",
      title: task.title,
      meta: `${task.dealTitle} · ${task.stageName}`,
      waitedMinutes: waited,
      tone,
      to: "/admin",
      taskId: task.id,
    });
  }

  for (const run of actionRuns) {
    if (run.status === "completed" || run.status === "success") continue;
    if (run.status !== "needs_input" && run.status !== "blocked" && run.status !== "error" && run.status !== "failed") continue;
    const updated = parseTs(run.updatedAt) ?? parseTs(run.createdAt);
    const waited = updated ? Math.round((now - updated) / 60000) : null;
    const tone: UrgentItem["tone"] = run.status === "error" || run.status === "failed" ? "danger" : "warn";
    items.push({
      id: `run-${run.id}`,
      kind: "action-run",
      title: run.registryName || run.skill || "Action run",
      meta: run.errorMessage ? run.errorMessage.slice(0, 80) : `${run.status}`,
      waitedMinutes: waited,
      tone,
      to: "/admin",
      runId: run.id,
    });
  }

  return items
    .sort((a, b) => (b.waitedMinutes ?? 0) - (a.waitedMinutes ?? 0))
    .slice(0, 6);
}

export function priorityQueue({
  drafts,
  threads,
  dealTasks,
  actionRuns,
}: {
  drafts: SourceInboxDraft[];
  threads: SourceInboxThread[];
  dealTasks: AdminDealTask[];
  actionRuns: AdminActionRun[];
}): UrgentItem[] {
  const now = Date.now();
  const items: UrgentItem[] = [];

  for (const draft of pendingDrafts(drafts)) {
    const ts = parseTs(draft.latestAt);
    const waited = ts ? Math.round((now - ts) / 60000) : null;
    const tone: UrgentItem["tone"] = waited != null && waited > 60 * 6 ? "danger" : waited != null && waited > 60 ? "warn" : "neutral";
    items.push({
      id: `draft-${draft.id}`,
      kind: "draft",
      title: `Approve reply to ${draft.personName || "lead"}`,
      meta: draft.draftText?.slice(0, 90) || draft.title || "Draft ready",
      waitedMinutes: waited,
      tone,
      to: "/leads",
      sourceId: draft.sourceId,
      threadId: draft.threadId,
    });
  }

  for (const thread of hotLeadsWaiting(threads)) {
    const ts = parseTs(thread.latestAt);
    const waited = ts ? Math.round((now - ts) / 60000) : null;
    const tone: UrgentItem["tone"] = thread.heatLabel === "hot" ? "danger" : "warn";
    items.push({
      id: `thread-${thread.id}`,
      kind: "hot-lead",
      title: `${thread.heatLabel === "hot" ? "Hot" : "Warm"} lead: ${thread.personName}`,
      meta: thread.latestText?.slice(0, 90) || `${thread.channel} thread`,
      waitedMinutes: waited,
      tone,
      to: "/leads",
      sourceId: thread.sourceId,
      threadId: thread.threadId,
    });
  }

  for (const urgent of urgentAdminTasks(dealTasks, actionRuns)) {
    items.push(urgent);
  }

  return items
    .sort((a, b) => {
      const order: Record<UrgentItem["tone"], number> = { danger: 0, warn: 1, neutral: 2 };
      if (order[a.tone] !== order[b.tone]) return order[a.tone] - order[b.tone];
      return (b.waitedMinutes ?? 0) - (a.waitedMinutes ?? 0);
    })
    .slice(0, 8);
}

export function scheduledNext24h(jobs: CronJob[]): CronJob[] {
  const now = Date.now();
  const horizon = now + DAY_MS;
  return jobs
    .filter((job) => {
      if (!job.enabled) return false;
      const t = parseTs(job.next_run_at);
      return t != null && t >= now && t <= horizon;
    })
    .sort((a, b) => (parseTs(a.next_run_at) ?? 0) - (parseTs(b.next_run_at) ?? 0))
    .slice(0, 6);
}

export function liveSessions(sessions: SessionInfo[]): SessionInfo[] {
  return sessions.filter((s) => s.is_active).slice(0, 5);
}

export function inFlightRuns(actionRuns: AdminActionRun[]): AdminActionRun[] {
  return actionRuns
    .filter((r) => r.status === "running" || r.status === "in_progress" || r.status === "pending")
    .sort((a, b) => (parseTs(b.startedAt ?? b.createdAt) ?? 0) - (parseTs(a.startedAt ?? a.createdAt) ?? 0))
    .slice(0, 5);
}

export function buildTodayData(input: {
  sourceInbox: SourceInboxResponse | null;
  actionRuns: AdminActionRun[];
  dealTasks: AdminDealTask[];
  cronJobs: CronJob[];
  sessions: SessionInfo[];
}) {
  const threads = input.sourceInbox?.threads ?? [];
  const drafts = input.sourceInbox?.drafts ?? [];
  const hourBuckets = bucketThreadsByHour(threads);
  const dayBuckets = bucketThreadsByDay(threads, input.actionRuns);
  return {
    pulse: computePulseStats(threads, drafts, hourBuckets, dayBuckets),
    hourBuckets,
    dayBuckets,
    priority: priorityQueue({
      drafts,
      threads,
      dealTasks: input.dealTasks,
      actionRuns: input.actionRuns,
    }),
    scheduled: scheduledNext24h(input.cronJobs),
    live: liveSessions(input.sessions),
    running: inFlightRuns(input.actionRuns),
  };
}

```

---
## `src/pages/real-estate-hub/admin-task-drawer.tsx`
```tsx
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { createPortal } from "react-dom";
import { Link } from "react-router-dom";
import { ExternalLink, Loader2, X as CloseIcon } from "lucide-react";
import { api } from "@/lib/api";
import type { AdminActionRun, AdminDealTask } from "@/lib/api";
import type { HubData } from "./_shared/types";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

type AdminTaskTarget =
  | { kind: "deal-task"; id: string }
  | { kind: "action-run"; id: string }
  | null;

const AdminTaskDrawerContext = createContext<{
  openDealTask: (taskId: string) => void;
  openActionRun: (runId: string) => void;
} | null>(null);

export function useAdminTaskDrawer() {
  return useContext(AdminTaskDrawerContext);
}

export function AdminTaskDrawerProvider({
  children,
  data,
}: {
  children: ReactNode;
  data: HubData;
}) {
  const [target, setTarget] = useState<AdminTaskTarget>(null);
  const openDealTask = useCallback((id: string) => setTarget({ kind: "deal-task", id }), []);
  const openActionRun = useCallback((id: string) => setTarget({ kind: "action-run", id }), []);
  const close = useCallback(() => setTarget(null), []);
  const ctx = useMemo(() => ({ openDealTask, openActionRun }), [openDealTask, openActionRun]);
  return (
    <AdminTaskDrawerContext.Provider value={ctx}>
      {children}
      {target && <AdminTaskDialog data={data} target={target} onClose={close} />}
    </AdminTaskDrawerContext.Provider>
  );
}

function AdminTaskDialog({
  data,
  target,
  onClose,
}: {
  data: HubData;
  target: NonNullable<AdminTaskTarget>;
  onClose: () => void;
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = prev;
    };
  }, [onClose]);

  const task: AdminDealTask | null = useMemo(() => {
    if (target.kind !== "deal-task") return null;
    return data.dealTasks.find((t) => t.id === target.id) ?? null;
  }, [data.dealTasks, target]);

  const run: AdminActionRun | null = useMemo(() => {
    if (target.kind !== "action-run") return null;
    return data.actionRuns.find((r) => r.id === target.id) ?? null;
  }, [data.actionRuns, target]);

  return createPortal(
    <div
      role="dialog"
      aria-modal="true"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 px-4 py-6 animate-[fade-in_120ms_ease-out]"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        className="flex max-h-[85vh] w-full max-w-xl flex-col rounded-lg border border-border bg-background shadow-[0_24px_90px_rgba(0,0,0,0.32)]"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-3 border-b border-border px-5 py-4">
          <div className="min-w-0">
            <div className="font-mono-ui text-[0.6rem] uppercase tracking-[0.14em] text-muted-foreground">
              {target.kind === "deal-task" ? "Deal task" : "Action run"}
            </div>
            <div className="mt-1 truncate text-[1.02rem] font-semibold leading-tight text-foreground">
              {task?.title || run?.registryName || run?.skill || "Loading..."}
            </div>
          </div>
          <Button variant="ghost" size="sm" onClick={onClose} className="text-foreground/75 hover:text-foreground">
            <CloseIcon className="h-4 w-4" />
          </Button>
        </div>

        <div className="flex-1 overflow-y-auto px-5 py-4 text-sm leading-5">
          {task && <DealTaskBody task={task} data={data} onClose={onClose} />}
          {run && <ActionRunBody run={run} data={data} onClose={onClose} />}
          {!task && !run && (
            <p className="text-xs text-muted-foreground/80">
              This item is no longer in the active queue. It may have been completed or moved.
            </p>
          )}
        </div>

        <div className="flex items-center justify-between gap-3 border-t border-border px-5 py-3">
          <Link
            to="/admin"
            onClick={onClose}
            className="inline-flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground"
          >
            Open in admin
            <ExternalLink className="h-3 w-3" />
          </Link>
          <Button variant="ghost" size="sm" onClick={onClose}>
            Close
          </Button>
        </div>
      </div>
    </div>,
    document.body,
  );
}

function DealTaskBody({
  task,
  data,
  onClose,
}: {
  task: AdminDealTask;
  data: HubData;
  onClose: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const runWithAi = useCallback(async () => {
    if (!task.skill) return;
    setBusy(true);
    setError(null);
    try {
      await api.runAdminDealTask({
        dealId: task.dealId,
        skill: task.skill,
        title: task.title,
        sourceTaskId: task.id,
        runNow: true,
      });
      await data.refresh();
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }, [data, onClose, task]);

  return (
    <div className="space-y-3">
      <DetailRow label="Deal" value={task.dealTitle} />
      <DetailRow label="Stage" value={task.stageName} />
      {task.skill && <DetailRow label="Skill" value={task.skill} mono />}
      {task.description && (
        <div>
          <div className="font-mono-ui mb-1 text-[0.6rem] uppercase tracking-[0.14em] text-muted-foreground">
            Description
          </div>
          <p className="whitespace-pre-wrap text-[0.85rem] text-foreground/90">{task.description}</p>
        </div>
      )}
      <DetailRow label="Status" value={task.status} mono />

      {error && (
        <div className="rounded-md border border-destructive/55 bg-destructive/10 px-3 py-2 text-xs font-medium text-destructive">
          {error}
        </div>
      )}

      {task.canRunWithAi && task.skill && task.status !== "done" && task.status !== "completed" && (
        <div className="pt-2">
          <Button size="sm" onClick={() => void runWithAi()} disabled={busy}>
            {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
            Run with AI
          </Button>
        </div>
      )}
    </div>
  );
}

function ActionRunBody({
  run,
  data,
  onClose,
}: {
  run: AdminActionRun;
  data: HubData;
  onClose: () => void;
}) {
  const [busy, setBusy] = useState<"approve" | "cancel" | null>(null);
  const [error, setError] = useState<string | null>(null);

  const act = useCallback(
    async (approved: boolean) => {
      setBusy(approved ? "approve" : "cancel");
      setError(null);
      try {
        await api.approveAdminActionRun(run.id, { approved, runNow: approved });
        await data.refresh();
        onClose();
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      } finally {
        setBusy(null);
      }
    },
    [data, onClose, run.id],
  );

  const canAct =
    run.status === "needs_input" ||
    run.status === "blocked" ||
    run.status === "error" ||
    run.status === "failed";

  return (
    <div className="space-y-3">
      <DetailRow label="Status" value={run.status} mono tone={run.status === "error" || run.status === "failed" ? "danger" : run.status === "needs_input" ? "warn" : "neutral"} />
      {run.registryName && <DetailRow label="Action" value={run.registryName} />}
      {run.skill && <DetailRow label="Skill" value={run.skill} mono />}
      {run.errorMessage && (
        <div>
          <div className="font-mono-ui mb-1 text-[0.6rem] uppercase tracking-[0.14em] text-muted-foreground">
            Error
          </div>
          <p className="whitespace-pre-wrap rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-[0.82rem] text-destructive">
            {run.errorMessage}
          </p>
        </div>
      )}

      {error && (
        <div className="rounded-md border border-destructive/55 bg-destructive/10 px-3 py-2 text-xs font-medium text-destructive">
          {error}
        </div>
      )}

      {canAct && (
        <div className="flex flex-wrap gap-2 pt-2">
          <Button size="sm" onClick={() => void act(true)} disabled={busy !== null}>
            {busy === "approve" ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
            Approve &amp; run
          </Button>
          <Button
            size="sm"
            variant="ghost"
            onClick={() => void act(false)}
            disabled={busy !== null}
            className="text-foreground/75 hover:text-foreground"
          >
            {busy === "cancel" ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
            Cancel
          </Button>
        </div>
      )}
    </div>
  );
}

function DetailRow({
  label,
  value,
  mono,
  tone,
}: {
  label: string;
  value: string;
  mono?: boolean;
  tone?: "warn" | "danger" | "neutral";
}) {
  return (
    <div className="flex items-baseline gap-3">
      <div className="font-mono-ui min-w-[5.5rem] text-[0.6rem] uppercase tracking-[0.14em] text-muted-foreground">
        {label}
      </div>
      <div
        className={cn(
          "flex-1 text-[0.85rem] text-foreground/90",
          mono && "font-mono-ui",
          tone === "warn" && "text-warning",
          tone === "danger" && "text-destructive",
        )}
      >
        {value}
      </div>
    </div>
  );
}

```

---
## `src/pages/real-estate-hub/social-media-widgets.tsx`
```tsx
import {
  forwardRef,
  useCallback,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent as ReactKeyboardEvent,
  type MouseEvent as ReactMouseEvent,
} from "react";
import {
  Activity,
  Clock,
  ExternalLink,
  Loader2,
  PencilLine,
  ThumbsDown,
  ThumbsUp,
  Video,
} from "lucide-react";
import type { SocialIdea, SocialMetricRow, SocialPlatformBlock } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { cn, isoTimeAgo } from "@/lib/utils";

export function formatCompact(n: number | null | undefined): string {
  if (n == null || !Number.isFinite(n)) return "—";
  const abs = Math.abs(n);
  if (abs >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (abs >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
  return String(Math.round(n));
}

export function formatPct(n: number | null | undefined, digits = 1): string {
  if (n == null || !Number.isFinite(n)) return "—";
  return `${(n * 100).toFixed(digits)}%`;
}

// Total/cumulative time fields — show as hours. Returned in ms unless noted.
const MS_TOTAL_TIME_KEYS = new Set([
  "ig_reels_video_view_total_time",
  "post_video_view_time_organic",
]);
const MIN_TOTAL_TIME_KEYS = new Set([
  "estimated_minutes_watched", // YouTube — minutes
]);
// Per-view averages — show as seconds (hours would be too small to read).
const MS_AVG_TIME_KEYS = new Set([
  "ig_reels_avg_watch_time",
  "post_video_avg_time_watched",
]);
const SEC_AVG_TIME_KEYS = new Set([
  "avg_view_duration_sec",
]);
const PCT_KEYS = new Set([
  "engagement_rate",
  "hook_rate",
  "hold_rate",
  "avg_view_percentage",
]);

function formatHours(ms: number): string {
  if (!Number.isFinite(ms) || ms <= 0) return "0h";
  const h = ms / 3_600_000;
  if (h >= 100) return `${h.toFixed(0)}h`;
  if (h >= 10) return `${h.toFixed(1)}h`;
  if (h >= 1) return `${h.toFixed(2)}h`;
  // Sub-hour totals — degrade gracefully so we never claim "0h" on a real value.
  const m = ms / 60_000;
  if (m >= 1) return `${m.toFixed(1)}m`;
  return `${(ms / 1000).toFixed(1)}s`;
}

function formatSeconds(ms: number): string {
  if (!Number.isFinite(ms) || ms < 0) return "0s";
  const s = ms / 1000;
  if (s < 60) return `${s.toFixed(1)}s`;
  const m = Math.floor(s / 60);
  const rem = Math.round(s - m * 60);
  return rem ? `${m}m ${rem}s` : `${m}m`;
}

function formatIsoDuration(iso: string): string {
  // PT#H#M#S → "1h 23m 4s"
  const re = /PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?/;
  const m = iso.match(re);
  if (!m) return iso;
  const [, h, mm, s] = m;
  const parts: string[] = [];
  if (h) parts.push(`${h}h`);
  if (mm) parts.push(`${mm}m`);
  if (s) parts.push(`${Math.round(Number(s))}s`);
  return parts.join(" ") || "0s";
}

function prettifyMetricKey(key: string): string {
  const map: Record<string, string> = {
    likes: "likes",
    comments: "comments",
    shares: "shares",
    saved: "saves",
    views: "views",
    reach: "reach",
    plays: "plays",
    impressions: "impressions",
    total_interactions: "total interactions",
    profile_visits: "profile visits",
    profile_activity: "profile activity",
    follows: "follows",
    navigation: "navigation",
    replies: "replies",
    ig_reels_video_view_total_time: "total watch time",
    ig_reels_avg_watch_time: "avg watch time",
    post_video_view_time_organic: "total watch time",
    post_video_avg_time_watched: "avg watch time",
    avg_view_duration_sec: "avg watch time",
    avg_view_percentage: "avg view %",
    estimated_minutes_watched: "total watch time",
    duration_iso: "duration",
    view_count: "views",
    like_count: "likes",
    comment_count: "comments",
    dislike_count: "dislikes",
    favorite_count: "favorites",
    engagement_rate: "engagement rate",
    hook_rate: "hook rate",
    hold_rate: "hold rate",
  };
  return map[key] ?? key.replace(/_/g, " ");
}

function formatMetricValue(key: string, value: unknown): string {
  if (value == null) return "—";
  if (typeof value === "string") {
    if (key === "duration_iso" && value.startsWith("PT")) return formatIsoDuration(value);
    return value;
  }
  if (typeof value !== "number" || !Number.isFinite(value)) return String(value);
  if (PCT_KEYS.has(key)) return `${(value * 100).toFixed(1)}%`;
  if (MS_TOTAL_TIME_KEYS.has(key)) return formatHours(value);
  if (MIN_TOTAL_TIME_KEYS.has(key)) return formatHours(value * 60_000);
  if (MS_AVG_TIME_KEYS.has(key)) return formatSeconds(value);
  if (SEC_AVG_TIME_KEYS.has(key)) return formatSeconds(value * 1000);
  return formatCompact(value);
}

function platformDot(platform: string): string {
  const map: Record<string, string> = {
    instagram: "bg-[oklch(0.62_0.14_350)]",
    tiktok: "bg-[oklch(0.65_0.13_15)]",
    youtube: "bg-[oklch(0.58_0.16_30)]",
    facebook: "bg-[oklch(0.58_0.13_245)]",
    linkedin: "bg-[oklch(0.55_0.13_240)]",
  };
  return map[platform.toLowerCase()] ?? "bg-muted-foreground";
}

export function IdeaCard({
  idea,
  onAction,
  busy,
}: {
  idea: SocialIdea;
  onAction: (action: "approve" | "reject" | "edit", edit?: Partial<SocialIdea>) => Promise<void>;
  busy: boolean;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<Partial<SocialIdea>>({
    hook: idea.hook,
    concept: idea.concept,
    best_post_time: idea.best_post_time ?? "",
    target_audience: idea.target_audience ?? "",
  });

  const grounded = idea.grounded_in || {};
  const chipTone = "bg-background text-foreground border-border";
  const groundedChips = [
    grounded.metric ? { label: "metric", text: grounded.metric, tone: chipTone } : null,
    grounded.trend ? { label: "trend", text: grounded.trend, tone: chipTone } : null,
    grounded.signal ? { label: "signal", text: grounded.signal, tone: chipTone } : null,
  ].filter((x): x is { label: string; text: string; tone: string } => !!x);

  return (
    <div className="space-y-3 border-b border-border/40 pb-5 last:border-b-0 last:pb-0">
      <div className="flex flex-wrap items-center gap-2">
        <span className={cn("h-2 w-2 rounded-full", platformDot(idea.platform))} />
        <span className="font-mono-ui text-[0.7rem] uppercase tracking-wider text-muted-foreground">
          {idea.platform} · {idea.format}
        </span>
        {idea.best_post_time && (
          <Badge variant="outline" className="text-[0.65rem]">
            <Clock className="mr-1 h-3 w-3" />
            {idea.best_post_time}
          </Badge>
        )}
      </div>

      {editing ? (
        <div className="space-y-2">
          <input
            value={draft.hook ?? ""}
            onChange={(e) => setDraft({ ...draft, hook: e.target.value })}
            placeholder="Hook (first 3 seconds)"
            className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm font-medium"
          />
          <textarea
            value={draft.concept ?? ""}
            onChange={(e) => setDraft({ ...draft, concept: e.target.value })}
            placeholder="Concept"
            rows={3}
            className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm"
          />
          <div className="grid gap-2 sm:grid-cols-2">
            <input
              value={(draft.best_post_time as string) ?? ""}
              onChange={(e) => setDraft({ ...draft, best_post_time: e.target.value })}
              placeholder="Best post time"
              className="rounded-lg border border-border bg-background px-3 py-2 text-sm"
            />
            <input
              value={(draft.target_audience as string) ?? ""}
              onChange={(e) => setDraft({ ...draft, target_audience: e.target.value })}
              placeholder="Target audience"
              className="rounded-lg border border-border bg-background px-3 py-2 text-sm"
            />
          </div>
        </div>
      ) : (
        <>
          <div className="text-sm font-semibold leading-snug text-foreground">{idea.hook}</div>
          <p className="text-xs leading-5 text-muted-foreground">{idea.concept}</p>
          {idea.outline && idea.outline.length > 0 && (
            <ol className="text-xs leading-5 text-muted-foreground space-y-0.5 pl-4 list-decimal">
              {idea.outline.slice(0, 4).map((beat, i) => (
                <li key={i}>{beat}</li>
              ))}
            </ol>
          )}
        </>
      )}

      {groundedChips.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {groundedChips.map((chip) => (
            <span
              key={chip.label}
              className={cn(
                "inline-flex items-center gap-1 rounded-sm border px-2 py-0.5 text-[0.65rem] font-medium",
                chip.tone,
              )}
              title={chip.text}
            >
              <span className="font-mono-ui uppercase tracking-wider">{chip.label}</span>
              <span className="max-w-[16rem] truncate">{chip.text}</span>
            </span>
          ))}
        </div>
      )}

      {idea.reasoning && !editing && (
        <p className="text-[0.75rem] italic leading-5 text-muted-foreground">
          {idea.reasoning}
        </p>
      )}

      <div className="flex items-center justify-between gap-2 pt-1">
        <div className="font-mono-ui text-[0.7rem] uppercase tracking-wider text-muted-foreground">
          {idea.timestamp ? isoTimeAgo(idea.timestamp) : ""}
        </div>
        <div className="flex items-center gap-1.5">
          {editing ? (
            <>
              <Button
                size="sm"
                variant="ghost"
                onClick={() => setEditing(false)}
                disabled={busy}
                className="min-h-[44px] px-3"
              >
                Cancel
              </Button>
              <Button
                size="sm"
                onClick={async () => {
                  await onAction("edit", draft);
                  setEditing(false);
                }}
                disabled={busy}
                className="min-h-[44px] px-3"
              >
                {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : "Save edit"}
              </Button>
            </>
          ) : (
            <>
              <Button
                size="sm"
                variant="ghost"
                onClick={() => setEditing(true)}
                disabled={busy}
                aria-label="Edit idea"
                className="min-h-[44px] min-w-[44px]"
              >
                <PencilLine className="h-3.5 w-3.5" />
              </Button>
              <Button
                size="sm"
                variant="ghost"
                onClick={() => onAction("reject")}
                disabled={busy}
                aria-label="Reject idea"
                className="min-h-[44px] min-w-[44px] text-destructive hover:text-destructive"
              >
                <ThumbsDown className="h-3.5 w-3.5" />
              </Button>
              <Button
                size="sm"
                onClick={() => onAction("approve")}
                disabled={busy}
                aria-label="Approve idea"
                className="min-h-[44px] px-3"
              >
                {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <ThumbsUp className="h-3.5 w-3.5" />}
                <span className="ml-1">Approve</span>
              </Button>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
function ytNum(row: SocialMetricRow, key: string): number {
  const v = (row.metrics as Record<string, unknown>)?.[key];
  return typeof v === "number" && Number.isFinite(v) ? v : 0;
}

function ytEngagementScore(row: SocialMetricRow): number {
  const likes = ytNum(row, "like_count");
  const comments = ytNum(row, "comment_count");
  const views = ytNum(row, "view_count");
  if (views <= 0) return 0;
  return (likes + comments * 2) / views;
}

export function YouTubeTabView({
  posts,
  onSelect,
}: {
  posts: SocialMetricRow[];
  onSelect: (row: SocialMetricRow) => void;
}) {
  const ytAll = useMemo(
    () => posts.filter((p) => (p.platform || "").toLowerCase() === "youtube"),
    [posts],
  );
  const channelRow = useMemo(
    () => ytAll.find((p) => (p.media_type || "").toUpperCase() === "ACCOUNT"),
    [ytAll],
  );
  const videos = useMemo(
    () => ytAll.filter((p) => (p.media_type || "").toUpperCase() !== "ACCOUNT"),
    [ytAll],
  );
  const sumComments = useMemo(
    () => videos.reduce((a, r) => a + ytNum(r, "comment_count"), 0),
    [videos],
  );

  const channelMetrics = (channelRow?.metrics ?? {}) as Record<string, unknown>;
  const subCount =
    typeof channelMetrics.subscriber_count === "number" ? channelMetrics.subscriber_count : null;
  const channelViews =
    typeof channelMetrics.view_count === "number" ? channelMetrics.view_count : null;
  const videoCount =
    typeof channelMetrics.video_count === "number" ? channelMetrics.video_count : null;

  const rankings = useMemo(() => {
    const top = (key: string) =>
      [...videos]
        .sort((a, b) => ytNum(b, key) - ytNum(a, key))
        .filter((r) => ytNum(r, key) > 0)
        .slice(0, 3);
    const eng = [...videos]
      .map((r) => ({ row: r, score: ytEngagementScore(r) }))
      .filter((x) => x.score > 0)
      .sort((a, b) => b.score - a.score)
      .slice(0, 3)
      .map((x) => x.row);
    const least = [...videos]
      .filter((r) => ytNum(r, "view_count") > 0)
      .sort((a, b) => ytNum(a, "view_count") - ytNum(b, "view_count"))
      .slice(0, 3);
    return {
      views: top("view_count"),
      likes: top("like_count"),
      comments: top("comment_count"),
      engagement: eng,
      least,
    };
  }, [videos]);

  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <YouTubeStatTile label="Subscribers" value={formatCompact(subCount)} hint="lifetime" />
        <YouTubeStatTile label="Channel views" value={formatCompact(channelViews)} hint="lifetime" />
        <YouTubeStatTile label="Videos" value={formatCompact(videoCount)} hint="published" />
        <YouTubeStatTile
          label="Comments (pulled)"
          value={formatCompact(sumComments)}
          hint={`across ${videos.length} videos`}
        />
      </div>

      {videos.length > 0 && (
        <section aria-labelledby="yt-rankings-heading" className="space-y-3">
          <div className="flex items-center gap-2">
            <h3
              id="yt-rankings-heading"
              className="font-mono-ui text-[0.75rem] uppercase tracking-wider text-foreground"
            >
              Rankings
            </h3>
          </div>
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-5">
            <RankPanel
              title="Most views"
              rows={rankings.views}
              formatValue={(r) => formatCompact(ytNum(r, "view_count"))}
              onSelect={onSelect}
            />
            <RankPanel
              title="Most likes"
              rows={rankings.likes}
              formatValue={(r) => formatCompact(ytNum(r, "like_count"))}
              onSelect={onSelect}
            />
            <RankPanel
              title="Most comments"
              rows={rankings.comments}
              formatValue={(r) => formatCompact(ytNum(r, "comment_count"))}
              onSelect={onSelect}
            />
            <RankPanel
              title="Most engagement"
              rows={rankings.engagement}
              formatValue={(r) => `${(ytEngagementScore(r) * 100).toFixed(2)}%`}
              onSelect={onSelect}
            />
            <RankPanel
              title="Least views"
              rows={rankings.least}
              formatValue={(r) => formatCompact(ytNum(r, "view_count"))}
              onSelect={onSelect}
              tone="muted"
            />
          </div>
        </section>
      )}

      {videos.length === 0 ? (
        <p className="px-1 py-1 text-xs text-muted-foreground/80">
          No YouTube videos pulled yet. Click "refresh from platforms" above to pull the channel.
        </p>
      ) : (
        <div className="grid gap-4 grid-cols-[repeat(auto-fill,minmax(280px,1fr))]">
          {videos
            .slice()
            .sort((a, b) => ytNum(b, "view_count") - ytNum(a, "view_count"))
            .map((row) => (
              <YouTubeVideoCard
                key={`${row.platform}:${row.post_id}`}
                row={row}
                onClick={() => onSelect(row)}
              />
            ))}
        </div>
      )}
    </div>
  );
}

function YouTubeStatTile({
  label,
  value,
  hint,
}: {
  label: string;
  value: string | number;
  hint?: string;
}) {
  return (
    <div className="rounded-md border border-border bg-card px-3 py-3">
      <div className="font-mono-ui text-[0.65rem] uppercase tracking-wider text-muted-foreground">
        {label}
      </div>
      <div className="mt-1 text-xl font-semibold text-foreground tabular-nums">{value}</div>
      {hint && (
        <div className="mt-0.5 font-mono-ui text-[0.6rem] uppercase tracking-wider text-muted-foreground/70">
          {hint}
        </div>
      )}
    </div>
  );
}

function RankPanel({
  title,
  rows,
  formatValue,
  onSelect,
  tone,
}: {
  title: string;
  rows: SocialMetricRow[];
  formatValue: (row: SocialMetricRow) => string;
  onSelect: (row: SocialMetricRow) => void;
  tone?: "muted";
}) {
  return (
    <div className="rounded-md bg-card p-3 space-y-2">
      <div
        className={cn(
          "font-mono-ui text-[0.7rem] uppercase tracking-wider",
          tone === "muted" ? "text-muted-foreground" : "text-foreground",
        )}
      >
        {title}
      </div>
      {rows.length === 0 ? (
        <p className="px-1 py-1 text-xs text-muted-foreground/80">No data yet</p>
      ) : (
        <ol className="space-y-1.5">
          {rows.map((row, idx) => (
            <li key={`${row.post_id}-${idx}`}>
              <button
                type="button"
                onClick={() => onSelect(row)}
                aria-label={`Rank ${idx + 1}: ${row.caption || "untitled"}, ${formatValue(row)}`}
                className="group flex min-h-[44px] w-full items-center gap-2 rounded-sm border border-border bg-card px-2.5 py-2 text-left transition hover:border-ring focus-visible:outline focus-visible:outline-1 focus-visible:outline-ring"
              >
                <span className="font-mono-ui w-4 text-center text-[0.7rem] text-muted-foreground">
                  {idx + 1}
                </span>
                <span className="flex-1 truncate text-[0.8rem] text-foreground">
                  {row.caption || "(untitled)"}
                </span>
                <span className="font-mono-ui text-[0.75rem] tabular-nums text-foreground">
                  {formatValue(row)}
                </span>
              </button>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Cross-platform metric resolver. Each platform names the same concept
// differently — IG uses `likes`/`saved`/`shares`, FB uses `like_count`/
// `reaction_count`/`comments_count`, TikTok uses `digg_count`/`play_count`/
// `share_count`/`save_count`. Read in priority order; first hit wins.
// ---------------------------------------------------------------------------
const METRIC_LOOKUP: Record<string, string[]> = {
  views: [
    "views", "view_count", "plays", "play_count", "video_views",
    "post_video_views", "post_impressions",
  ],
  likes: ["likes", "like_count", "reaction_count", "digg_count"],
  comments: ["comments", "comment_count", "comments_count"],
  shares: ["shares", "share_count"],
  saves: ["saved", "saves", "save_count"],
  reach: ["reach"],
};

function readMetric(row: SocialMetricRow, logical: string): number {
  const m = (row.metrics || {}) as Record<string, unknown>;
  const raw = (row.raw || {}) as Record<string, unknown>;
  const fbPost = (raw.post as Record<string, unknown> | undefined) || {};
  for (const key of METRIC_LOOKUP[logical] || []) {
    for (const src of [m, raw, fbPost]) {
      const v = src[key];
      if (typeof v === "number" && Number.isFinite(v)) return v;
      if (typeof v === "string") {
        const n = Number(v);
        if (Number.isFinite(n)) return n;
      }
    }
  }
  return 0;
}

function genericEngagement(row: SocialMetricRow): number {
  const likes = readMetric(row, "likes");
  const comments = readMetric(row, "comments");
  const shares = readMetric(row, "shares");
  const saves = readMetric(row, "saves");
  const views = readMetric(row, "views");
  const total = likes + comments * 2 + shares * 3 + saves * 2;
  if (views > 0) return total / views;
  return 0;
}

function totalActivity(row: SocialMetricRow): number {
  return (
    readMetric(row, "likes") +
    readMetric(row, "comments") +
    readMetric(row, "shares") +
    readMetric(row, "saves")
  );
}

// Hook rate = % of people who watched after seeing the post.
// IG: views / reach. FB: post_video_views / post_impressions.
// TikTok Display API and YouTube Data API don't expose impressions/reach.
function derivedHookRate(row: SocialMetricRow): number | null {
  const platform = (row.platform || "").toLowerCase();
  const m = (row.metrics || {}) as Record<string, unknown>;
  const backend = m.hook_rate;
  if (typeof backend === "number" && Number.isFinite(backend) && backend > 0) {
    return backend;
  }
  if (platform === "instagram") {
    const views = readMetric(row, "views");
    const reach = readMetric(row, "reach");
    if (views > 0 && reach > 0) return Math.min(views / reach, 1);
    return null;
  }
  if (platform === "facebook") {
    const videoViews = Number(m.post_video_views) || 0;
    const impressions =
      Number(m.post_impressions) || Number(m.post_impressions_unique) || 0;
    if (videoViews > 0 && impressions > 0) return Math.min(videoViews / impressions, 1);
    return null;
  }
  return null;
}

// Hold rate = % of the video the average viewer watched.
// IG: ig_reels_avg_watch_time (ms) / duration_sec. Requires `duration` in fetcher.
// FB needs a separate /video?fields=length lookup (not yet wired).
// TikTok Display API has no avg_watch_time. YouTube Analytics API not exposed.
function derivedHoldRate(row: SocialMetricRow): number | null {
  const platform = (row.platform || "").toLowerCase();
  const m = (row.metrics || {}) as Record<string, unknown>;
  const backend = m.hold_rate;
  if (typeof backend === "number" && Number.isFinite(backend) && backend > 0) {
    return backend;
  }
  if (platform === "instagram") {
    const avgMs = Number(m.ig_reels_avg_watch_time) || 0;
    const durSec = Number(m.duration_sec ?? m.duration) || 0;
    if (avgMs > 0 && durSec > 0) return Math.min(avgMs / (durSec * 1000), 1);
    return null;
  }
  if (platform === "facebook") {
    // post_video_avg_time_watched is in milliseconds; need video length to ratio.
    const avgMs = Number(m.post_video_avg_time_watched) || 0;
    const raw = (row.raw || {}) as Record<string, unknown>;
    const fbPost = (raw.post as Record<string, unknown> | undefined) || {};
    const fbAttach = ((fbPost.attachments as Record<string, unknown> | undefined)
      ?.data as Array<Record<string, unknown>> | undefined)?.[0];
    const fbMedia = (fbAttach?.media as Record<string, unknown> | undefined) || {};
    const fbSrc = fbMedia.source as string | undefined;
    const lengthSec =
      Number((fbAttach as Record<string, unknown> | undefined)?.video_length) ||
      Number(fbMedia.length) ||
      0;
    if (avgMs > 0 && lengthSec > 0 && fbSrc) {
      return Math.min(avgMs / (lengthSec * 1000), 1);
    }
    return null;
  }
  return null;
}

export function PlatformRankingsBlock({
  posts,
  onSelect,
}: {
  posts: SocialMetricRow[];
  onSelect: (row: SocialMetricRow) => void;
}) {
  // YouTube has its own block; ACCOUNT rows aren't posts.
  const eligible = useMemo(
    () =>
      posts.filter(
        (p) =>
          (p.platform || "").toLowerCase() !== "youtube" &&
          (p.media_type || "").toUpperCase() !== "ACCOUNT",
      ),
    [posts],
  );

  const panels = useMemo(() => {
    const top = (logical: string) =>
      [...eligible]
        .sort((a, b) => readMetric(b, logical) - readMetric(a, logical))
        .filter((r) => readMetric(r, logical) > 0)
        .slice(0, 3);
    const eng = [...eligible]
      .map((r) => ({ row: r, score: genericEngagement(r) }))
      .filter((x) => x.score > 0)
      .sort((a, b) => b.score - a.score)
      .slice(0, 3)
      .map((x) => x.row);
    const least = [...eligible]
      .filter((r) => totalActivity(r) > 0)
      .sort((a, b) => totalActivity(a) - totalActivity(b))
      .slice(0, 3);

    const fmtCount = (key: string) => (r: SocialMetricRow) => formatCompact(readMetric(r, key));
    return [
      { title: "Most views", rows: top("views"), format: fmtCount("views") },
      { title: "Most likes", rows: top("likes"), format: fmtCount("likes") },
      { title: "Most comments", rows: top("comments"), format: fmtCount("comments") },
      { title: "Most shares", rows: top("shares"), format: fmtCount("shares") },
      { title: "Most saves", rows: top("saves"), format: fmtCount("saves") },
      {
        title: "Most engagement",
        rows: eng,
        format: (r: SocialMetricRow) => `${(genericEngagement(r) * 100).toFixed(2)}%`,
      },
      {
        title: "Least performing",
        rows: least,
        format: (r: SocialMetricRow) => `${formatCompact(totalActivity(r))} ints`,
        tone: "muted" as const,
      },
    ].filter((p) => p.rows.length > 0);
  }, [eligible]);

  if (!panels.length) return null;

  return (
    <section aria-labelledby="rankings-heading" className="space-y-3">
      <h3
        id="rankings-heading"
        className="font-mono-ui text-[0.75rem] uppercase tracking-wider text-foreground"
      >
        Rankings
      </h3>
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4">
        {panels.map((panel) => (
          <RankPanel
            key={panel.title}
            title={panel.title}
            rows={panel.rows}
            formatValue={panel.format}
            onSelect={onSelect}
            tone={panel.tone}
          />
        ))}
      </div>
    </section>
  );
}

function YouTubeVideoCard({
  row,
  onClick,
}: {
  row: SocialMetricRow;
  onClick: () => void;
}) {
  const raw = (row.raw || {}) as Record<string, unknown>;
  const ytSnippet = raw.snippet as Record<string, unknown> | undefined;
  const ytThumb =
    (ytSnippet?.thumbnail as string | undefined) ||
    ((ytSnippet?.thumbnails as Record<string, { url?: string }> | undefined)?.high?.url as string | undefined);
  const thumb =
    (raw.thumbnail_url as string | undefined) ||
    (raw.thumbnail as string | undefined) ||
    ytThumb;
  const m = (row.metrics || {}) as Record<string, unknown>;
  const caption = row.caption || "";
  const isShort = (row.media_type || "").toUpperCase() === "SHORT";
  const duration = m.duration_iso as string | undefined;

  const views = ytNum(row, "view_count");
  const likes = ytNum(row, "like_count");
  const comments = ytNum(row, "comment_count");
  const engagement = ytEngagementScore(row);

  const skipKeys = new Set([
    "view_count",
    "like_count",
    "comment_count",
    "duration_iso",
    "avg_view_duration_sec",
    "avg_view_percentage",
  ]);
  const extraChips: Array<{ label: string; value: string }> = [];
  for (const [k, v] of Object.entries(m)) {
    if (k.startsWith("_") || skipKeys.has(k)) continue;
    if (v == null) continue;
    if (typeof v !== "number" && typeof v !== "string") continue;
    extraChips.push({ label: prettifyMetricKey(k), value: formatMetricValue(k, v) });
  }

  return (
    <button
      type="button"
      onClick={onClick}
      className="group flex flex-col text-left rounded-md border border-border bg-card overflow-hidden transition hover:border-ring"
    >
      <div className="relative aspect-video w-full bg-card">
        {thumb ? (
          <img
            src={thumb}
            alt={caption ? caption.slice(0, 100) : ""}
            loading="lazy"
            onError={(e) => {
              (e.currentTarget as HTMLImageElement).style.display = "none";
            }}
            className="absolute inset-0 h-full w-full object-cover"
          />
        ) : (
          <div aria-hidden="true" className="absolute inset-0 flex items-center justify-center text-muted-foreground/40">
            <Video className="h-8 w-8" />
          </div>
        )}
        <div className="absolute top-1.5 left-1.5 flex items-center gap-1 rounded-sm bg-card border border-border px-2 py-0.5">
          <span className={cn("h-1.5 w-1.5 rounded-full", platformDot("youtube"))} />
          <span className="font-mono-ui text-[0.7rem] uppercase tracking-wider text-foreground">
            {isShort ? "short" : "video"}
          </span>
        </div>
        {duration && (
          <div className="absolute bottom-1.5 right-1.5 rounded bg-card border border-border/60 px-1.5 py-0.5 font-mono-ui text-[0.7rem] tabular-nums text-foreground">
            {formatIsoDuration(duration)}
          </div>
        )}
        {engagement > 0 && (
          <div
            className="absolute top-1.5 right-1.5 rounded bg-primary px-1.5 py-0.5 font-mono-ui text-[0.7rem] uppercase tracking-wider text-primary-foreground"
            aria-label={`Engagement ${(engagement * 100).toFixed(2)} percent`}
          >
            {(engagement * 100).toFixed(2)}% eng
          </div>
        )}
      </div>
      <div className="flex flex-col gap-2 p-3">
        <h3 className="line-clamp-2 text-sm font-semibold leading-snug text-foreground">
          {caption || "(untitled)"}
        </h3>
        <div className="font-mono-ui text-[0.7rem] uppercase tracking-wider text-muted-foreground">
          {row.posted_at ? isoTimeAgo(row.posted_at) : "—"}
        </div>
        <div className="grid grid-cols-3 gap-1.5 pt-1">
          <YouTubeMetricCell label="views" value={formatCompact(views)} />
          <YouTubeMetricCell label="likes" value={formatCompact(likes)} />
          <YouTubeMetricCell label="comments" value={formatCompact(comments)} />
        </div>
        {extraChips.length > 0 && (
          <div className="font-mono-ui flex flex-wrap gap-x-2 gap-y-0.5 pt-1 text-[0.7rem] text-muted-foreground">
            {extraChips.map((chip, i) => (
              <span key={`${chip.label}-${i}`} className="whitespace-nowrap">
                {chip.value}
                <span className="ml-0.5 text-muted-foreground">{chip.label}</span>
              </span>
            ))}
          </div>
        )}
      </div>
    </button>
  );
}

function YouTubeMetricCell({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-border/40 bg-card px-2 py-1">
      <div className="font-mono-ui text-[0.7rem] uppercase tracking-wider text-muted-foreground">
        {label}
      </div>
      <div className="text-sm font-semibold tabular-nums text-foreground">{value}</div>
    </div>
  );
}

export function PlatformTablist({
  tabs,
  active,
  onChange,
  idPrefix,
  panelId,
}: {
  tabs: Array<{ label: string; count: number }>;
  active: string;
  onChange: (label: string) => void;
  idPrefix: string;
  panelId: string;
}) {
  const refs = useRef<Array<HTMLButtonElement | null>>([]);
  const handleKey = (idx: number) => (e: ReactKeyboardEvent<HTMLButtonElement>) => {
    if (e.key !== "ArrowRight" && e.key !== "ArrowLeft" && e.key !== "Home" && e.key !== "End")
      return;
    e.preventDefault();
    let next = idx;
    if (e.key === "ArrowRight") next = (idx + 1) % tabs.length;
    else if (e.key === "ArrowLeft") next = (idx - 1 + tabs.length) % tabs.length;
    else if (e.key === "Home") next = 0;
    else if (e.key === "End") next = tabs.length - 1;
    onChange(tabs[next].label);
    refs.current[next]?.focus();
  };
  return (
    <div role="tablist" aria-label="Filter posts by platform" className="flex flex-wrap items-center gap-1.5 pt-1">
      {tabs.map((t, i) => (
        <PlatformTab
          key={t.label}
          ref={(el) => {
            refs.current[i] = el;
          }}
          id={`${idPrefix}-tab-${t.label}`}
          label={t.label}
          count={t.count}
          active={active === t.label}
          onClick={() => onChange(t.label)}
          onKeyDown={handleKey(i)}
          controlsId={panelId}
        />
      ))}
    </div>
  );
}

const PlatformTab = forwardRef<HTMLButtonElement, {
  id: string;
  label: string;
  active: boolean;
  count: number;
  onClick: () => void;
  onKeyDown?: (e: ReactKeyboardEvent<HTMLButtonElement>) => void;
  controlsId?: string;
}>(function PlatformTab({ id, label, active, count, onClick, onKeyDown, controlsId }, ref) {
  return (
    <button
      ref={ref}
      id={id}
      type="button"
      role="tab"
      aria-selected={active}
      aria-controls={controlsId}
      tabIndex={active ? 0 : -1}
      onClick={onClick}
      onKeyDown={onKeyDown}
      className={cn(
        "inline-flex min-h-[44px] items-center gap-1.5 rounded-sm border px-3 py-2 font-mono-ui text-[0.75rem] uppercase tracking-wider transition focus-visible:outline focus-visible:outline-1 focus-visible:outline-ring",
        active
          ? "border-primary bg-muted text-foreground"
          : "border-border bg-card text-muted-foreground hover:border-ring hover:text-foreground",
      )}
    >
      {label !== "all" && (
        <span aria-hidden="true" className={cn("h-1.5 w-1.5 rounded-full", platformDot(label))} />
      )}
      <span>{label}</span>
      <span className="text-muted-foreground">{count}</span>
    </button>
  );
});

// Single source of truth — delegates to the cross-platform readers so IG/FB/TT/YT
// rank consistently. Adds a tiny activity tiebreaker so two posts with identical
// rates don't shuffle randomly.
export function computeEngagementScore(row: SocialMetricRow): number {
  const score = genericEngagement(row);
  const activity = totalActivity(row);
  if (score > 0) return score * 100 + activity * 0.001;
  return activity;
}

export function PostDetailModal({ row, onClose }: { row: SocialMetricRow; onClose: () => void }) {
  const raw = (row.raw || {}) as Record<string, unknown>;
  const fbPost = (raw.post as Record<string, unknown> | undefined) || {};
  const fbAttach = ((fbPost.attachments as Record<string, unknown> | undefined)?.data as Array<Record<string, unknown>> | undefined)?.[0];
  const fbMedia = (fbAttach?.media as Record<string, unknown> | undefined) || {};
  const fbImage = (fbMedia.image as { src?: string } | undefined)?.src;
  const ytSnippet = raw.snippet as Record<string, unknown> | undefined;
  const ytThumb =
    (ytSnippet?.thumbnail as string | undefined) ||
    ((ytSnippet?.thumbnails as Record<string, { url?: string }> | undefined)?.high?.url as string | undefined);
  const thumb =
    (raw.thumbnail_url as string | undefined) ||
    (raw.thumbnail as string | undefined) ||
    ytThumb ||
    (fbPost.full_picture as string | undefined) ||
    fbImage ||
    (raw.full_picture as string | undefined) ||
    (raw.media_url as string | undefined);
  const caption = row.caption || (fbPost.message as string | undefined) || "";
  const m = (row.metrics || {}) as Record<string, unknown>;
  const page = (m._page as string | undefined) || "";
  const hookRate = derivedHookRate(row);
  const holdRate = derivedHoldRate(row);
  const engagementRate =
    typeof m.engagement_rate === "number" ? (m.engagement_rate as number) : null;
  // Hook/hold render as their own row above the grid; drop the raw fields
  // from the grid so we don't show them twice.
  const metricEntries = Object.entries(m).filter(
    ([k]) => !k.startsWith("_") && k !== "hook_rate" && k !== "hold_rate",
  );

  const titleId = useId();
  const dialogRef = useRef<HTMLDivElement>(null);
  const previouslyFocused = useRef<HTMLElement | null>(null);

  useEffect(() => {
    previouslyFocused.current = document.activeElement as HTMLElement | null;
    const root = dialogRef.current;
    if (root) {
      const first = root.querySelector<HTMLElement>(
        'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])',
      );
      (first ?? root).focus();
    }
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.stopPropagation();
        onClose();
        return;
      }
      if (e.key === "Tab" && root) {
        const focusable = Array.from(
          root.querySelectorAll<HTMLElement>(
            'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
          ),
        ).filter((el) => !el.hasAttribute("aria-hidden"));
        if (!focusable.length) return;
        const first = focusable[0];
        const last = focusable[focusable.length - 1];
        const active = document.activeElement as HTMLElement | null;
        if (e.shiftKey && active === first) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && active === last) {
          e.preventDefault();
          first.focus();
        }
      }
    };
    document.addEventListener("keydown", onKeyDown);
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      document.body.style.overflow = prevOverflow;
      previouslyFocused.current?.focus?.();
    };
  }, [onClose]);

  const headingText = caption
    ? caption.split("\n")[0].slice(0, 120)
    : `${row.platform || "Post"} detail`;
  const platformLabel = (row.platform || "").toString();
  const isFbLandscape = platformLabel.toLowerCase() === "facebook";
  const [linkCopied, setLinkCopied] = useState(false);
  const handleCopyLink = useCallback(async () => {
    if (!row.permalink) return;
    try {
      await navigator.clipboard.writeText(row.permalink);
      setLinkCopied(true);
      window.setTimeout(() => setLinkCopied(false), 1600);
    } catch {
      // clipboard blocked; ignore
    }
  }, [row.permalink]);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-background/85 p-4"
      onClick={onClose}
    >
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
        className="relative max-h-[90vh] w-full max-w-3xl overflow-y-auto rounded-md border border-border bg-card outline-none"
        onClick={(e) => e.stopPropagation()}
      >
        <button
          type="button"
          onClick={onClose}
          aria-label="Close post detail"
          className="absolute right-3 top-3 z-10 inline-flex min-h-[44px] min-w-[44px] items-center justify-center rounded-sm bg-background px-3 font-mono-ui text-[0.7rem] uppercase tracking-wider text-muted-foreground hover:text-foreground focus-visible:outline focus-visible:outline-1 focus-visible:outline-ring"
        >
          close
        </button>
        <div className="grid gap-0 md:grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)]">
          <div
            className={cn(
              "relative bg-card md:aspect-auto md:min-h-[480px]",
              isFbLandscape ? "aspect-[4/5]" : "aspect-[9/16]",
            )}
          >
            {thumb ? (
              <img
                src={thumb}
                alt={caption ? caption.slice(0, 100) : ""}
                onError={(e) => {
                  (e.currentTarget as HTMLImageElement).style.display = "none";
                }}
                className="absolute inset-0 h-full w-full object-cover"
              />
            ) : (
              <div
                aria-hidden="true"
                className="absolute inset-0 flex items-center justify-center text-muted-foreground/40"
              >
                <Activity className="h-8 w-8" />
              </div>
            )}
            <div className="absolute top-3 left-3 flex items-center gap-1.5 rounded-sm bg-card border border-border px-2.5 py-1">
              <span
                aria-hidden="true"
                className={cn("h-2 w-2 rounded-full", platformDot(row.platform))}
              />
              <span className="font-mono-ui text-[0.7rem] uppercase tracking-wider text-foreground">
                {platformLabel || "post"}
              </span>
            </div>
          </div>
          <div className="space-y-4 p-5">
            <div>
              <h2
                id={titleId}
                className="text-base font-semibold leading-snug text-foreground"
              >
                {headingText}
              </h2>
              <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 font-mono-ui text-[0.7rem] uppercase tracking-wider text-muted-foreground">
                {page && <span>{page}</span>}
                <span>
                  {row.posted_at ? new Date(row.posted_at).toLocaleString() : "—"}
                </span>
              </div>
              {row.permalink && (
                <div className="mt-2 flex flex-wrap items-center gap-2">
                  <a
                    href={row.permalink}
                    target="_blank"
                    rel="noopener noreferrer"
                    aria-label="Open original post in new tab"
                    className="font-mono-ui inline-flex min-h-[44px] items-center px-3 text-[0.7rem] uppercase tracking-wider text-primary hover:underline focus-visible:outline focus-visible:outline-1 focus-visible:outline-ring"
                  >
                    open ↗
                  </a>
                  <button
                    type="button"
                    onClick={handleCopyLink}
                    aria-label="Copy post link to clipboard"
                    aria-live="polite"
                    className="font-mono-ui inline-flex min-h-[44px] items-center rounded-md border border-border bg-background px-3 text-[0.7rem] uppercase tracking-wider text-muted-foreground hover:text-foreground focus-visible:outline focus-visible:outline-1 focus-visible:outline-ring"
                  >
                    {linkCopied ? "copied" : "copy link"}
                  </button>
                </div>
              )}
            </div>
            {caption && caption !== headingText && (
              <p className="whitespace-pre-wrap text-sm leading-relaxed text-foreground">
                {caption}
              </p>
            )}
            {(engagementRate != null || hookRate != null || holdRate != null) && (
              <div className="flex flex-wrap items-baseline gap-x-5 gap-y-1 border-t border-border pt-3 font-mono-ui text-[0.7rem] uppercase tracking-wider text-muted-foreground">
                {engagementRate != null && (
                  <span>
                    <span className="text-base font-semibold tabular-nums text-foreground">
                      {(engagementRate * 100).toFixed(2)}%
                    </span>{" "}
                    engagement
                  </span>
                )}
                {hookRate != null && (
                  <span>
                    <span className="text-base font-semibold tabular-nums text-foreground">
                      {(hookRate * 100).toFixed(1)}%
                    </span>{" "}
                    hook
                  </span>
                )}
                {holdRate != null && (
                  <span>
                    <span className="text-base font-semibold tabular-nums text-foreground">
                      {(holdRate * 100).toFixed(1)}%
                    </span>{" "}
                    hold
                  </span>
                )}
              </div>
            )}
            {metricEntries.length > 0 ? (
              <div>
                <div className="mb-2 font-mono-ui text-[0.7rem] uppercase tracking-wider text-muted-foreground">
                  Metrics
                </div>
                <div className="grid grid-cols-2 gap-2">
                  {metricEntries.map(([k, v]) => (
                    <div key={k} className="rounded-sm border border-border bg-card px-3 py-2">
                      <div className="font-mono-ui text-[0.7rem] uppercase tracking-wider text-muted-foreground">
                        {prettifyMetricKey(k)}
                      </div>
                      <div className="mt-0.5 text-sm font-medium tabular-nums text-foreground">
                        {formatMetricValue(k, v)}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            ) : (
              <p className="px-1 py-1 text-xs text-muted-foreground/80">No metrics returned for this post yet.</p>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

export function RealVideoCard({
  row,
  onClick,
  highlight,
}: {
  row: SocialMetricRow;
  onClick?: () => void;
  highlight?: boolean;
}) {
  const raw = (row.raw || {}) as Record<string, unknown>;
  const fbPost = (raw.post as Record<string, unknown> | undefined) || {};
  const fbAttach = ((fbPost.attachments as Record<string, unknown> | undefined)?.data as Array<Record<string, unknown>> | undefined)?.[0];
  const fbMedia = (fbAttach?.media as Record<string, unknown> | undefined) || {};
  const fbImage = (fbMedia.image as { src?: string } | undefined)?.src;
  const ytSnippet = raw.snippet as Record<string, unknown> | undefined;
  const ytThumb =
    (ytSnippet?.thumbnail as string | undefined) ||
    ((ytSnippet?.thumbnails as Record<string, { url?: string }> | undefined)?.high?.url as string | undefined);
  const thumb =
    (raw.thumbnail_url as string | undefined) ||
    (raw.thumbnail as string | undefined) ||
    ytThumb ||
    (fbPost.full_picture as string | undefined) ||
    fbImage ||
    (raw.full_picture as string | undefined) ||
    (raw.media_url as string | undefined);
  const m = (row.metrics || {}) as Record<string, unknown>;
  const engagementRate =
    typeof m.engagement_rate === "number" ? (m.engagement_rate as number) : null;
  const hookRate = derivedHookRate(row);
  const holdRate = derivedHoldRate(row);
  const caption = row.caption || (fbPost.message as string | undefined) || "";
  const captionDisplay = caption.trim() || "Untitled post";

  // Two metrics max — pick the most meaningful for this row.
  // Video: views + likes. Static: likes + comments. Story: reach + replies.
  const views = readMetric(row, "views");
  const likes = readMetric(row, "likes");
  const comments = readMetric(row, "comments");
  const shares = readMetric(row, "shares");
  const candidates: Array<[string, number]> = [
    ["views", views],
    ["likes", likes],
    ["comments", comments],
    ["shares", shares],
  ];
  const topMetrics = candidates.filter(([, v]) => v > 0).slice(0, 2);

  // Pick a single rate to show — hold > hook > engagement (descending priority of insight value).
  const primaryRate: { label: string; value: number } | null =
    holdRate != null
      ? { label: "hold", value: holdRate }
      : hookRate != null
        ? { label: "hook", value: hookRate }
        : engagementRate != null
          ? { label: "eng", value: engagementRate }
          : null;

  const handleClick = (e: ReactMouseEvent) => {
    if (onClick) {
      e.preventDefault();
      onClick();
    }
  };

  const platform = (row.platform || "").toLowerCase();
  const mediaType = (row.media_type || "").toUpperCase();
  // Vertical for Reels/Shorts/TikTok; square for static FB/IG photo posts.
  const isVertical =
    platform === "tiktok" ||
    mediaType === "REEL" ||
    mediaType === "REELS" ||
    mediaType === "VIDEO" ||
    mediaType === "SHORT" ||
    mediaType === "STORY";
  const aspectClass = isVertical ? "aspect-[9/16]" : "aspect-square";

  const Inner = (
    <div className="space-y-2">
      <div
        className={cn(
          "relative overflow-hidden rounded-md bg-card border transition",
          aspectClass,
          highlight ? "border-primary" : "border-border group-hover:border-ring",
        )}
      >
        {thumb ? (
          <img
            src={thumb}
            alt={caption ? caption.slice(0, 100) : ""}
            loading="lazy"
            onError={(e) => {
              (e.currentTarget as HTMLImageElement).style.display = "none";
            }}
            className="absolute inset-0 h-full w-full object-cover"
          />
        ) : (
          <div aria-hidden="true" className="absolute inset-0 flex items-center justify-center text-muted-foreground/40">
            <Activity className="h-6 w-6" />
          </div>
        )}
        <span
          aria-hidden="true"
          className={cn(
            "absolute top-2 left-2 h-2 w-2 rounded-full ring-2 ring-background",
            platformDot(row.platform),
          )}
          title={row.platform}
        />
      </div>
      <div className="space-y-1">
        <p className="line-clamp-2 text-[0.8rem] leading-snug text-foreground">
          {captionDisplay}
        </p>
        {topMetrics.length > 0 && (
          <div className="flex items-baseline gap-3 text-[0.72rem] text-muted-foreground">
            {topMetrics.map(([label, value]) => (
              <span key={label} className="whitespace-nowrap">
                <span className="font-medium tabular-nums text-foreground">
                  {formatCompact(value)}
                </span>{" "}
                {label}
              </span>
            ))}
          </div>
        )}
        <div className="flex items-center justify-between text-[0.7rem] text-muted-foreground">
          <span className="font-mono-ui uppercase tracking-wider">
            {row.posted_at ? isoTimeAgo(row.posted_at) : "—"}
          </span>
          {primaryRate && (
            <span className="font-mono-ui tabular-nums uppercase tracking-wider text-foreground">
              {(primaryRate.value * 100).toFixed(1)}% {primaryRate.label}
            </span>
          )}
        </div>
      </div>
    </div>
  );
  if (onClick) {
    return (
      <button
        type="button"
        onClick={handleClick}
        className="group block w-full text-left focus-visible:outline focus-visible:outline-1 focus-visible:outline-offset-2 focus-visible:outline-ring rounded-md"
      >
        {Inner}
      </button>
    );
  }
  return row.permalink ? (
    <a
      href={row.permalink}
      target="_blank"
      rel="noopener noreferrer"
      className="group block focus-visible:outline focus-visible:outline-1 focus-visible:outline-offset-2 focus-visible:outline-ring rounded-md"
    >
      {Inner}
    </a>
  ) : (
    <div>{Inner}</div>
  );
}

export function PlatformBlockCard({
  platform,
  block,
}: {
  platform: string;
  block: SocialPlatformBlock;
}) {
  const { totals, averages, top_posts, post_count } = block;
  return (
    <div className="space-y-4">
      <div className="flex items-baseline justify-between gap-3">
        <div className="flex items-center gap-2">
          <span aria-hidden="true" className={cn("h-2 w-2 rounded-full", platformDot(platform))} />
          <span className="font-mono-ui text-[0.8rem] uppercase tracking-wider text-foreground">
            {platform}
          </span>
        </div>
        <span className="font-mono-ui text-[0.7rem] uppercase tracking-wider text-muted-foreground">
          {post_count} posts
        </span>
      </div>

      <div className="flex flex-wrap items-baseline gap-x-6 gap-y-2">
        <div>
          <div className="text-base font-semibold tabular-nums text-foreground">
            {formatCompact(totals?.reach)}
          </div>
          <div className="font-mono-ui text-[0.7rem] uppercase tracking-wider text-muted-foreground">
            Reach
          </div>
        </div>
        <div>
          <div className="text-base font-semibold tabular-nums text-foreground">
            {formatPct(averages?.engagement_rate, 2)}
          </div>
          <div className="font-mono-ui text-[0.7rem] uppercase tracking-wider text-muted-foreground">
            Engagement
          </div>
        </div>
        <div>
          <div className="text-base font-semibold tabular-nums text-foreground">
            {formatPct(averages?.hook_rate ?? averages?.hold_rate, 2)}
          </div>
          <div className="font-mono-ui text-[0.7rem] uppercase tracking-wider text-muted-foreground">
            {averages?.hook_rate != null ? "Hook" : "Hold"}
          </div>
        </div>
      </div>

      {top_posts && top_posts.length > 0 && (
        <div className="space-y-1">
          <div className="font-mono-ui text-[0.7rem] uppercase tracking-wider text-muted-foreground">
            Top performers
          </div>
          <ul className="space-y-0.5">
            {top_posts.slice(0, 3).map((p) => (
              <li key={p.post_id}>
                <a
                  href={p.permalink ?? "#"}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="flex items-center gap-2 px-1 py-1 text-[0.8rem] text-foreground hover:text-primary"
                >
                  <span className="flex-1 truncate">{p.caption || "(no caption)"}</span>
                  <span className="font-mono-ui text-[0.7rem] tabular-nums text-muted-foreground">
                    {formatPct(p.derived?.engagement_rate, 1)}
                  </span>
                  {p.permalink && <ExternalLink className="h-3 w-3 text-muted-foreground" />}
                </a>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

```

---
## `src/pages/real-estate-hub/thread-drawer.tsx`
```tsx
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { createPortal } from "react-dom";
import { Activity, CheckSquare, Loader2, RotateCcw, Send, X as CloseIcon, StickyNote } from "lucide-react";
import { api } from "@/lib/api";
import type { ThreadContextMessage, ThreadContextResponse } from "@/lib/api";
import type { SourceInboxDraft } from "@/lib/api-types";
import type { HubData } from "../RealEstateHubPages";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { LeadStatusControl } from "./_shared/lead-status-control";

type ThreadDrawerExtras = { skippedDraft?: SourceInboxDraft };
type ThreadDrawerTarget =
  | { sourceId: string; threadId: string; extras?: ThreadDrawerExtras }
  | null;

const ThreadDrawerContext = createContext<{
  openThread: (
    sourceId: string,
    threadId: string,
    extras?: ThreadDrawerExtras,
  ) => void;
} | null>(null);

export function useThreadDrawer() {
  return useContext(ThreadDrawerContext);
}

export function ThreadDrawerProvider({
  children,
  data,
}: {
  children: ReactNode;
  data: HubData;
}) {
  const [target, setTarget] = useState<ThreadDrawerTarget>(null);
  const openThread = useCallback(
    (sourceId: string, threadId: string, extras?: ThreadDrawerExtras) => {
      setTarget({ sourceId, threadId, extras });
    },
    [],
  );
  const close = useCallback(() => setTarget(null), []);
  const ctx = useMemo(() => ({ openThread }), [openThread]);
  return (
    <ThreadDrawerContext.Provider value={ctx}>
      {children}
      {target && <ThreadDrawer data={data} target={target} onClose={close} />}
    </ThreadDrawerContext.Provider>
  );
}

function fmtMessageTimestamp(value: string | null | undefined): string {
  if (!value) return "";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}

function ThreadMessageBubble({ message }: { message: ThreadContextMessage }) {
  const inbound = message.direction !== "outbound";
  return (
    <div className={cn("flex flex-col gap-1.5", inbound ? "items-start" : "items-end")}>
      <div
        className={cn(
          "max-w-[82%] rounded-lg px-3.5 py-2.5 text-[0.875rem] leading-[1.45] whitespace-pre-wrap break-words text-foreground",
          inbound
            ? "bg-background border border-border"
            : "bg-primary/15 border border-primary/45",
        )}
      >
        {message.text || <span className="text-foreground/55 italic">(no text)</span>}
      </div>
      <div
        className="flex items-center gap-1.5 text-[0.68rem] uppercase tracking-[0.08em] text-foreground/55"
        style={{ fontFamily: "var(--theme-font-mono)" }}
      >
        {message.sender && <span className="font-medium">{message.sender}</span>}
        {message.sender && message.timestamp && <span>·</span>}
        {message.timestamp && <span>{fmtMessageTimestamp(message.timestamp)}</span>}
      </div>
    </div>
  );
}

function ThreadDrawer({
  data,
  target,
  onClose,
}: {
  data: HubData;
  target: { sourceId: string; threadId: string; extras?: ThreadDrawerExtras };
  onClose: () => void;
}) {
  const skippedDraft = target.extras?.skippedDraft;
  const [context, setContext] = useState<ThreadContextResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [reply, setReply] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [restoring, setRestoring] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await api.getThreadContext(target.sourceId, target.threadId);
      setContext(result);
      setReply(result.pendingDraft?.draftText ?? "");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, [target.sourceId, target.threadId]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = prevOverflow;
    };
  }, [onClose]);

  useLayoutEffect(() => {
    if (!loading && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [loading, context?.messages.length]);

  const sendDraft = useCallback(
    async (action: "approve" | "skip") => {
      if (!context?.pendingDraft) return;
      setSubmitting(true);
      try {
        const nextInbox = await api.updateSourceInboxDraft(
          context.pendingDraft.sourceId,
          context.pendingDraft.taskId,
          action,
          reply,
        );
        data.setSourceInbox(nextInbox);
        onClose();
      } catch (err) {
        window.alert(`Failed to ${action} draft: ${err instanceof Error ? err.message : String(err)}`);
      } finally {
        setSubmitting(false);
      }
    },
    [context?.pendingDraft, data, onClose, reply],
  );

  const restoreSkippedDraft = useCallback(async () => {
    if (!skippedDraft || restoring) return;
    setRestoring(true);
    try {
      const nextInbox = await api.updateSourceInboxDraft(
        skippedDraft.sourceId,
        skippedDraft.taskId,
        "restore",
        skippedDraft.draftText,
      );
      data.setSourceInbox(nextInbox);
      onClose();
    } catch (err) {
      window.alert(`Failed to restore skipped draft: ${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setRestoring(false);
    }
  }, [data, onClose, restoring, skippedDraft]);

  const meta = context?.meta;
  const sends = context?.sends ?? [];
  const messages = context?.messages ?? [];

  const profile = useMemo(() => {
    const profiles = data.sourceInbox?.profiles ?? [];
    const composite = `${target.sourceId}:${target.threadId}`;
    for (const p of profiles) {
      for (const key of p.threadIds ?? []) {
        if (!key) continue;
        if (key === composite) return p;
        const colonAt = key.indexOf(":");
        if (colonAt >= 0 && key.slice(colonAt + 1) === target.threadId) return p;
      }
    }
    return null;
  }, [data.sourceInbox?.profiles, target.sourceId, target.threadId]);

  return createPortal(
    <div className="fixed inset-0 z-50 flex items-stretch justify-center animate-[fade-in_120ms_ease-out] sm:items-center sm:p-6">
      <button
        type="button"
        aria-label="Close thread"
        onClick={onClose}
        className="absolute inset-0 z-0 bg-background/80"
      />
      <div
        role="dialog"
        aria-modal="true"
        className="relative z-10 flex h-full w-full flex-col bg-card shadow-[0_24px_90px_rgba(0,0,0,0.32)] sm:h-[calc(100vh-3rem)] sm:max-h-[calc(100vh-3rem)] sm:min-h-[640px] sm:w-full sm:max-w-[56rem] sm:rounded-md sm:border sm:border-border lg:max-w-[68rem] xl:max-w-[80rem]"
      >
        <div className="flex items-start justify-between gap-3 border-b border-border px-5 py-4">
          <div className="flex min-w-0 flex-col gap-1.5">
            <div className="truncate text-[1.05rem] font-semibold leading-tight text-foreground">
              {context?.personName ?? "Loading thread..."}
            </div>
            <div className="flex flex-wrap items-center gap-1.5">
              {context?.source?.label && (
                <Badge
                  variant="outline"
                  className="border-border text-foreground/85 text-[0.7rem] font-medium"
                  style={{ fontFamily: "var(--theme-font-mono)" }}
                >
                  {context.source.label}
                </Badge>
              )}
              {context?.source?.ownerAgent && (
                <Badge
                  variant="outline"
                  className="border-border text-foreground/85 text-[0.7rem] font-medium"
                  style={{ fontFamily: "var(--theme-font-mono)" }}
                >
                  {context.source.ownerAgent}
                </Badge>
              )}
              {meta?.label && (
                <Badge
                  variant="outline"
                  className={cn(
                    "text-[0.7rem] font-semibold",
                    meta.label === "hot" && "border-destructive/60 bg-destructive/10 text-destructive",
                    meta.label === "warm" && "border-warning/60 bg-warning/10 text-warning",
                    meta.label === "cold" && "border-border text-foreground/75",
                    meta.label === "dead" && "border-border/60 text-foreground/55",
                  )}
                  style={{ fontFamily: "var(--theme-font-mono)" }}
                >
                  {meta.label} {typeof meta.score === "number" ? meta.score : ""}
                </Badge>
              )}
              {context && (
                <span
                  className="text-[0.7rem] font-medium uppercase tracking-[0.08em] text-foreground/65"
                  style={{ fontFamily: "var(--theme-font-mono)" }}
                >
                  {context.messageCount} {context.messageCount === 1 ? "message" : "messages"}
                </span>
              )}
            </div>
          </div>
          <div className="flex items-center gap-2">
            {profile && (
              <LeadStatusControl
                profileId={profile.id}
                status={profile.status}
                onChanged={(nextInbox) => {
                  if (nextInbox) data.setSourceInbox(nextInbox);
                }}
                selectClassName="w-36"
                selectButtonClassName="h-8 px-2 text-xs"
              />
            )}
            <Button variant="ghost" size="sm" onClick={onClose} className="text-foreground/75 hover:text-foreground">
              <CloseIcon className="h-4 w-4" />
            </Button>
          </div>
        </div>

        <div className="grid min-h-0 flex-1 grid-cols-1 lg:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]">
          <div className="flex min-h-0 flex-col border-r border-border">
            <div ref={scrollRef} className="flex-1 overflow-y-auto px-5 py-5">
              {skippedDraft && (
                <div className="mb-4 rounded-md border border-warning/55 bg-warning/10 px-3.5 py-3">
                  <div
                    className="mb-1.5 flex items-center justify-between text-[0.68rem] font-semibold uppercase tracking-[0.1em] text-warning"
                    style={{ fontFamily: "var(--theme-font-mono)" }}
                  >
                    <span>Skipped draft{skippedDraft.skippedAt ? ` · ${fmtMessageTimestamp(skippedDraft.skippedAt)}` : ""}</span>
                    <span className="text-foreground/65">{skippedDraft.channel}</span>
                  </div>
                  {skippedDraft.context && (
                    <p className="mb-2 line-clamp-3 text-[0.78rem] leading-5 text-foreground/70">
                      <span
                        className="mr-1.5 uppercase tracking-[0.08em] text-foreground/55"
                        style={{ fontFamily: "var(--theme-font-mono)", fontSize: "0.65rem" }}
                      >
                        Context:
                      </span>
                      {skippedDraft.context}
                    </p>
                  )}
                  <p className="whitespace-pre-wrap break-words text-sm leading-5 text-foreground">
                    {skippedDraft.draftText || <span className="text-foreground/55 italic">(empty draft)</span>}
                  </p>
                  <div className="mt-2.5 flex justify-end">
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => void restoreSkippedDraft()}
                      disabled={restoring}
                    >
                      {restoring ? (
                        <Loader2 className="h-3.5 w-3.5 animate-spin" />
                      ) : (
                        <RotateCcw className="h-3.5 w-3.5" />
                      )}
                      Restore
                    </Button>
                  </div>
                </div>
              )}
              {loading && (
                <p className="px-1 py-1 text-xs text-muted-foreground/80">Loading thread…</p>
              )}
              {error && (
                <div className="rounded-md border border-destructive/55 bg-destructive/10 px-3 py-2 text-xs font-medium text-destructive">
                  {error}
                </div>
              )}
              {!loading && !error && messages.length === 0 && !skippedDraft && (
                <p className="px-1 py-1 text-xs text-muted-foreground/80">No messages on file yet.</p>
              )}
              {!loading && messages.length > 0 && (
                <div className="space-y-4">
                  {messages.map((message) => (
                    <ThreadMessageBubble key={message.id || `${message.timestamp}-${message.text.slice(0, 12)}`} message={message} />
                  ))}
                </div>
              )}
            </div>

            {context?.pendingDraft && (
              <div className="border-t border-border bg-background/60 px-5 py-4">
                <div
                  className="mb-2 flex items-center justify-between text-[0.68rem] font-semibold uppercase tracking-[0.1em]"
                  style={{ fontFamily: "var(--theme-font-mono)" }}
                >
                  <span className="flex items-center gap-1.5 text-primary">
                    <span className="inline-block h-1.5 w-1.5 rounded-full bg-primary" />
                    Draft reply · awaiting approval
                  </span>
                  <span className="text-foreground/65">{context.pendingDraft.channel}</span>
                </div>
                <textarea
                  value={reply}
                  onChange={(e) => setReply(e.target.value)}
                  rows={4}
                  className="w-full resize-none rounded-xl border border-border bg-background px-3 py-2.5 text-sm leading-5 text-foreground placeholder:text-foreground/45 focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/30"
                />
                <div className="mt-2.5 flex justify-end gap-2">
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => void sendDraft("skip")}
                    disabled={submitting}
                    className="text-foreground/75 hover:text-foreground"
                  >
                    Skip
                  </Button>
                  <Button size="sm" onClick={() => void sendDraft("approve")} disabled={submitting || !reply.trim()}>
                    {submitting ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Send className="h-3.5 w-3.5" />}
                    Send
                  </Button>
                </div>
              </div>
            )}
          </div>

          <div className="min-h-0 overflow-y-auto bg-background/40 px-5 py-5">
            <ThreadContextSidebar context={context} loading={loading} sends={sends} />
          </div>
        </div>
      </div>
    </div>,
    document.body,
  );
}

function ThreadContextSidebar({
  context,
  loading,
  sends,
}: {
  context: ThreadContextResponse | null;
  loading: boolean;
  sends: ThreadContextResponse["sends"];
}) {
  if (loading || !context) {
    return (
      <div className="font-mono-ui text-[0.7rem] font-semibold uppercase tracking-[0.1em] text-muted-foreground/80">
        Loading context...
      </div>
    );
  }
  const meta = context.meta;
  const lead = context.lead;
  const activity = context.activity ?? [];
  const notes = context.notes ?? [];
  const tasks = context.tasks ?? [];
  const sectionLabel =
    "font-mono-ui flex items-center gap-1.5 text-[0.68rem] font-semibold uppercase tracking-[0.12em] text-foreground/70";
  const sectionClass = "py-5 first:pt-0 last:pb-0";
  const displayScore = meta?.score ?? lead?.score ?? null;
  const scoreLabel = meta?.label ?? (lead?.stage || lead?.leadSource || null);
  const hasContact = Boolean(lead && (lead.emails.length > 0 || lead.phones.length > 0));
  return (
    <div className="divide-y divide-border/40">
      <section className={sectionClass}>
        <h4 className={sectionLabel}>Lead score</h4>
        {displayScore !== null ? (
          <>
            <div className="mt-2 flex items-baseline gap-2.5">
              <span className="text-[2.25rem] font-semibold leading-none tracking-tight text-primary">
                {displayScore}
              </span>
              {scoreLabel && (
                <span className="font-mono-ui text-[0.7rem] font-semibold uppercase tracking-[0.1em] text-foreground/70">
                  {scoreLabel}
                </span>
              )}
            </div>
            {meta?.reason && (
              <p className="mt-2.5 text-[0.8rem] leading-[1.5] text-foreground">{meta.reason}</p>
            )}
            {!meta && lead?.summary && (
              <p className="mt-2.5 text-[0.8rem] leading-[1.5] text-foreground">{lead.summary}</p>
            )}
            {lead && (lead.leadSource || lead.assignedUser || lead.tags.length > 0) && (
              <div className="mt-2.5 space-y-1.5">
                {lead.leadSource && (
                  <div className="flex items-center gap-1.5 text-[0.72rem] text-foreground/75">
                    <span className="font-mono-ui text-[0.62rem] uppercase tracking-[0.1em] text-muted-foreground/80">
                      source
                    </span>
                    <span>{lead.leadSource}</span>
                  </div>
                )}
                {lead.assignedUser && (
                  <div className="flex items-center gap-1.5 text-[0.72rem] text-foreground/75">
                    <span className="font-mono-ui text-[0.62rem] uppercase tracking-[0.1em] text-muted-foreground/80">
                      owner
                    </span>
                    <span>{lead.assignedUser}</span>
                  </div>
                )}
                {lead.tags.length > 0 && (
                  <div className="flex flex-wrap gap-1.5 pt-1">
                    {lead.tags
                      .filter((t) => t !== "crm-lead" && !t.endsWith("-crm"))
                      .slice(0, 6)
                      .map((tag) => (
                        <span
                          key={tag}
                          className="font-mono-ui inline-flex items-center rounded-full border border-border/60 bg-background px-2 py-0.5 text-[0.65rem] font-medium text-foreground/75"
                        >
                          {tag}
                        </span>
                      ))}
                  </div>
                )}
              </div>
            )}
            {(meta?.scoredBy || meta?.scoredAt) && (
              <div className="font-mono-ui mt-2.5 text-[0.66rem] uppercase tracking-[0.08em] text-muted-foreground/80">
                {meta.scoredBy ? `by ${meta.scoredBy}` : null}
                {meta.scoredBy && meta.scoredAt ? " · " : ""}
                {meta.scoredAt ? fmtMessageTimestamp(meta.scoredAt) : ""}
              </div>
            )}
          </>
        ) : (
          <p className="mt-2 text-[0.8rem] text-muted-foreground">Not yet scored.</p>
        )}
      </section>

      {hasContact && lead && (
        <section className={sectionClass}>
          <h4 className={sectionLabel}>Contact</h4>
          <div className="mt-2 space-y-1">
            {lead.phones.slice(0, 3).map((phone) => (
              <div key={phone} className="text-[0.8rem] text-foreground">
                {phone}
              </div>
            ))}
            {lead.emails.slice(0, 3).map((email) => (
              <div key={email} className="truncate text-[0.8rem] text-foreground">
                {email}
              </div>
            ))}
          </div>
        </section>
      )}

      <section className={sectionClass}>
        <h4 className={sectionLabel}>
          <StickyNote className="h-3 w-3" />
          Notes
          {notes.length > 0 && (
            <span className="font-mono-ui text-[0.62rem] font-medium text-muted-foreground/70">
              {notes.length}
            </span>
          )}
        </h4>
        {notes.length === 0 ? (
          <p className="mt-2 text-[0.8rem] leading-[1.5] text-muted-foreground">
            {lead?.summary || "No notes yet."}
          </p>
        ) : (
          <ul className="mt-2 space-y-2.5">
            {notes.slice(0, 8).map((note) => (
              <li key={note.id} className="rounded-md border border-border/40 bg-background/60 px-3 py-2">
                <div className="font-mono-ui flex items-center justify-between gap-2 text-[0.62rem] font-semibold uppercase tracking-[0.1em] text-muted-foreground">
                  <span>{note.author || "note"}</span>
                  {note.timestamp && (
                    <span className="text-muted-foreground/70">{fmtMessageTimestamp(note.timestamp)}</span>
                  )}
                </div>
                <p className="mt-1 whitespace-pre-line text-[0.8rem] leading-[1.5] text-foreground">
                  {note.summary}
                </p>
              </li>
            ))}
          </ul>
        )}
      </section>

      {tasks.length > 0 && (
        <section className={sectionClass}>
          <h4 className={sectionLabel}>
            <CheckSquare className="h-3 w-3" />
            Tasks
            <span className="font-mono-ui text-[0.62rem] font-medium text-muted-foreground/70">
              {tasks.length}
            </span>
          </h4>
          <ul className="mt-2 space-y-1.5">
            {tasks.slice(0, 6).map((task) => (
              <li key={task.id} className="flex items-start gap-2">
                <span
                  className={cn(
                    "mt-1 h-1.5 w-1.5 shrink-0 rounded-full",
                    task.status === "done"
                      ? "bg-success"
                      : task.status === "in_progress"
                        ? "bg-primary"
                        : "bg-muted-foreground/60"
                  )}
                  aria-hidden
                />
                <div className="min-w-0 flex-1">
                  <div className="text-[0.8rem] leading-[1.4] text-foreground">
                    {task.title}
                  </div>
                  {(task.dueAt || task.status) && (
                    <div className="font-mono-ui mt-0.5 flex items-center gap-1.5 text-[0.62rem] uppercase tracking-[0.1em] text-muted-foreground">
                      <span>{task.status.replace(/_/g, " ")}</span>
                      {task.dueAt && (
                        <>
                          <span aria-hidden>·</span>
                          <span>due {fmtMessageTimestamp(task.dueAt)}</span>
                        </>
                      )}
                    </div>
                  )}
                </div>
              </li>
            ))}
          </ul>
        </section>
      )}

      <section className={sectionClass}>
        <h4 className={sectionLabel}>
          <Activity className="h-3 w-3" />
          Property activity
          {activity.length > 0 && (
            <span className="font-mono-ui text-[0.62rem] font-medium text-muted-foreground/70">
              {activity.length}
            </span>
          )}
        </h4>
        {activity.length === 0 ? (
          <p className="mt-2 text-[0.8rem] leading-[1.5] text-muted-foreground">
            No activity logged yet.
          </p>
        ) : (
          <ul className="mt-2 divide-y divide-border/30">
            {activity.slice(0, 8).map((event) => {
              const label = (event.subtype || event.type).replace(/_/g, " ");
              return (
                <li key={event.id} className="py-2.5 first:pt-0 last:pb-0">
                  <div className="font-mono-ui flex items-center justify-between gap-2 text-[0.66rem] font-semibold uppercase tracking-[0.08em] text-muted-foreground">
                    <span>{label}</span>
                    {event.timestamp && (
                      <span className="text-muted-foreground/80">{fmtMessageTimestamp(event.timestamp)}</span>
                    )}
                  </div>
                  {(event.title || event.summary) && (
                    <p className="mt-1 line-clamp-2 text-[0.8rem] leading-[1.45] text-foreground">
                      {event.title || event.summary}
                    </p>
                  )}
                  {event.address && (
                    <p className="font-mono-ui mt-0.5 text-[0.66rem] uppercase tracking-[0.08em] text-muted-foreground/80">
                      {event.address}
                    </p>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </section>

      <section className={sectionClass}>
        <h4 className={sectionLabel}>Send history</h4>
        {sends.length === 0 ? (
          <p className="mt-2 text-[0.8rem] text-muted-foreground">No prior sends.</p>
        ) : (
          <ul className="mt-2 divide-y divide-border/30">
            {sends.slice(0, 8).map((send) => (
              <li key={send.id} className="py-2.5 first:pt-0 last:pb-0">
                <div className="font-mono-ui flex items-center justify-between gap-2 text-[0.66rem] font-semibold uppercase tracking-[0.08em]">
                  <span className="text-foreground/75">{send.channel ?? "send"}</span>
                  <span
                    className={cn(
                      send.status === "sent" || send.status === "delivered"
                        ? "text-success"
                        : send.status === "failed"
                          ? "text-destructive"
                          : "text-muted-foreground",
                    )}
                  >
                    {send.status ?? "unknown"}
                  </span>
                </div>
                {(() => {
                  // Codex audit P2 (2026-05-05): older outreach_db rows
                  // store the body at payload.draft_text; future
                  // operational.db rows may put it at the top level.
                  // Fall back through every shape we've shipped so the
                  // history doesn't render blank.
                  const body =
                    (send.payload?.text as string | undefined) ||
                    (send.payload?.draft_text as string | undefined) ||
                    ((send as { draftText?: string }).draftText) ||
                    ((send as { text?: string }).text);
                  return body ? (
                    <p className="mt-1 line-clamp-3 text-[0.8rem] leading-[1.45] text-foreground">
                      {String(body)}
                    </p>
                  ) : null;
                })()}
                {send.createdAt && (
                  <div className="font-mono-ui mt-1 text-[0.65rem] uppercase tracking-[0.08em] text-muted-foreground/80">
                    {fmtMessageTimestamp(send.createdAt)}
                  </div>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}

```

---
## `src/pages/real-estate-hub/admin-setup.ts`
```ts
import type { AdminSetupItemStatus, AdminSetupSnapshot } from "@/lib/api";

export type AdminSetupDraft = {
  realtorLegalName: string;
  licenseName: string;
  brokerageName: string;
  teamName: string;
  province: string;
  market: string;
  boardMemberships: string;
  managingBrokerEmail: string;
  approvalChannel: string;
  emailProvider: string;
  calendarProvider: string;
  driveProvider: string;
  crmProvider: string;
  mlsProvider: string;
  formsProvider: string;
  signingProvider: string;
  complianceProvider: string;
  showingProvider: string;
  photoProcessingProvider: string;
  mlsLoginUrl: string;
  mlsLoginEmail: string;
  mlsLoginPassword: string;
  complianceLoginUrl: string;
  complianceLoginEmail: string;
  complianceLoginPassword: string;
  showingLoginUrl: string;
  showingLoginEmail: string;
  showingLoginPassword: string;
  browserWorkflowNotes: string;
  fintracProvider: string;
  defaultFolderPattern: string;
  commissionNotes: string;
  servicesSchedule: string;
  regionalMemory: string;
  approvalPolicy: string;
};

export const ADMIN_SETUP_PROVIDER_ITEMS: Array<{
  key: string;
  field: keyof AdminSetupDraft;
  status: AdminSetupItemStatus;
}> = [
  { key: "approval_channel", field: "approvalChannel", status: "connected" },
  { key: "email", field: "emailProvider", status: "connected" },
  { key: "calendar", field: "calendarProvider", status: "connected" },
  { key: "drive", field: "driveProvider", status: "connected" },
  { key: "crm", field: "crmProvider", status: "connected" },
  { key: "mls", field: "mlsProvider", status: "connected" },
  { key: "forms_provider", field: "formsProvider", status: "configured" },
  { key: "signing_provider", field: "signingProvider", status: "configured" },
  { key: "compliance_platform", field: "complianceProvider", status: "configured" },
  { key: "showing_platform", field: "showingProvider", status: "configured" },
  { key: "photo_processing", field: "photoProcessingProvider", status: "configured" },
  { key: "fintrac_workflow", field: "fintracProvider", status: "manual" },
];

export function setupRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

export function setupString(value: unknown): string {
  return typeof value === "string" ? value : "";
}

export function adminSetupDraftFromSnapshot(setup: AdminSetupSnapshot): AdminSetupDraft {
  const profile = setup.profile;
  const itemsByKey = new Map(setup.items.map((item) => [item.key, item]));
  const photoValue = setupRecord(itemsByKey.get("photo_processing")?.value);
  const browserValue = setupRecord(itemsByKey.get("browser_workflows")?.value);
  const playbooks = setupRecord(browserValue.playbooks);
  const mlsPlaybook = setupRecord(playbooks.mls);
  const compliancePlaybook = setupRecord(playbooks.compliance);
  const showingPlaybook = setupRecord(playbooks.showing);
  const regionalMemory = profile.regionalMemory && typeof profile.regionalMemory.notes === "string"
    ? profile.regionalMemory.notes
    : "";
  const approvalPolicy = profile.approvalPolicy && typeof profile.approvalPolicy.notes === "string"
    ? profile.approvalPolicy.notes
    : "";
  return {
    realtorLegalName: profile.realtorLegalName ?? "",
    licenseName: profile.licenseName ?? "",
    brokerageName: profile.brokerageName ?? "",
    teamName: profile.teamName ?? "",
    province: profile.province ?? "",
    market: profile.market ?? "",
    boardMemberships: (profile.boardMemberships ?? []).join(", "),
    managingBrokerEmail: profile.managingBrokerEmail ?? "",
    approvalChannel: profile.approvalChannel ?? "",
    emailProvider: profile.emailProvider ?? "",
    calendarProvider: profile.calendarProvider ?? "",
    driveProvider: profile.driveProvider ?? "",
    crmProvider: profile.crmProvider ?? "",
    mlsProvider: profile.mlsProvider ?? "",
    formsProvider: profile.formsProvider ?? "",
    signingProvider: profile.signingProvider ?? "",
    complianceProvider: profile.complianceProvider ?? "",
    showingProvider: profile.showingProvider ?? "",
    photoProcessingProvider: setupString(photoValue.provider),
    mlsLoginUrl: setupString(mlsPlaybook.loginUrl),
    mlsLoginEmail: setupString(mlsPlaybook.loginEmail),
    mlsLoginPassword: setupString(mlsPlaybook.loginPassword) || setupString(mlsPlaybook.credentialRef),
    complianceLoginUrl: setupString(compliancePlaybook.loginUrl),
    complianceLoginEmail: setupString(compliancePlaybook.loginEmail),
    complianceLoginPassword: setupString(compliancePlaybook.loginPassword) || setupString(compliancePlaybook.credentialRef),
    showingLoginUrl: setupString(showingPlaybook.loginUrl),
    showingLoginEmail: setupString(showingPlaybook.loginEmail),
    showingLoginPassword: setupString(showingPlaybook.loginPassword) || setupString(showingPlaybook.credentialRef),
    browserWorkflowNotes: setupString(browserValue.notes),
    fintracProvider: profile.fintracProvider ?? "",
    defaultFolderPattern: profile.defaultFolderPattern ?? "Address - Client - Deal Type",
    commissionNotes: profile.commissionNotes ?? "",
    servicesSchedule: profile.servicesSchedule ?? "",
    regionalMemory,
    approvalPolicy,
  };
}

export function splitAdminSetupList(value: string): string[] {
  return value
    .split(/[,\n]/)
    .map((item) => item.trim())
    .filter(Boolean);
}

export function adminSetupPayloadFromDraft(draft: AdminSetupDraft) {
  const browserPlaybooks = {
    mls: {
      provider: draft.mlsProvider.trim(),
      loginUrl: draft.mlsLoginUrl.trim(),
      loginEmail: draft.mlsLoginEmail.trim(),
      loginPassword: draft.mlsLoginPassword,
      notes: draft.browserWorkflowNotes.trim(),
    },
    compliance: {
      provider: draft.complianceProvider.trim(),
      loginUrl: draft.complianceLoginUrl.trim(),
      loginEmail: draft.complianceLoginEmail.trim(),
      loginPassword: draft.complianceLoginPassword,
      notes: draft.browserWorkflowNotes.trim(),
    },
    showing: {
      provider: draft.showingProvider.trim(),
      loginUrl: draft.showingLoginUrl.trim(),
      loginEmail: draft.showingLoginEmail.trim(),
      loginPassword: draft.showingLoginPassword,
      notes: draft.browserWorkflowNotes.trim(),
    },
  };
  const browserWorkflowReady = Object.values(browserPlaybooks).every(
    (playbook) => playbook.provider && (playbook.loginUrl || playbook.loginEmail || playbook.loginPassword || playbook.notes),
  );
  const items = [
    {
      key: "identity_profile",
      status: draft.realtorLegalName.trim() && draft.brokerageName.trim() ? "configured" : "missing",
      provider: draft.brokerageName.trim() || null,
      value: {
        realtorLegalName: draft.realtorLegalName.trim(),
        licenseName: draft.licenseName.trim(),
        brokerageName: draft.brokerageName.trim(),
        teamName: draft.teamName.trim(),
        managingBrokerEmail: draft.managingBrokerEmail.trim(),
      },
    },
    {
      key: "jurisdiction",
      status: draft.province.trim() ? "configured" : "missing",
      provider: draft.province.trim().toUpperCase() || null,
      value: {
        country: "CA",
        province: draft.province.trim().toUpperCase(),
        market: draft.market.trim(),
        boards: splitAdminSetupList(draft.boardMemberships),
      },
    },
    {
      key: "regional_memory",
      status: draft.regionalMemory.trim() ? "configured" : "missing",
      provider: draft.province.trim().toUpperCase() || null,
      value: {
        notes: draft.regionalMemory.trim(),
        market: draft.market.trim(),
        boards: splitAdminSetupList(draft.boardMemberships),
      },
    },
    {
      key: "browser_workflows",
      status: browserWorkflowReady ? "configured" : "missing",
      provider: "browser-use",
      value: {
        mode: "browser-use",
        notes: draft.browserWorkflowNotes.trim(),
        playbooks: browserPlaybooks,
      },
    },
    ...ADMIN_SETUP_PROVIDER_ITEMS.map((item) => {
      const value = String(draft[item.field] ?? "").trim();
      return {
        key: item.key,
        status: value ? item.status : "missing",
        provider: value || null,
        value: value ? { provider: value } : null,
      };
    }),
  ] satisfies Array<{
    key: string;
    status: AdminSetupItemStatus;
    provider?: string | null;
    value?: unknown;
  }>;
  return {
    profile: {
      realtorLegalName: draft.realtorLegalName,
      licenseName: draft.licenseName,
      brokerageName: draft.brokerageName,
      teamName: draft.teamName,
      country: "CA",
      province: draft.province,
      market: draft.market,
      boardMemberships: splitAdminSetupList(draft.boardMemberships),
      managingBrokerEmail: draft.managingBrokerEmail,
      approvalChannel: draft.approvalChannel,
      emailProvider: draft.emailProvider,
      calendarProvider: draft.calendarProvider,
      driveProvider: draft.driveProvider,
      crmProvider: draft.crmProvider,
      mlsProvider: draft.mlsProvider,
      formsProvider: draft.formsProvider,
      signingProvider: draft.signingProvider,
      complianceProvider: draft.complianceProvider,
      showingProvider: draft.showingProvider,
      fintracProvider: draft.fintracProvider,
      defaultFolderPattern: draft.defaultFolderPattern,
      commissionNotes: draft.commissionNotes,
      servicesSchedule: draft.servicesSchedule,
      regionalMemory: { notes: draft.regionalMemory },
      approvalPolicy: { notes: draft.approvalPolicy },
    },
    items,
  };
}

```

---
## `src/pages/real-estate-hub/profile-workflow.ts`
```ts
import type {
  AdminDealSide,
  AgentHandoff,
  SourceInboxProfile,
  SourceInboxProfileVerifier,
  SourceInboxThread,
} from "@/lib/api";

export function profileSortTime(profile: SourceInboxProfile): number {
  const ms = Date.parse(profile.latestAt || "");
  return Number.isFinite(ms) ? ms : 0;
}

export function profileContactLine(profile: SourceInboxProfile): string {
  const contacts = [...profile.phones.slice(0, 1), ...profile.emails.slice(0, 1)];
  return contacts.length ? contacts.join(" · ") : "No phone or email yet";
}

export type ProfileAdminDealIds = Partial<Record<AdminDealSide, string>>;

export type ProfilePendingAdminAction = {
  profileId: string;
  side: AdminDealSide;
};

export type ProfileHandoffIds = Partial<Record<AdminDealSide, AgentHandoff>>;

export type ProfileActionBucketId = "active-conversation" | "push-admin" | "needs-verifier" | "follow-up" | "in-admin";

export const PROFILE_WORKFLOW_JOB_PREFIX = "Lead profile workflow";

export const PROFILE_ACTION_BUCKETS: Array<{
  id: ProfileActionBucketId;
  label: string;
  description: string;
}> = [
  {
    id: "active-conversation",
    label: "Active conversations",
    description: "People they are actively messaging stay first, sorted by the newest conversation activity.",
  },
  {
    id: "push-admin",
    label: "Ready for skill handoff",
    description: "Verified hot or potential leads ready for a buyer workflow or seller CMA before Admin handoff.",
  },
  {
    id: "needs-verifier",
    label: "Needs phone or email",
    description: "People with useful conversation context but no matching verifier yet.",
  },
  {
    id: "follow-up",
    label: "Follow up",
    description: "Lower-urgency profiles to review, message, or keep watching from the source inbox.",
  },
  {
    id: "in-admin",
    label: "Already in Admin",
    description: "Profiles already pushed into Buyers Admin, Sellers Admin, or both.",
  },
];

export const PROFILE_ADMIN_SIDE_COPY = {
  listing: {
    actionLabel: "Run CMA skill",
    queuedLabel: "CMA queued",
    openLabel: "Open Sellers",
    badgeLabel: "Sellers Admin",
    queuedBadgeLabel: "CMA skill queued",
    workflow: "seller-cma-admin",
    skill: "cma",
    workflowLabel: "Seller CMA",
    errorLabel: "CMA skill",
  },
  buyer: {
    actionLabel: "Run buyer skill",
    queuedLabel: "Buyer queued",
    openLabel: "Open Buyers",
    badgeLabel: "Buyers Admin",
    queuedBadgeLabel: "buyer skill queued",
    workflow: "buyer-admin-intake",
    skill: "outreach",
    workflowLabel: "Buyer qualification",
    errorLabel: "buyer workflow",
  },
} satisfies Record<
  AdminDealSide,
  {
    actionLabel: string;
    queuedLabel: string;
    openLabel: string;
    badgeLabel: string;
    queuedBadgeLabel: string;
    workflow: string;
    skill: string;
    workflowLabel: string;
    errorLabel: string;
  }
>;

export function profileWorkflowToken(side: AdminDealSide): string {
  return side === "listing" ? "seller-cma" : "buyer-admin";
}

export function profileSkillWorkflowName(profile: SourceInboxProfile, side: AdminDealSide): string {
  const name = profile.displayName?.trim() || "New profile";
  return `${PROFILE_WORKFLOW_JOB_PREFIX}: ${profileWorkflowToken(side)}: ${name}: ${profile.id}`;
}

export function profileHandoffSide(handoff: AgentHandoff): AdminDealSide | null {
  const payload = handoff.payload ?? {};
  const side = payload.targetSide;
  if (side === "listing" || side === "buyer") return side;
  const workflow = String(payload.workflow ?? "").toLowerCase();
  if (workflow.includes("seller") || workflow.includes("listing")) return "listing";
  if (workflow.includes("buyer")) return "buyer";
  const title = handoff.title.toLowerCase();
  if (title.includes("seller-cma")) return "listing";
  if (title.includes("buyer-admin")) return "buyer";
  return null;
}

export function profileHandoffIsActive(handoff: AgentHandoff | undefined): boolean {
  if (!handoff) return false;
  return ["queued", "running", "waiting_human"].includes(String(handoff.status));
}

export function profileHandoffBadgeLabel(handoff: AgentHandoff | undefined, side: AdminDealSide): string | null {
  if (!handoff) return null;
  const label = PROFILE_ADMIN_SIDE_COPY[side].workflowLabel;
  if (handoff.status === "completed") return `${label} done`;
  if (handoff.status === "failed") return `${label} failed`;
  if (handoff.status === "cancelled") return `${label} cancelled`;
  if (handoff.status === "waiting_human") return `${label} waiting`;
  return PROFILE_ADMIN_SIDE_COPY[side].queuedBadgeLabel;
}

export function profileSkillWorkflowContext(profile: SourceInboxProfile, side: AdminDealSide): string {
  const sideCopy = PROFILE_ADMIN_SIDE_COPY[side];
  return JSON.stringify(
    {
      profileId: profile.id,
      targetSide: side,
      workflow: sideCopy.workflow,
      skill: sideCopy.skill,
      displayName: profile.displayName,
      primaryContactId: profilePrimaryContactId(profile),
      contactIds: profile.contactIds ?? [],
      conversationIds: profile.conversationIds ?? [],
      threadIds: profile.threadIds,
      sourceIds: profile.sourceIds,
      sources: profile.sources,
      channels: profile.channels,
      phones: profile.phones,
      emails: profile.emails,
      verifiers: profileVerifiers(profile),
      latestText: profile.latestText,
      latestAt: profile.latestAt,
      heatScore: profile.heatScore,
      heatLabel: profile.heatLabel,
      tags: profile.tags,
      sourceMeta: profileSourceMeta(profile),
    },
    null,
    2,
  );
}

export function profileSkillWorkflowPrompt(profile: SourceInboxProfile, side: AdminDealSide): string {
  const sideCopy = PROFILE_ADMIN_SIDE_COPY[side];
  const context = profileSkillWorkflowContext(profile, side);
  if (side === "listing") {
    return `Run the seller CMA handoff for this lead profile.

Profile context:
${context}

Workflow rules:
1. This is a skill-owned handoff, not a direct dashboard push to Sellers Admin.
2. Confirm from the profile, thread history, or source records that there is enough seller appointment/property context to run the CMA.
3. If the property address or appointment context is missing, draft or queue the next same-channel follow-up needed to get it. Do not fabricate missing details and do not create an Admin record yet.
4. Once the appointment/property context is present, run the installed CMA skill workflow. Preserve CMA handoffs and generated artifacts.
5. Only after the CMA outputs are complete, use the admin_profile tool with action=promote, side=listing, profile_id=${profile.id}, workflow=${sideCopy.workflow}, profile_context from above, and the available verifiers/contact ids. Do not create a duplicate deal manually.
6. Hand control to Admin by using the Admin stage mutation after the record exists. Move or re-enter the listing card at Admin stage 0 (CMA / Prospect) unless the CMA outcome clearly belongs in a later listing stage. This stage event is what lets the Admin action registry run next.
7. Leave a concise run note explaining whether the person stayed in lead follow-up or moved into CMA/Admin.`;
  }

  return `Run the buyer qualification handoff for this lead profile.

Profile context:
${context}

Workflow rules:
1. This is a skill-owned handoff, not a direct dashboard push to Buyers Admin.
2. Use the outreach/lead context to determine whether a buyer appointment, qualification, financing, search criteria, or follow-up is still needed.
3. If qualification details are missing, draft or queue the next same-channel message needed to collect them. Do not fabricate budget, financing, timeline, or area criteria.
4. After the buyer workflow has enough appointment and qualification context, use the admin_profile tool with action=promote, side=buyer, profile_id=${profile.id}, workflow=${sideCopy.workflow}, profile_context from above, and the available verifiers/contact ids. Do not create a duplicate deal manually.
5. Hand control to Admin by using the Admin stage mutation after the record exists. Move or re-enter the buyer card at Admin stage 0 (Intake) unless the qualification outcome clearly belongs in a later buyer stage. This stage event is what lets the Admin action registry run next.
6. Leave a concise run note explaining whether the person stayed in lead follow-up or moved into Buyers Admin.`;
}

export function profileSourceMeta(profile: SourceInboxProfile): string {
  const sources = profile.sources.length ? profile.sources.slice(0, 2).join(" + ") : "Source inbox";
  const channels = profile.channels.length ? profile.channels.slice(0, 2).join(" + ") : "unknown channel";
  return `${sources} / ${channels}`;
}

export function profilePrimaryContactId(profile: SourceInboxProfile): string | null {
  return profile.contactIds?.[0] ?? null;
}

export function profileVerifiers(profile: SourceInboxProfile): SourceInboxProfileVerifier[] {
  return (profile.verifiers ?? []).filter((verifier) => verifier.key && verifier.value);
}

export function verifierSummary(verifiers: SourceInboxProfileVerifier[]): string {
  const kinds = Array.from(new Set(verifiers.map((verifier) => verifier.kind))).sort();
  if (!kinds.length) return "needs phone/email";
  return `verified by ${kinds.join(" + ")}`;
}

export function profileVerifierSummary(profile: SourceInboxProfile): string {
  return verifierSummary(profileVerifiers(profile));
}

export function profileHasVerifier(profile: SourceInboxProfile): boolean {
  return profileVerifiers(profile).length > 0;
}

export function profileHasAdminDeal(dealIds?: ProfileAdminDealIds): boolean {
  return Boolean(dealIds?.listing || dealIds?.buyer);
}

export function threadSortTime(thread: SourceInboxThread): number {
  const ms = Date.parse(thread.latestAt || "");
  return Number.isFinite(ms) ? ms : 0;
}

export function isActiveProfileThread(thread: SourceInboxThread): boolean {
  const status = String(thread.status || "open").toLowerCase();
  return status !== "done" && status !== "archived";
}

export function profileHasActiveConversation(
  profile: SourceInboxProfile,
  threadsForProfile?: SourceInboxThread[],
): boolean {
  if (!profile.hasConversation || profile.threadCount < 1) return false;
  if (!threadsForProfile?.length) return true;
  return threadsForProfile.some(isActiveProfileThread);
}

export function profileActionBucket(
  profile: SourceInboxProfile,
  dealIds?: ProfileAdminDealIds,
  activeConversation = false,
): ProfileActionBucketId {
  if (activeConversation) return "active-conversation";
  if (profileHasAdminDeal(dealIds)) return "in-admin";
  if (!profileHasVerifier(profile)) return "needs-verifier";
  if (profile.isPotentialLead || profile.heatLabel === "hot" || profile.heatLabel === "warm") return "push-admin";
  return "follow-up";
}

export function profileActionSort(a: SourceInboxProfile, b: SourceInboxProfile): number {
  if (a.isPotentialLead !== b.isPotentialLead) return a.isPotentialLead ? -1 : 1;
  const heat = (b.heatScore ?? 0) - (a.heatScore ?? 0);
  if (heat !== 0) return heat;
  return profileSortTime(b) - profileSortTime(a);
}

export function profileConversationSort(a: SourceInboxProfile, b: SourceInboxProfile): number {
  const recency = profileSortTime(b) - profileSortTime(a);
  if (recency !== 0) return recency;
  const heat = (b.heatScore ?? 0) - (a.heatScore ?? 0);
  if (heat !== 0) return heat;
  return a.displayName.localeCompare(b.displayName);
}

```

---
## `src/pages/real-estate-hub/utils.ts`
```ts
import type { SourceInboxProfile, SourceInboxResponse, SourceInboxThread } from "@/lib/api";
import { isoTimeAgo } from "@/lib/utils";

export function threadWhen(thread: SourceInboxThread): string {
  return thread.latestAt ? isoTimeAgo(thread.latestAt) : "unsynced";
}

export function heatVariant(item: { heatLabel: string }): "default" | "success" | "warning" | "destructive" | "outline" {
  if (item.heatLabel === "hot") return "destructive";
  if (item.heatLabel === "warm") return "warning";
  if (item.heatLabel === "watch") return "success";
  return "outline";
}

export type HeatTone = {
  dot: string;
  pill: string;
  text: string;
  ring: string;
  label: string;
};

export function heatStyles(label: string): HeatTone {
  switch (label) {
    case "hot":
      return {
        dot: "bg-destructive",
        pill: "bg-destructive/12 text-destructive border-destructive/45",
        text: "text-destructive",
        ring: "ring-destructive/30",
        label: "Hot lead",
      };
    case "warm":
      return {
        dot: "bg-warning",
        pill: "bg-warning/12 text-warning border-warning/45",
        text: "text-warning",
        ring: "ring-warning/30",
        label: "Warm lead",
      };
    case "watch":
      return {
        dot: "bg-success",
        pill: "bg-success/12 text-success border-success/40",
        text: "text-success",
        ring: "ring-success/30",
        label: "Lead to watch",
      };
    case "dead":
      return {
        dot: "bg-foreground/30",
        pill: "bg-card text-foreground/55 border-border line-through",
        text: "text-foreground/55",
        ring: "ring-border",
        label: "Dead lead",
      };
    default:
      return {
        dot: "bg-foreground/40",
        pill: "bg-card text-foreground/70 border-border",
        text: "text-foreground/70",
        ring: "ring-border",
        label: "Cold lead",
      };
  }
}

export function inboundWaitMinutes(thread: SourceInboxThread): number | null {
  if (!thread.latestAt) return null;
  if (thread.direction !== "inbound") return null;
  const ts = Date.parse(thread.latestAt);
  if (Number.isNaN(ts)) return null;
  return Math.max(0, (Date.now() - ts) / 60000);
}

export type ResponsePulse = {
  unanswered: number;
  median: number | null;
  longest: number | null;
  longestThread: SourceInboxThread | null;
  breached5: number;
  breached30: number;
  breached60: number;
};

export function computeResponsePulse(threads: SourceInboxThread[]): ResponsePulse {
  const waits: Array<{ minutes: number; thread: SourceInboxThread }> = [];
  for (const thread of threads) {
    const minutes = inboundWaitMinutes(thread);
    if (minutes === null) continue;
    waits.push({ minutes, thread });
  }
  if (waits.length === 0) {
    return {
      unanswered: 0,
      median: null,
      longest: null,
      longestThread: null,
      breached5: 0,
      breached30: 0,
      breached60: 0,
    };
  }
  const sorted = waits.slice().sort((a, b) => a.minutes - b.minutes);
  const mid = Math.floor(sorted.length / 2);
  const median =
    sorted.length % 2 === 1
      ? sorted[mid].minutes
      : (sorted[mid - 1].minutes + sorted[mid].minutes) / 2;
  const longest = sorted[sorted.length - 1];
  return {
    unanswered: waits.length,
    median,
    longest: longest.minutes,
    longestThread: longest.thread,
    breached5: waits.filter((w) => w.minutes >= 5).length,
    breached30: waits.filter((w) => w.minutes >= 30).length,
    breached60: waits.filter((w) => w.minutes >= 60).length,
  };
}

export function formatMinutes(minutes: number | null): string {
  if (minutes == null) return "—";
  if (minutes < 1) return "<1m";
  if (minutes < 60) return `${Math.round(minutes)}m`;
  if (minutes < 1440) {
    const h = Math.floor(minutes / 60);
    const m = Math.round(minutes - h * 60);
    return m ? `${h}h ${m}m` : `${h}h`;
  }
  return `${Math.floor(minutes / 1440)}d`;
}
const FOLLOWUP_CHANNELS = new Set([
  "email",
  "gmail",
  "sms",
  "imessage",
  "messenger",
  "facebook",
  "instagram",
  "instagram_dm",
  "whatsapp",
  "telegram",
]);

export function isFollowUpThread(thread: SourceInboxThread): boolean {
  const channel = (thread.channel || "").toLowerCase();
  if (!FOLLOWUP_CHANNELS.has(channel)) return false;
  // First outreach must have happened — at least one outbound from us.
  if ((thread.outboundCount ?? 0) < 1) return false;
  // Ball is in our court: last message came in.
  return thread.direction === "inbound";
}

export function leadSectionCount(
  sourceInbox: SourceInboxResponse | null | undefined,
  sectionId: string,
  fallback = 0,
): number {
  const value = sourceInbox?.leadSections?.[sectionId]?.count;
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

function threadMatchesSectionId(thread: SourceInboxThread, id: string): boolean {
  if (thread.id === id) return true;
  if (thread.threadId === id) return true;
  if (thread.conversationId && thread.conversationId === id) return true;
  return false;
}

export function leadSectionThreads(
  threads: SourceInboxThread[],
  sourceInbox: SourceInboxResponse | null | undefined,
  sectionId: string,
  fallback: SourceInboxThread[],
): SourceInboxThread[] {
  const section = sourceInbox?.leadSections?.[sectionId];
  if (!section) return fallback;
  const threadIds = new Set(section.threadIds ?? []);
  return threads.filter((thread) => {
    if (thread.leadSectionIds?.includes(sectionId)) return true;
    if (threadIds.size === 0) return false;
    for (const id of threadIds) {
      if (threadMatchesSectionId(thread, id)) return true;
    }
    return false;
  });
}

export function leadThreadBuckets(threads: SourceInboxThread[]) {
  const hot = threads.filter((thread) => thread.heatLabel === "hot").slice(0, 10);
  const followUp = threads
    .filter(isFollowUpThread)
    .sort((a, b) => {
      const heatDiff = (b.heatScore ?? 0) - (a.heatScore ?? 0);
      if (heatDiff !== 0) return heatDiff;
      const aTime = a.latestAt ? Date.parse(a.latestAt) : 0;
      const bTime = b.latestAt ? Date.parse(b.latestAt) : 0;
      return bTime - aTime;
    })
    .slice(0, 12);
  const placed = new Set<string>([...hot, ...followUp].map((t) => t.id));
  const remaining = threads.filter((thread) => !placed.has(thread.id));
  const watch: SourceInboxThread[] = [];
  const seenSources = new Set<string>(
    [...hot, ...followUp].map((t) => String(t.sourceId ?? "")),
  );
  for (const thread of remaining) {
    const sid = String(thread.sourceId ?? "");
    if (!seenSources.has(sid) && watch.length < 10) {
      watch.push(thread);
      seenSources.add(sid);
    }
  }
  for (const thread of remaining) {
    if (watch.length >= 10) break;
    if (!watch.includes(thread)) watch.push(thread);
  }
  return { followUp, hot, watch };
}
export function contactBuckets(profiles: SourceInboxProfile[]) {
  const crmContacts = profiles.filter((profile) => profile.hasCrm).slice(0, 12);
  const active = profiles
    .filter((profile) => !profile.hasCrm && profile.hasConversation && !profile.isPotentialLead)
    .slice(0, 8);
  const potential = profiles
    .filter((profile) => profile.isPotentialLead && !profile.hasCrm)
    .slice(0, 8);
  return { active, crmContacts, potential };
}

export function profileWhen(profile: SourceInboxProfile): string {
  return profile.latestAt ? isoTimeAgo(profile.latestAt) : "unsynced";
}

```
