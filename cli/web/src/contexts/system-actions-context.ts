import { createContext } from "react";
import type { ActionStatusResponse, UpdateStatusResponse } from "@/lib/api";

export const SystemActionsContext = createContext<SystemActionsState | null>(
  null,
);

export type SystemAction = "restart" | "update";

export interface SystemActionsState {
  actionStatus: ActionStatusResponse | null;
  activeAction: SystemAction | null;
  dismissLog: () => void;
  isBusy: boolean;
  isRunning: boolean;
  pendingAction: SystemAction | null;
  refreshUpdateStatus: (refresh?: boolean) => Promise<void>;
  runAction: (action: SystemAction) => Promise<void>;
  updateStatus: UpdateStatusResponse | null;
}
