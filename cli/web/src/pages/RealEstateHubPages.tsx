import {
  createElement,
  memo,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ComponentType,
  type ReactNode,
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
  Database as DatabaseIcon,
  ExternalLink,
  FileCheck2,
  FileText,
  Flame,
  Filter,
  Home,
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
  AdminDealSide,
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
  SourceInboxThread,
} from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button, buttonVariants } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { cn, isoTimeAgo } from "@/lib/utils";
import { ThreadDrawerProvider, useThreadDrawer } from "@/pages/real-estate-hub/thread-drawer";
import {
  computeResponsePulse,
  formatMinutes,
  heatStyles,
  heatVariant,
  inboundWaitMinutes,
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
  profileHandoffBadgeLabel,
  profileHandoffIsActive,
  profileHandoffSide,
  profilePrimaryContactId,
  profileSkillWorkflowContext,
  profileSkillWorkflowName,
  profileSkillWorkflowPrompt,
  profileSourceMeta,
  profileVerifierSummary,
  profileVerifiers,
  threadSortTime,
  type ProfileActionBucketId,
  type ProfileAdminDealIds,
  type ProfileHandoffIds,
  type ProfilePendingAdminAction,
} from "@/pages/real-estate-hub/profile-workflow";
import {
  HubShell,
  jobMatches,
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

export type { BoardAction, HubData };

function LeadProfilesWorkbench({
  onChanged,
  showHeader = true,
  profiles,
  threads,
}: {
  onChanged: () => Promise<void>;
  showHeader?: boolean;
  profiles: SourceInboxProfile[];
  threads: SourceInboxThread[];
}) {
  const drawer = useThreadDrawer();
  const navigate = useNavigate();
  const [pendingProfileAction, setPendingProfileAction] = useState<ProfilePendingAdminAction | null>(null);
  const [profileHandoffs, setProfileHandoffs] = useState<Record<string, ProfileHandoffIds>>({});
  const [existingDealIds, setExistingDealIds] = useState<Record<string, ProfileAdminDealIds>>({});
  const [errors, setErrors] = useState<Record<string, string>>({});

  useEffect(() => {
    let live = true;
    Promise.all([
      api.getAdminDeals({ status: "active", limit: 200 }),
      api.getAgentHandoffs({ fromAgentId: "executive-assistant", toAgentId: "admin", limit: 500 }),
    ])
      .then(([dealsResponse, handoffsResponse]) => {
        if (!live) return;
        const nextDeals: Record<string, ProfileAdminDealIds> = {};
        for (const deal of dealsResponse.items) {
          const sourceProfileId = deal.extraToggles?.sourceProfileId;
          if (typeof sourceProfileId === "string" && (deal.side === "listing" || deal.side === "buyer")) {
            nextDeals[sourceProfileId] = {
              ...nextDeals[sourceProfileId],
              [deal.side]: deal.id,
            };
          }
        }
        const nextHandoffs: Record<string, ProfileHandoffIds> = {};
        for (const handoff of handoffsResponse.items) {
          if (!handoff.profileId) continue;
          const side = profileHandoffSide(handoff);
          if (!side) continue;
          const existing = nextHandoffs[handoff.profileId]?.[side];
          if (existing && Date.parse(existing.updatedAt || "") >= Date.parse(handoff.updatedAt || "")) continue;
          nextHandoffs[handoff.profileId] = {
            ...nextHandoffs[handoff.profileId],
            [side]: handoff,
          };
        }
        setExistingDealIds(nextDeals);
        setProfileHandoffs(nextHandoffs);
      })
      .catch(() => {
        if (live) {
          setExistingDealIds({});
          setProfileHandoffs({});
        }
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

  const combinedDealIdsByProfile = useMemo(() => {
    const next: Record<string, ProfileAdminDealIds> = {};
    for (const [profileId, dealIds] of Object.entries(existingDealIds)) {
      next[profileId] = { ...dealIds };
    }
    return next;
  }, [existingDealIds]);

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
          combinedDealIdsByProfile[profile.id],
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
  }, [combinedDealIdsByProfile, profiles, threadsByProfileId]);

  const queueProfileSkillWorkflow = async (profile: SourceInboxProfile, side: AdminDealSide) => {
    if (pendingProfileAction) return;
    const sideCopy = PROFILE_ADMIN_SIDE_COPY[side];
    setPendingProfileAction({ profileId: profile.id, side });
    setErrors((prev) => {
      const next = { ...prev };
      delete next[profile.id];
      return next;
    });
    try {
      const verifiers = profileVerifiers(profile);
      if (!verifiers.length) {
        setErrors((prev) => ({
          ...prev,
          [profile.id]: "Add or sync a phone/email verifier before sending this profile to Admin.",
        }));
        return;
      }
      const setup = await api.getAdminSetup();
      if (!setup.complete) {
        setErrors((prev) => ({
          ...prev,
          [profile.id]: `Admin setup must be completed before ${sideCopy.errorLabel}. Missing: ${setup.missingRequiredKeys.join(", ")}`,
        }));
        return;
      }
      const priorHandoff = profileHandoffs[profile.id]?.[side];
      const activeHandoff = profileHandoffIsActive(priorHandoff);
      const handoff = await api.createAgentHandoff({
        fromAgentId: "executive-assistant",
        toAgentId: "admin",
        title: profileSkillWorkflowName(profile, side),
        task: profileSkillWorkflowPrompt(profile, side),
        priority: side === "listing" ? "high" : "normal",
        profileId: profile.id,
        contactId: profilePrimaryContactId(profile),
        conversationId: profile.conversationIds?.[0] ?? null,
        payload: {
          targetSide: side,
          workflow: sideCopy.workflow,
          workflowLabel: sideCopy.workflowLabel,
          skill: sideCopy.skill,
          profileContext: JSON.parse(profileSkillWorkflowContext(profile, side)),
          verifiers,
        },
        idempotencyKey: priorHandoff && !activeHandoff
          ? `profile-admin-handoff:${profile.id}:${sideCopy.workflow}:${Date.now()}`
          : `profile-admin-handoff:${profile.id}:${sideCopy.workflow}`,
        runNow: true,
      });
      setProfileHandoffs((prev) => ({
        ...prev,
        [profile.id]: {
          ...prev[profile.id],
          [side]: handoff,
        },
      }));
      await onChanged();
    } catch (error) {
      setErrors((prev) => ({
        ...prev,
        [profile.id]: error instanceof Error ? error.message : `Could not queue ${sideCopy.errorLabel}`,
      }));
    } finally {
      setPendingProfileAction(null);
    }
  };

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
      <div className="px-4 py-8 text-center">
        <h4 className="font-mono-ui text-[0.66rem] font-semibold uppercase tracking-[0.16em] text-muted-foreground/80">
          No profiles yet
        </h4>
        <p className="mt-2 text-sm leading-6 text-foreground/75">
          Synced contacts and conversations will appear here with buyer and seller admin handoff actions.
        </p>
      </div>
    );
  }

  return (
    <div className="divide-y divide-border">
      {showHeader && (
        <div className="flex flex-wrap items-center justify-between gap-3 px-4 py-3">
          <div>
            <div className="text-sm font-semibold text-foreground">Profiles</div>
            <p className="mt-0.5 text-xs leading-5 text-muted-foreground">
              People built from CRM, inbox, SMS, and social sources, with active conversations pinned first.
            </p>
          </div>
          <Badge variant="outline">{profiles.length} profiles</Badge>
        </div>
      )}

      {profileSections.map((section) => (
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

          {section.profiles.map((profile) => {
            const thread = threadByProfileId.get(profile.id);
            const activeConversation = profileHasActiveConversation(profile, threadsByProfileId.get(profile.id));
            const dealIds = combinedDealIdsByProfile[profile.id] ?? {};
            const sellerDealId = dealIds.listing;
            const buyerDealId = dealIds.buyer;
            const sellerPending =
              pendingProfileAction?.profileId === profile.id && pendingProfileAction.side === "listing";
            const buyerPending =
              pendingProfileAction?.profileId === profile.id && pendingProfileAction.side === "buyer";
            const sellerHandoff = profileHandoffs[profile.id]?.listing;
            const buyerHandoff = profileHandoffs[profile.id]?.buyer;
            const error = errors[profile.id];
            const canHandoff = profileHasVerifier(profile);
            const sellerHandoffLabel = profileHandoffBadgeLabel(sellerHandoff, "listing");
            const buyerHandoffLabel = profileHandoffBadgeLabel(buyerHandoff, "buyer");
            return (
              <div key={profile.id} className="px-4 py-3">
                <div className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-center">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <span
                        className={cn(
                          "h-2.5 w-2.5 rounded-full",
                          profile.heatLabel === "hot"
                            ? "bg-destructive"
                            : profile.heatLabel === "warm"
                              ? "bg-warning"
                              : profile.heatLabel === "watch"
                                ? "bg-success"
                                : "bg-muted-foreground/45",
                        )}
                      />
                      <div className="min-w-0 truncate text-sm font-semibold text-foreground">
                        {profile.displayName}
                      </div>
                      <Badge variant={heatVariant(profile)}>
                        {profile.heatLabel} {profile.heatScore}
                      </Badge>
                      {profile.hasCrm && <Badge variant="success">CRM</Badge>}
                      {profile.isPotentialLead && <Badge variant="warning">potential lead</Badge>}
                      {activeConversation && <Badge variant="success">active conversation</Badge>}
                      <Badge variant={profileHasVerifier(profile) ? "success" : "warning"}>
                        {profileVerifierSummary(profile)}
                      </Badge>
                      {sellerHandoffLabel && <Badge variant={sellerHandoff?.status === "failed" ? "destructive" : "warning"}>{sellerHandoffLabel}</Badge>}
                      {buyerHandoffLabel && <Badge variant={buyerHandoff?.status === "failed" ? "destructive" : "warning"}>{buyerHandoffLabel}</Badge>}
                      {sellerDealId && <Badge variant="success">{PROFILE_ADMIN_SIDE_COPY.listing.badgeLabel}</Badge>}
                      {buyerDealId && <Badge variant="success">{PROFILE_ADMIN_SIDE_COPY.buyer.badgeLabel}</Badge>}
                    </div>
                    <p className="mt-1 line-clamp-2 text-xs leading-5 text-muted-foreground">
                      {profile.latestText || "No recent source context yet."}
                    </p>
                    <div className="mt-2 flex flex-wrap items-center gap-1.5 text-[0.72rem] text-muted-foreground">
                      <Badge variant="outline">{profileSourceMeta(profile)}</Badge>
                      <Badge variant="outline">{profileContactLine(profile)}</Badge>
                      {profilePrimaryContactId(profile) && <Badge variant="outline">DB contact</Badge>}
                      <Badge variant="outline">{profile.threadCount} thread{profile.threadCount === 1 ? "" : "s"}</Badge>
                      <Badge variant="outline">{profileWhen(profile)}</Badge>
                      {profile.tags.slice(0, 3).map((tag) => (
                        <Badge key={tag} variant="outline">{tag}</Badge>
                      ))}
                    </div>
                    {error && (
                      <p className="mt-2 text-xs leading-5 text-destructive">
                        {error}
                      </p>
                    )}
                  </div>
                  <div className="flex flex-wrap items-center gap-2 lg:justify-end">
                    <Button
                      type="button"
                      size="sm"
                      variant="outline"
                      disabled={!thread}
                      onClick={() => openProfileThread(profile)}
                    >
                      <MessageSquare className="h-3.5 w-3.5" />
                      Open thread
                    </Button>
                    {sellerDealId ? (
                      <Link
                        to="/admin"
                        className={cn(buttonVariants({ variant: "outline", size: "sm" }), "h-9 px-3")}
                      >
                        <ExternalLink className="h-3.5 w-3.5" />
                        {PROFILE_ADMIN_SIDE_COPY.listing.openLabel}
                      </Link>
                    ) : (
	                      <Button
	                        type="button"
	                        size="sm"
	                        variant="outline"
	                        onClick={() => queueProfileSkillWorkflow(profile, "listing")}
	                        disabled={pendingProfileAction !== null || !canHandoff || profileHandoffIsActive(sellerHandoff)}
	                      >
	                        {sellerPending ? (
	                          <Loader2 className="h-3.5 w-3.5 animate-spin" />
	                        ) : profileHandoffIsActive(sellerHandoff) ? (
	                          <CheckCircle2 className="h-3.5 w-3.5" />
	                        ) : (
	                          <Home className="h-3.5 w-3.5" />
	                        )}
	                        {profileHandoffIsActive(sellerHandoff)
	                          ? PROFILE_ADMIN_SIDE_COPY.listing.queuedLabel
	                          : PROFILE_ADMIN_SIDE_COPY.listing.actionLabel}
                      </Button>
                    )}
                    {buyerDealId ? (
                      <Link
                        to="/admin"
                        className={cn(buttonVariants({ variant: "outline", size: "sm" }), "h-9 px-3")}
                      >
                        <ExternalLink className="h-3.5 w-3.5" />
                        {PROFILE_ADMIN_SIDE_COPY.buyer.openLabel}
                      </Link>
                    ) : (
                      <Button
                        type="button"
	                        size="sm"
	                        variant="outline"
	                        onClick={() => queueProfileSkillWorkflow(profile, "buyer")}
	                        disabled={pendingProfileAction !== null || !canHandoff || profileHandoffIsActive(buyerHandoff)}
	                      >
	                        {buyerPending ? (
	                          <Loader2 className="h-3.5 w-3.5 animate-spin" />
	                        ) : profileHandoffIsActive(buyerHandoff) ? (
	                          <CheckCircle2 className="h-3.5 w-3.5" />
	                        ) : (
	                          <Users className="h-3.5 w-3.5" />
	                        )}
	                        {profileHandoffIsActive(buyerHandoff)
	                          ? PROFILE_ADMIN_SIDE_COPY.buyer.queuedLabel
	                          : PROFILE_ADMIN_SIDE_COPY.buyer.actionLabel}
                      </Button>
                    )}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      ))}
    </div>
  );
}

function LeadProfilesListPage({
  onChanged,
  profiles,
  threads,
}: {
  onChanged: () => Promise<void>;
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
  showOpenThread = true,
  variant = "card",
}: {
  data: HubData;
  thread: SourceInboxThread;
  showOpenThread?: boolean;
  variant?: "card" | "list";
}) {
  const drawer = useThreadDrawer();
  const navigate = useNavigate();

  const mark = async (action: "done" | "archive") => {
    await api.updateSourceInboxThread(thread.sourceId, thread.threadId, action);
    await data.refresh();
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
    return (
      <div className="group flex items-start gap-3 px-3 py-3 transition-colors first:pt-3 last:pb-3 hover:bg-foreground/[0.02]">
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
        <div className="flex shrink-0 items-center gap-1">
          <Button
            size="sm"
            variant="ghost"
            className="h-11 w-11 p-0 text-foreground/60 hover:text-foreground sm:h-9 sm:w-9"
            onClick={() => void mark("archive")}
            aria-label={`Remove ${thread.personName} from list`}
            title="Remove"
          >
            <Trash2 className="h-3.5 w-3.5" />
          </Button>
          <Button
            size="sm"
            variant="ghost"
            className="h-11 w-11 p-0 text-foreground/60 hover:text-foreground sm:h-9 sm:w-9"
            onClick={() => void mark("done")}
            aria-label={`Mark ${thread.personName} done`}
            title="Mark done"
          >
            <CheckCircle2 className="h-3.5 w-3.5" />
          </Button>
          {showOpenThread && (
            <Button
              size="sm"
              className="h-11 px-3 sm:h-9"
              onClick={() => void openInChat()}
              aria-label={`Open thread with ${thread.personName}`}
            >
              <ExternalLink className="h-3.5 w-3.5" />
              Open
            </Button>
          )}
        </div>
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
  const selectedVisible = visibleDrafts.filter((d) => selectedIds.has(d.id));
  const allVisibleSelected = visibleDrafts.length > 0 && selectedVisible.length === visibleDrafts.length;

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
        await api.updateSourceInboxDraft(draft.sourceId, draft.taskId, action, text);
        if (!isDismiss) {
          setEditingId(null);
          setDraftEdits((current) => {
            const next = { ...current };
            delete next[draft.id];
            return next;
          });
        }
        void data.refresh();
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
      if (visibleDrafts.length > 0 && visibleDrafts.every((d) => current.has(d.id))) {
        const next = new Set(current);
        visibleDrafts.forEach((d) => next.delete(d.id));
        return next;
      }
      const next = new Set(current);
      visibleDrafts.forEach((d) => next.add(d.id));
      return next;
    });
  }, [visibleDrafts]);

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
                        {draft.generated && (
                          <>
                            <span aria-hidden className="opacity-50">·</span>
                            <span className="text-muted-foreground/70">suggested</span>
                          </>
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
          <div className="px-4 py-10 text-center">
            <h4 className="font-mono-ui text-[0.66rem] font-semibold uppercase tracking-[0.16em] text-muted-foreground/80">
              Inbox empty
            </h4>
            <p className="mt-2 text-sm leading-6 text-muted-foreground">{fallbackEmpty}</p>
          </div>
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


function HotLeadsList({
  data,
  threads,
}: {
  data: HubData;
  threads: SourceInboxThread[];
}) {
  const hot = leadThreadBuckets(threads).hot.slice(0, 8);
  if (!hot.length) {
    return (
      <p className="px-1 py-1 text-xs text-muted-foreground/80">
        No hot leads — recent replies and repeat opens land here.
      </p>
    );
  }
  return (
    <div className="divide-y divide-border">
      {hot.map((thread) => (
        <LeadBoardRow key={thread.id} data={data} thread={thread} showOpenThread variant="list" />
      ))}
    </div>
  );
}

function LeadQueuePanel({
  children,
  count,
  title,
}: {
  children: ReactNode;
  count: number;
  title: string;
}) {
  return (
    <div className="min-w-0">
      <div className="flex items-baseline gap-2 pb-1.5">
        <h3 className="text-sm font-medium text-foreground">{title}</h3>
        <span className="inline-flex items-baseline gap-1 font-mono-ui text-[0.7rem] text-muted-foreground/80">
          ·<span className="tabular-nums">{count}</span>
        </span>
      </div>
      <div>{children}</div>
    </div>
  );
}

function LeadPipelineBoard({
  buyers,
  data,
  skippedDrafts,
  threads,
}: {
  buyers: BuyerWatchlistEntry[];
  data: HubData;
  skippedDrafts: SourceInboxDraft[];
  threads: SourceInboxThread[];
}) {
  const buckets = leadThreadBuckets(threads);

  return (
    <div className="grid gap-x-6 gap-y-4 xl:grid-cols-2">
      <LeadQueuePanel title="Hot leads" count={buckets.hot.length}>
        <HotLeadsList data={data} threads={threads} />
      </LeadQueuePanel>

      <LeadQueuePanel title="Follow-ups" count={buckets.followUp.length}>
        <FollowUpThreadsList data={data} threads={threads} />
      </LeadQueuePanel>

      <LeadQueuePanel title="Buyer searches" count={buyers.length}>
        <PrivateSearchBuyersList buyers={buyers} />
      </LeadQueuePanel>

      <LeadQueuePanel title="Recently skipped" count={skippedDrafts.length}>
        <SkippedDraftsList data={data} drafts={skippedDrafts} />
      </LeadQueuePanel>
    </div>
  );
}

function FollowUpThreadsList({
  data,
  threads,
}: {
  data: HubData;
  threads: SourceInboxThread[];
}) {
  const followUps = leadThreadBuckets(threads).followUp.slice(0, 8);
  if (!followUps.length) {
    return (
      <p className="px-1 py-1 text-xs text-muted-foreground/80">
        Inbox zero — replies across email, SMS, Messenger, IG, WhatsApp will surface here.
      </p>
    );
  }
  return (
    <div className="divide-y divide-border">
      {followUps.map((thread) => (
        <LeadBoardRow key={thread.id} data={data} thread={thread} showOpenThread variant="list" />
      ))}
    </div>
  );
}

function PrivateSearchBuyersList({ buyers }: { buyers: BuyerWatchlistEntry[] }) {
  if (!buyers.length) {
    return (
      <p className="px-1 py-1 text-xs text-muted-foreground/80">
        No active buyer searches — run the MLS analyzer to score buyers on the board.
      </p>
    );
  }
  return (
    <div className="divide-y divide-border">
      {buyers.map((buyer) => (
        <BuyerWatchlistRow key={buyer.id} buyer={buyer} />
      ))}
    </div>
  );
}

function BuyerWatchlistRow({ buyer }: { buyer: BuyerWatchlistEntry }) {
  const score = typeof buyer.score === "number" ? buyer.score : null;
  const tier = (buyer.tier ?? "").toUpperCase();
  const days = typeof buyer.days === "number" ? buyer.days : null;
  const searches = (buyer.searches ?? []).filter(Boolean);
  const tone =
    tier === "HOT"
      ? "border-border bg-card text-destructive"
      : tier === "WARM"
        ? "border-border bg-card text-warning"
        : "border-border bg-card text-foreground/70";
  const dot =
    tier === "HOT"
      ? "bg-destructive"
      : tier === "WARM"
        ? "bg-warning"
        : "bg-foreground/40";

  return (
    <div className="group flex items-start gap-3 px-3 py-3 transition-colors first:pt-3 last:pb-3 hover:bg-foreground/[0.02]">
      <span aria-hidden="true" className={cn("mt-1 h-2.5 w-2.5 shrink-0 rounded-full", dot)} />
      <div className="min-w-0 flex-1">
        <div className="flex min-w-0 flex-wrap items-center gap-2">
          <div className="min-w-0 flex-1 truncate text-sm font-semibold text-foreground">
            {buyer.name || "Unnamed buyer"}
          </div>
          {score !== null && (
            <span
              className={cn(
                "font-mono-ui inline-flex items-center rounded-sm border px-2 py-0.5 text-[0.7rem] font-semibold",
                tone,
              )}
            >
              {score}
            </span>
          )}
        </div>
        {searches.length > 0 && (
          <p className="mt-1 line-clamp-2 text-xs leading-5 text-foreground/75">
            {searches.join(" · ")}
          </p>
        )}
        <div className="font-mono-ui mt-1.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-[0.7rem] text-muted-foreground">
          {tier && <span>{tier.toLowerCase()}</span>}
          {tier && (days != null || buyer.lastActivity) && <span aria-hidden>·</span>}
          {days != null ? (
            <span>{days === 0 ? "today" : `${days}d ago`}</span>
          ) : buyer.lastActivity ? (
            <span>{buyer.lastActivity}</span>
          ) : null}
          {buyer.email && (
            <>
              <span aria-hidden>·</span>
              <span className="inline-flex items-center gap-1">
                <Mail className="h-3 w-3" />
                <span className="truncate">{buyer.email}</span>
              </span>
            </>
          )}
          {buyer.phone && (
            <>
              <span aria-hidden>·</span>
              <span className="inline-flex items-center gap-1">
                <Phone className="h-3 w-3" />
                {buyer.phone}
              </span>
            </>
          )}
          {buyer.sourceLabel && (
            <>
              <span aria-hidden>·</span>
              <span>{buyer.sourceLabel}</span>
            </>
          )}
        </div>
      </div>
      {buyer.profileUrl && (
        <a
          href={buyer.profileUrl}
          target="_blank"
          rel="noopener noreferrer"
          aria-label={`Open MLS profile for ${buyer.name}`}
          className={cn(
            buttonVariants({ size: "sm", variant: "outline" }),
            "h-11 shrink-0 px-3 sm:h-9",
          )}
        >
          <ExternalLink className="h-3.5 w-3.5" />
          Profile
        </a>
      )}
    </div>
  );
}

function SkippedDraftsList({
  data,
  drafts: draftsOverride,
}: {
  data: HubData;
  drafts?: SourceInboxDraft[];
}) {
  const skipped = draftsOverride ?? data.sourceInbox?.skippedDrafts ?? [];
  const [restoredIds, setRestoredIds] = useState<Set<string>>(() => new Set());

  const visible = skipped.filter((d) => !restoredIds.has(d.id));

  useEffect(() => {
    setRestoredIds((current) => {
      if (current.size === 0) return current;
      const liveIds = new Set(skipped.map((d) => d.id));
      let changed = false;
      const next = new Set<string>();
      current.forEach((id) => {
        if (liveIds.has(id)) next.add(id);
        else changed = true;
      });
      return changed ? next : current;
    });
  }, [skipped]);

  const restore = useCallback(
    async (draft: SourceInboxDraft) => {
      setRestoredIds((current) => {
        const next = new Set(current);
        next.add(draft.id);
        return next;
      });
      try {
        await api.updateSourceInboxDraft(draft.sourceId, draft.taskId, "restore", draft.draftText);
        void data.refresh();
      } catch (error) {
        setRestoredIds((current) => {
          const next = new Set(current);
          next.delete(draft.id);
          return next;
        });
        window.alert(`Failed to restore: ${error instanceof Error ? error.message : String(error)}`);
      }
    },
    [data],
  );

  if (!visible.length) {
    return (
      <p className="px-1 py-1 text-xs text-muted-foreground/80">
        Nothing skipped — drafts auto-clear after 3 days.
      </p>
    );
  }

  return (
    <div className="divide-y divide-border">
      {visible.map((draft) => {
        const identity = parseIdentity(draft.personName);
        return (
        <div
          key={draft.id}
          className="group flex items-start gap-2 px-2.5 py-2.5 transition-colors hover:bg-card"
        >
          <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-sm bg-card text-muted-foreground">
            <XCircle className="h-3.5 w-3.5" />
          </span>
          <div className="min-w-0 flex-1">
            <div className="flex min-w-0 items-baseline gap-2">
              <div className="min-w-0 flex-1 truncate text-sm font-medium leading-5 text-foreground">
                {identity.name}
              </div>
              <span className="font-mono-ui shrink-0 text-[0.62rem] tabular-nums text-muted-foreground/80">
                {draft.skippedAt ? isoTimeAgo(draft.skippedAt) : "—"}
              </span>
            </div>
            {identity.email && (
              <div className="truncate font-mono-ui text-[0.62rem] text-muted-foreground/70">
                {identity.email}
              </div>
            )}
            <p className="mt-0.5 line-clamp-2 text-[0.78rem] leading-5 text-muted-foreground">
              {draft.draftText}
            </p>
          </div>
          <button
            type="button"
            onClick={() => void restore(draft)}
            title="Restore to queue"
            aria-label={`Restore draft for ${identity.name}`}
            className="font-mono-ui inline-flex h-11 shrink-0 items-center rounded-sm px-3 text-[0.7rem] font-semibold text-muted-foreground transition hover:bg-muted hover:text-primary sm:h-9"
          >
            Restore
          </button>
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
        <div className="flex flex-wrap items-center gap-1.5 px-1 py-1.5">
          <span className="font-mono-ui mr-1 inline-flex items-center gap-1 text-[0.66rem] uppercase tracking-[0.14em] text-muted-foreground">
            <Filter className="h-3 w-3" />
            Filter
          </span>
          <FilterChip
            active={active === null}
            label="All"
            onClick={() => onSelect(null)}
          />
          {options.map((option) => (
            <FilterChip
              key={option.id}
              active={active === option.id}
              label={option.label}
              meta={`${option.drafts ? `${option.drafts} drafts · ` : ""}${option.profiles ? `${option.profiles} profiles · ` : ""}${option.threads}`}
              onClick={() => onSelect(option.id)}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function FilterChip({
  active,
  label,
  meta,
  onClick,
}: {
  active: boolean;
  label: string;
  meta?: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={cn(
        "inline-flex h-11 items-center gap-1.5 rounded-sm border px-3 text-xs font-medium transition-colors sm:h-8",
        active
          ? "border-primary bg-muted text-foreground"
          : "border-border bg-card text-muted-foreground hover:bg-card hover:text-foreground",
      )}
    >
      <span>{label}</span>
      {meta && (
        <span
          className={cn(
            "font-mono-ui rounded-sm px-1.5 py-0.5 text-[0.62rem] tabular-nums",
            active ? "bg-muted text-foreground" : "bg-card text-muted-foreground",
          )}
        >
          {meta}
        </span>
      )}
    </button>
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
                  <h4 className="font-mono-ui flex items-center gap-2 text-[0.7rem] uppercase tracking-[0.12em] text-warning">
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
                <div className="rounded-md border border-dashed border-border bg-card px-4 py-6 text-center text-xs text-muted-foreground">
                  No templates yet. The agent on this lane will skip drafting until at least one exists.
                </div>
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

export function RealEstateLeadsPage() {
  const data = useRealEstateHubData();
  useHubHeader("Leads", data);
  const [sourceFilter, setSourceFilter] = useState<string | null>(null);
  const [tab, setTab] = useState<LeadTab>("action-board");

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
  const buyerSearches = data.sourceInbox?.privateSearchBuyers ?? [];

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

  const hotLeads = threads.filter((thread) => thread.heatLabel === "hot").length;
  const followUpThreadCount = leadThreadBuckets(threads).followUp.length;
  const blockedSources = allSources.filter((source) => source.blocked);
  const pulse = useMemo(() => computeResponsePulse(threads), [threads]);

  const refresh = data.refresh;
  const shellIcon = tab === "profiles" ? Users : tab === "templates" ? BookText : Radar;
  const shellTitle =
    tab === "profiles"
      ? "Lead profiles."
      : tab === "templates"
        ? "Lead templates."
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
        <div className="flex flex-wrap items-center justify-between gap-3">
          <LeadsTabBar active={tab} onChange={setTab} />
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
        </div>

        {tab === "templates" ? (
          <div id="leads-panel-templates" role="tabpanel" aria-labelledby="leads-tab-templates">
            <TemplatesPanel />
          </div>
        ) : (
          <>
            <LeadFilterBar
              active={sourceFilter}
              buyerSearches={buyerSearches.length}
              drafts={drafts.length}
              followUps={followUpThreadCount}
              hot={hotLeads}
              onSelect={setSourceFilter}
              options={filterOptions}
              pulse={pulse}
              profiles={profiles.length}
              skipped={skippedDrafts.length}
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
                onChanged={refresh}
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
      </div>
    </HubShell>
    </ThreadDrawerProvider>
  );
}

export { RealEstateAdminPage } from "@/pages/real-estate-hub/admin";

export { RealEstateMemoryPage } from "@/pages/real-estate-hub/memory";
export { RealEstateSocialMediaPage } from "@/pages/real-estate-hub/social";
export { RealEstateTasksPage } from "@/pages/real-estate-hub/tasks";
