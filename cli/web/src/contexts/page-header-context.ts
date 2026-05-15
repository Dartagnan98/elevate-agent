import { createContext } from "react";
import type { ReactNode } from "react";

export interface PageHeaderContextValue {
  setAfterTitle: (node: ReactNode) => void;
  setBeforeTitle: (node: ReactNode) => void;
  setEnd: (node: ReactNode) => void;
  setTitle: (title: ReactNode | string | null) => void;
  sidebarCollapsed: boolean;
  onShowSidebar?: () => void;
}

export const PageHeaderContext = createContext<PageHeaderContextValue | null>(
  null,
);
