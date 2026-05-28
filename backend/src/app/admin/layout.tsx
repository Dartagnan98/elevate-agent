"use client";

import { useState } from "react";
import { usePathname } from "next/navigation";
import "./admin.css";
import Sidebar from "./components/sidebar";
import AdminBoard from "./components/admin-board";

export default function AdminLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const isLogin = pathname?.startsWith("/admin/login");

  const [activeNav, setActiveNav] = useState("admin");
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);

  if (isLogin) return <>{children}</>;

  const rootAttrs = {
    "data-accent": "graphite" as const,
    "data-density": "compact" as const,
    "data-dots": "smart" as const,
    "data-active-row": "fill" as const,
    "data-sections": "micro" as const,
    "data-artifacts": "hidden" as const,
  };

  return (
    <div className="app" {...rootAttrs}>
      <Sidebar
        activeNav={activeNav}
        onNavSelect={(id) => setActiveNav(id === activeNav ? id : id)}
        activeSessionId={activeSessionId}
        onSessionSelect={setActiveSessionId}
      />
      <AdminBoard />
    </div>
  );
}
