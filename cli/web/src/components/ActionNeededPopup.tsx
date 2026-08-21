import { useCallback, useEffect, useRef, useState } from "react";
import { fetchJSON, api } from "@/lib/api";
import WaitingCard, {
  type WaitingRunLike,
} from "@/pages/real-estate-hub/admin/components/waiting-card";
import "./action-needed-popup.css";

type QItem = {
  runId: string;
  dealId: string;
  address: string;
  side: string;
  title: string;
  message: string;
  hasPreview: boolean;
  outbound: boolean;
  createdAt: string;
  requiredFields?: unknown[];
  skill?: string;
  humanPrompt?: Record<string, unknown>;
};
type QResp = { ok: boolean; documents: QItem[]; gates: QItem[]; count: number };

/** One deduped card: the shown run plus every other waiting run that is the SAME
 *  ask (same deal + same title). Acting on the card clears the whole group so a
 *  hidden sibling can never resurface and re-pop the popup. */
type Group = { primary: QItem; siblings: string[] };

const POLL_MS = 20_000;

/** Global "ACTION NEEDED" popup. Polls the same /api/admin/approvals-queue that
 *  aggregates every waiting_human run across all deals, and floats an
 *  interactive slide-in card top-right ON ANY SCREEN so Skyleigh can preview,
 *  fill in, and approve without hunting for the deal card. Auto-pops open when a
 *  new item appears; she can minimize it to a badge (it re-pops for anything
 *  new). Non-blocking — the rest of the screen stays usable. */
export default function ActionNeededPopup() {
  const [groups, setGroups] = useState<Group[]>([]);
  const [minimized, setMinimized] = useState(false);
  const seen = useRef<Set<string>>(new Set());

  const load = useCallback(() => {
    fetchJSON<QResp>("/api/admin/approvals-queue")
      .then((r) => {
        const raw = [...(r.documents ?? []), ...(r.gates ?? [])];
        // Collapse duplicate waiting runs (same deal + same ask) into ONE card,
        // but keep every sibling runId so dismissing/acting clears the whole
        // group. Rows arrive newest-first, so the first per key is the primary.
        const byKey = new Map<string, Group>();
        for (const x of raw) {
          const key = `${x.dealId}::${x.title}`;
          const g = byKey.get(key);
          if (!g) byKey.set(key, { primary: x, siblings: [] });
          else g.siblings.push(x.runId);
        }
        const all = [...byKey.values()];
        // Pop open whenever a primary runId we've never shown appears.
        const fresh = all.some((g) => !seen.current.has(g.primary.runId));
        for (const g of all) seen.current.add(g.primary.runId);
        setGroups(all);
        if (fresh && all.length) setMinimized(false);
      })
      .catch(() => {
        /* endpoint absent / transient — keep last state, try again next tick */
      });
  }, []);

  // When a card resolves, cancel its same-title dupe siblings too, so a hidden
  // duplicate can't take its place on the next poll (the "dismiss doesn't stick"
  // bug). Then refresh.
  const resolveGroup = useCallback(
    async (siblings: string[]) => {
      for (const runId of siblings) {
        try {
          await api.approveAdminActionRun(runId, { approved: false, runNow: false });
        } catch {
          /* already resolved / gone — ignore */
        }
      }
      load();
    },
    [load],
  );

  useEffect(() => {
    load();
    const t = setInterval(load, POLL_MS);
    // Refresh immediately after any card resolves (here or in a deal scorecard).
    const onResolved = () => load();
    window.addEventListener("elevate:action-resolved", onResolved);
    // Refresh when the app regains focus so it never sits on stale data.
    const onFocus = () => load();
    window.addEventListener("focus", onFocus);
    return () => {
      clearInterval(t);
      window.removeEventListener("elevate:action-resolved", onResolved);
      window.removeEventListener("focus", onFocus);
    };
  }, [load]);

  if (!groups.length) return null;

  if (minimized) {
    return (
      <button
        type="button"
        className="anp-badge"
        onClick={() => setMinimized(false)}
        title={`${groups.length} thing${groups.length > 1 ? "s" : ""} need your input`}
      >
        <span className="anp-badge-dot" />
        {groups.length} action{groups.length > 1 ? "s" : ""} needed
      </button>
    );
  }

  return (
    <div className="anp-stack" role="region" aria-label="Actions needed">
      <div className="anp-head">
        <span className="anp-head-dot" />
        <span className="anp-head-title">
          ACTION NEEDED {groups.length > 1 ? `· ${groups.length}` : ""}
        </span>
        <button
          type="button"
          className="anp-min"
          onClick={() => setMinimized(true)}
          aria-label="Minimize"
          title="Minimize"
        >
          –
        </button>
      </div>
      <div className="anp-scroll">
        {groups.map((g) => {
          const it = g.primary;
          const run: WaitingRunLike = {
            runId: it.runId,
            dealId: it.dealId,
            skill: it.skill,
            registryName: it.title,
            humanPrompt:
              it.humanPrompt ??
              ({
                title: it.title,
                message: it.message,
                requiredFields: it.requiredFields ?? [],
                ...(it.hasPreview ? { previewPdf: "x" } : {}),
              } as Record<string, unknown>),
          };
          return (
            <div className="anp-item" key={it.runId}>
              <div className="anp-item-addr mono">{it.address}</div>
              <WaitingCard run={run} compact onResolved={() => resolveGroup(g.siblings)} />
            </div>
          );
        })}
      </div>
    </div>
  );
}
