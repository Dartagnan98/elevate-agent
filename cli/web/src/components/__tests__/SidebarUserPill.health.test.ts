import fs from "node:fs";
import { describe, expect, it } from "vitest";
import type { StatusResponse } from "@/lib/api-types";
import {
  BACKEND_UNREACHABLE,
  isBackendUnreachable,
} from "@/hooks/useSidebarStatus";

function source(relative: string): string {
  return fs.readFileSync(new URL(relative, import.meta.url), "utf8");
}

describe("useSidebarStatus unreachable sentinel", () => {
  it("recognises the sentinel by identity, not shape", () => {
    expect(isBackendUnreachable(BACKEND_UNREACHABLE)).toBe(true);
    // A structurally identical but distinct object is NOT the sentinel.
    const lookalike = { ...BACKEND_UNREACHABLE } as StatusResponse;
    expect(isBackendUnreachable(lookalike)).toBe(false);
  });

  it("does not treat null or a healthy response as unreachable", () => {
    expect(isBackendUnreachable(null)).toBe(false);
    expect(isBackendUnreachable({} as StatusResponse)).toBe(false);
    const healthy = {
      gateway_state: "running",
      gateway_running: true,
      database: { reachable: true, latency_ms: 3, error: null },
    } as StatusResponse;
    expect(isBackendUnreachable(healthy)).toBe(false);
  });

  it("marks the database unreachable and carries an error string", () => {
    expect(BACKEND_UNREACHABLE.database?.reachable).toBe(false);
    expect(BACKEND_UNREACHABLE.database?.error).toBeTruthy();
  });

  it("leaves version undefined so the footer shows no stale version", () => {
    // SidebarFooter reads `status?.version`; the sentinel must not present a
    // stale version when the backend is actually down.
    expect(BACKEND_UNREACHABLE.version).toBeUndefined();
  });
});

describe("SidebarUserPill health surface", () => {
  const pill = source("../SidebarUserPill.tsx");

  it("renders a Database status row alongside Gateway", () => {
    expect(pill).toContain('<span className="dim">Gateway</span>');
    expect(pill).toContain('<span className="dim">Database</span>');
    expect(pill).toContain("● reachable");
    expect(pill).toContain("● unreachable");
    expect(pill).toContain("var(--status-error)");
  });

  it("shows the collapsed-avatar dot when backend or database is down", () => {
    expect(pill).toContain("isBackendUnreachable(status)");
    expect(pill).toContain("backendUnreachable || dbReachable === false");
    expect(pill).toContain("showHealthBadge");
    // The dot lives on the always-visible avatar element.
    expect(pill).toMatch(/className="avatar"[\s\S]*showHealthBadge && \(/);
  });
});
