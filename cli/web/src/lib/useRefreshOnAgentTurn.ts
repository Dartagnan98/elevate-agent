import { useEffect, useRef } from "react";

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
    const handler = () => {
      void refreshRef.current();
    };
    window.addEventListener("elevate:agent-turn-complete", handler);
    return () => {
      window.removeEventListener("elevate:agent-turn-complete", handler);
    };
  }, [enabled]);
}
