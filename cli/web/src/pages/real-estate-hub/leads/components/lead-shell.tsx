import { useEffect, useState } from "react";

import { Clock } from "../../admin/icons";
import type { LeadsActivityEntry } from "../leads-data";

export { LeadsTabs } from "./leads-tabs";
export type { LeadsTab } from "./leads-tabs";
export { LbSourceAlert, SourcesHealthPill } from "./source-health";

export function ActivityTicker({ activity }: { activity: LeadsActivityEntry[] }) {
  const [idx, setIdx] = useState(0);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    if (open) return;
    if (activity.length <= 1) return;
    const t = setInterval(() => {
      setIdx(i => (i + 1) % activity.length);
    }, 4200);
    return () => clearInterval(t);
  }, [activity.length, open]);

  if (activity.length === 0) return null;
  const a = activity[idx];

  return (
    <div className="lb-ticker-wrap">
      <button
        type="button"
        className="lb-ticker"
        onClick={() => setOpen(o => !o)}
        aria-expanded={open}
      >
        <Clock />
        <span className="lb-ticker-label mono">Last run</span>
        <span key={a.id} className="lb-ticker-item">
          <span className="lb-ticker-title">{a.title}</span>
          <span className="lb-ticker-dot">·</span>
          <span className="lb-ticker-age mono">{a.age}</span>
        </span>
        <span className={"lb-ticker-chev" + (open ? " open" : "")}>▾</span>
      </button>

      {open && (
        <div className="lb-ticker-drawer">
          <header className="lb-ticker-drawer-head">
            <span className="lb-ticker-drawer-title">Recent agent activity</span>
            <span className="lb-ticker-drawer-sub mono">{activity.length} runs</span>
          </header>
          <div className="lb-ticker-drawer-list">
            {activity.map(it => (
              <div key={it.id} className="lb-ticker-drawer-row">
                <span className="lb-ticker-drawer-dot"></span>
                <div className="lb-ticker-drawer-body">
                  <div className="lb-ticker-drawer-row-title">{it.title}</div>
                  <div className="lb-ticker-drawer-row-meta mono">{it.kind} · {it.age} · {it.messages} messages</div>
                </div>
                <span className="lb-ticker-drawer-tools mono">{it.tools} tools</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

interface LbKpiProps {
  label: string;
  value: string | number;
  breakdown?: string;
  delta?: string;
  deltaTone?: "up" | "down" | "warn" | "";
}

export function LbKpi({ label, value, breakdown, delta, deltaTone }: LbKpiProps) {
  return (
    <div className="ab-kpi">
      <div className="ab-kpi-label mono">{label}</div>
      <div className="ab-kpi-value">{value}</div>
      {breakdown && <div className="ab-kpi-breakdown">{breakdown}</div>}
      {delta && (
        <div className={"ab-kpi-delta" + (deltaTone ? " " + deltaTone : "")}>
          {delta}
        </div>
      )}
    </div>
  );
}

function LbToggle({
  on, label, hint, onClick, disabled = false,
}: { on: boolean; label: string; hint: string; onClick: () => void; disabled?: boolean }) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      title={hint}
      style={{
        display: "inline-flex", alignItems: "center", gap: 8,
        border: "1px solid var(--border, #2a2a2e)", borderRadius: 8,
        background: "transparent", color: "inherit", padding: "6px 10px",
        cursor: disabled ? "not-allowed" : "pointer", font: "inherit", opacity: disabled ? 0.65 : 1,
      }}
    >
      <span
        aria-hidden
        style={{
          width: 30, height: 18, borderRadius: 999, position: "relative",
          background: on ? "var(--accent-good, #4c9a6a)" : "var(--border, #3a3a3e)",
          transition: "background .15s",
        }}
      >
        <span style={{
          position: "absolute", top: 2, left: on ? 14 : 2, width: 14, height: 14,
          borderRadius: 999, background: "#fff", transition: "left .15s",
        }} />
      </span>
      <span style={{ display: "inline-flex", flexDirection: "column", lineHeight: 1.15, textAlign: "left" }}>
        <span style={{ fontWeight: 600, fontSize: 12 }}>{label}</span>
        <span style={{ opacity: 0.6, fontSize: 11 }}>{on ? "on" : "off"}</span>
      </span>
    </button>
  );
}

export function AppleMessagesToggleBar({
  appleMessages, onToggle,
}: {
  appleMessages?: { inbound: boolean; outbound: boolean; blocked?: boolean; note?: string };
  onToggle?: (dir: "inbound" | "outbound", value: boolean) => void | Promise<void>;
}) {
  const [busy, setBusy] = useState<"inbound" | "outbound" | null>(null);
  const [error, setError] = useState<string | null>(null);

  if (!appleMessages || !onToggle) return null;
  const runToggle = async (dir: "inbound" | "outbound", value: boolean) => {
    setBusy(dir);
    setError(null);
    try {
      await onToggle(dir, value);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not update Apple Messages.");
    } finally {
      setBusy(null);
    }
  };
  return (
    <div style={{
      display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap",
      padding: "8px 0", marginBottom: 4,
    }}>
      <span style={{ fontWeight: 600, fontSize: 12, opacity: 0.8 }}>Apple Messages</span>
      <LbToggle
        on={appleMessages.inbound}
        label="Inbound (read replies)"
        hint="Read your Mac Messages as a lead source. Needs Full Disk Access for Elevate."
        onClick={() => void runToggle("inbound", !appleMessages.inbound)}
        disabled={busy !== null}
      />
      <LbToggle
        on={appleMessages.outbound}
        label="Outbound (send texts)"
        hint="Send approved texts through Messages. No Full Disk Access required."
        onClick={() => void runToggle("outbound", !appleMessages.outbound)}
        disabled={busy !== null}
      />
      {error && <span style={{ color: "var(--accent-warn, #e0a44c)", fontSize: 12 }}>{error}</span>}
    </div>
  );
}
