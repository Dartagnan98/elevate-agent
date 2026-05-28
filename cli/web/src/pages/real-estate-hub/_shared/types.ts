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
  refreshing: boolean;
  refresh: (options?: { force?: boolean }) => Promise<void>;
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
