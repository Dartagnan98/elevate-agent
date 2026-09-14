import { useState } from "react";
import { Link } from "react-router-dom";

import { AlertTriangle } from "../../admin/icons";
import type {
  LeadsAvailable,
  LeadsChannel,
  LeadsSchedule,
} from "../leads-data";

export function SourcesHealthPill({
  channels,
  schedules,
  available,
}: {
  channels: LeadsChannel[];
  schedules: LeadsSchedule[];
  available: LeadsAvailable[];
}) {
  const [open, setOpen] = useState(false);
  const all = [...channels, ...schedules];
  const broken = all.filter((s) => s.status === "error" || s.status === "blocked");
  const live = all.filter((s) => s.status === "live");

  return (
    <div className="lb-health-wrap">
      <button
        type="button"
        className={"lb-health" + (broken.length > 0 ? " has-broken" : "")}
        onClick={() => setOpen((o) => !o)}
      >
        {broken.length > 0 && <span className="lb-health-pulse"></span>}
        <span className="lb-health-text">
          <strong>{live.length}</strong> live
          {broken.length > 0 && (
            <span className="lb-health-warn"> · {broken.length} need attention</span>
          )}
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
              {available.map((a) => (
                <Link key={a.id} to="/config#connectors" className="lb-avail-chip">
                  <span>+</span>
                  <span>{a.label}</span>
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
  title,
  items,
  kind,
}: {
  title: string;
  items: Array<LeadsChannel | LeadsSchedule>;
  kind: "channel" | "schedule";
}) {
  return (
    <div className="lb-health-section" data-kind={kind}>
      <div className="lb-health-section-label mono">{title}</div>
      {items.map((it) => {
        const isBroken = it.status === "error" || it.status === "blocked";
        const sched = (it as LeadsSchedule).schedule;
        return (
          <div key={it.id} className="lb-health-row" data-status={it.status}>
            {isBroken && (
              <span
                className="lb-source-pulse"
                data-tone={it.status === "error" ? "error" : "warn"}
              ></span>
            )}
            {!isBroken && <span className="lb-health-ok-dot"></span>}
            <span className="lb-health-name">{it.name}</span>
            {sched && <span className="lb-health-sched mono">{sched}</span>}
            <span className={"lb-source-tag " + it.status}>
              {it.status === "live"
                ? "Live"
                : it.status === "error"
                  ? "Error"
                  : it.status === "blocked"
                    ? "Blocked"
                    : it.status}
            </span>
          </div>
        );
      })}
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
      <span className="lb-alert-icon">
        <AlertTriangle />
      </span>
      <span className="lb-alert-label">
        {isFda ? "Apple Messages needs Full Disk Access." : "A lead source needs access."}
      </span>
      <span className="lb-alert-detail">
        {isFda ? (
          "Open System Settings → Privacy & Security → Full Disk Access, turn ON Elevate (click + to add it if it's not listed), then quit and reopen Elevate."
        ) : (
          <>
            <strong>{top.name}:</strong> {top.note}
          </>
        )}
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
        <Link to="/config#connectors" className="lb-alert-action">
          Open Settings
        </Link>
      )}
    </div>
  );
}
