import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import {
  AlertTriangle,
  Clock,
} from "../../admin/icons";
import type {
  LeadsActivityEntry,
  LeadsAvailable,
  LeadsChannel,
  LeadsSchedule,
} from "../leads-data";

export type LeadsTab = "action" | "profiles" | "templates" | "sent";

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

export function SourcesHealthPill({
  channels, schedules, available,
}: {
  channels: LeadsChannel[];
  schedules: LeadsSchedule[];
  available: LeadsAvailable[];
}) {
  const [open, setOpen] = useState(false);
  const all = [...channels, ...schedules];
  const broken = all.filter(s => s.status === "error" || s.status === "blocked");
  const live = all.filter(s => s.status === "live");

  return (
    <div className="lb-health-wrap">
      <button type="button" className={"lb-health" + (broken.length > 0 ? " has-broken" : "")} onClick={() => setOpen(o => !o)}>
        {broken.length > 0 && <span className="lb-health-pulse"></span>}
        <span className="lb-health-text">
          <strong>{live.length}</strong> live
          {broken.length > 0 && <span className="lb-health-warn"> · {broken.length} need attention</span>}
        </span>
        <span className={"lb-health-chev" + (open ? " open" : "")}>▾</span>
      </button>

      {open && (
        <div className="lb-health-drawer">
          <SourcesDrawerSection title="Channels" items={channels} kind="channel" />
          <SourcesDrawerSection title="Schedules" items={schedules} kind="schedule" />
          <div className="lb-health-available">
            <div className="lb-health-available-label mono">Connect more</div>
            <div className="lb-health-available-chips">
              {available.map(a => (
                <Link key={a.id} to="/config#connectors" className="lb-avail-chip">
                  <span>+</span><span>{a.label}</span>
                </Link>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function SourcesDrawerSection({
  title, items, kind,
}: {
  title: string;
  items: Array<LeadsChannel | LeadsSchedule>;
  kind: "channel" | "schedule";
}) {
  return (
    <div className="lb-health-section" data-kind={kind}>
      <div className="lb-health-section-label mono">{title}</div>
      {items.map(it => {
        const isBroken = it.status === "error" || it.status === "blocked";
        const sched = (it as LeadsSchedule).schedule;
        return (
          <div key={it.id} className="lb-health-row" data-status={it.status}>
            {isBroken && <span className="lb-source-pulse" data-tone={it.status === "error" ? "error" : "warn"}></span>}
            {!isBroken && <span className="lb-health-ok-dot"></span>}
            <span className="lb-health-name">{it.name}</span>
            {sched && <span className="lb-health-sched mono">{sched}</span>}
            <span className={"lb-source-tag " + it.status}>
              {it.status === "live" ? "Live" : it.status === "error" ? "Error" : it.status === "blocked" ? "Blocked" : it.status}
            </span>
          </div>
        );
      })}
    </div>
  );
}

export function LeadsTabs({ tab, onChange }: { tab: LeadsTab; onChange: (t: LeadsTab) => void }) {
  const tabs: Array<{ id: LeadsTab; label: string }> = [
    { id: "action", label: "Action board" },
    { id: "profiles", label: "Profiles" },
    { id: "templates", label: "Templates" },
    { id: "sent", label: "Sent" },
  ];
  return (
    <div className="lb-tabs">
      {tabs.map(t => (
        <button
          key={t.id}
          type="button"
          className={"lb-tab" + (tab === t.id ? " active" : "")}
          onClick={() => onChange(t.id)}
        >
          {t.label}
        </button>
      ))}
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

// macOS deep-link straight to System Settings → Privacy & Security → Full Disk
// Access. Electron's setWindowOpenHandler shell.openExternal's any non-backend
// URL, so window.open(this) opens the real pane. The legacy
// `com.apple.preference.security?Privacy_AllFiles` anchor only worked on the old
// System Preferences (≤ Monterey); System Settings (Ventura+) uses the
// PrivacySecurity.extension pane id below, which actually scrolls to the section.
const FDA_SETTINGS_URL =
  "x-apple.systempreferences:com.apple.settings.PrivacySecurity.extension?Privacy_AllFiles";

export function LbSourceAlert({ blocked }: { blocked: LeadsChannel[] }) {
  if (blocked.length === 0) return null;
  const top = blocked[0];
  const isFda = top.kind === "imessage" || /full disk access/i.test(top.note || "");
  return (
    <div className="lb-alert">
      <span className="lb-alert-icon"><AlertTriangle /></span>
      <span className="lb-alert-label">
        {isFda ? "Apple Messages needs Full Disk Access." : "A lead source needs access."}
      </span>
      <span className="lb-alert-detail">
        {isFda
          ? "Open System Settings → Privacy & Security → Full Disk Access, turn ON Elevate (click + to add it if it's not listed), then quit and reopen Elevate."
          : <><strong>{top.name}:</strong> {top.note}</>}
      </span>
      {isFda ? (
        <button
          type="button"
          className="lb-alert-action"
          onClick={() => window.open(FDA_SETTINGS_URL, "_blank", "noopener,noreferrer")}
        >
          Open Full Disk Access
        </button>
      ) : (
        <Link to="/config#connectors" className="lb-alert-action">Open Settings</Link>
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
