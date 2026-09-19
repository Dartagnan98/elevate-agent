import { useEffect, useRef } from "react";

const AGENT_TURN_REFRESH_COALESCE_MS = 300;

/**
 * Re-run a fetch/refresh the instant the agent finishes a turn.
 *
 * ChatPage broadcasts `elevate:agent-turn-complete` on every `message.complete`.
 * Any data view (board, leads, templates, automations, memory, ...) calls this
 * hook with its own refresh function so a change the agent just made shows up
 * immediately — no per-page poll wait, no app restart. The listener only lives
 * while the page is mounted, so off-screen views don't fetch.
 *
 *   useRefreshOnAgentTurn(refresh);
 *
 * `enabled` lets a page opt out while busy (e.g. mid-edit) without unmounting.
 */
export function useRefreshOnAgentTurn(
  refresh: () => void | Promise<void>,
  enabled = true,
): void {
  // Keep the latest callback without resubscribing every render.
  const refreshRef = useRef(refresh);
  refreshRef.current = refresh;

  useEffect(() => {
    if (!enabled || typeof window === "undefined") return;
    // Coalesce bursts: a turn with subagents or tool follow-ups can emit
    // several `message.complete` events within a few hundred ms, and every
    // subscriber (the hub alone fans out to 7 endpoints) would refetch for
    // each one. One trailing refresh per burst is still "instant" to a human.
    let timer: number | null = null;
    const handler = () => {
      if (timer !== null) window.clearTimeout(timer);
      timer = window.setTimeout(() => {
        timer = null;
        void refreshRef.current();
      }, AGENT_TURN_REFRESH_COALESCE_MS);
    };
    window.addEventListener("elevate:agent-turn-complete", handler);
    return () => {
      if (timer !== null) window.clearTimeout(timer);
      window.removeEventListener("elevate:agent-turn-complete", handler);
    };
  }, [enabled]);
}
