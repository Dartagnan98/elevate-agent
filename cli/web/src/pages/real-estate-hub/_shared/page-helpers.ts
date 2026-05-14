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
