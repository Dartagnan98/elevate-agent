export const AGENT_ONBOARDING_ROUTED_KEY = "elevate:onboarding-routed";

type Navigate = (path: string, options?: { replace?: boolean }) => void;
type SessionStorage = { setItem: (key: string, value: string) => void };

export function exitAgentOnboardingToChat(
  navigate: Navigate,
  seed = Date.now(),
  storage?: SessionStorage | null,
): void {
  try {
    const target = storage === undefined && typeof window !== "undefined"
      ? window.sessionStorage
      : storage;
    target?.setItem(AGENT_ONBOARDING_ROUTED_KEY, "1");
  } catch {
    // Storage can be disabled. The exit must still take the user to Chat.
  }

  navigate(`/chat?new=${seed}&seed=${seed}`, { replace: true });
}
