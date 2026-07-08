import { Component, type ErrorInfo, type ReactNode } from "react";

interface Props {
  children: ReactNode;
  /** Custom fallback; receives the error and a reset() that clears the boundary. */
  fallback?: (error: Error, reset: () => void) => ReactNode;
  /** Label for the console log, e.g. "root" or "chat route". */
  label?: string;
}

interface State {
  error: Error | null;
}

/**
 * Catches render/lifecycle errors in its subtree so an exception shows a
 * recoverable panel instead of unmounting React to a blank white screen.
 * (A4) React error boundaries do NOT catch async/event errors — see
 * GlobalErrorToasts for those. Remote reporting is B4.
 */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    const tag = this.props.label ? ` ${this.props.label}` : "";
    console.error(`[ErrorBoundary${tag}]`, error, info.componentStack);
  }

  private reset = (): void => this.setState({ error: null });

  render(): ReactNode {
    const { error } = this.state;
    if (!error) return this.props.children;
    if (this.props.fallback) return this.props.fallback(error, this.reset);
    return <DefaultFallback error={error} />;
  }
}

function DefaultFallback({ error }: { error: Error }): ReactNode {
  // Inline styles + CSS-var fallbacks so the panel renders even if the theme
  // or stylesheet is what failed. Reload is the reliable recovery for a
  // corrupted render tree.
  return (
    <div
      role="alert"
      style={{
        minHeight: "100dvh",
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        gap: "14px",
        padding: "32px",
        textAlign: "center",
        color: "var(--fg, #14181f)",
        background: "var(--bg, #f4f6f8)",
        fontFamily:
          'system-ui, -apple-system, "Segoe UI", Roboto, sans-serif',
      }}
    >
      <div style={{ fontSize: "17px", fontWeight: 650 }}>Something went wrong</div>
      <p
        style={{
          margin: 0,
          maxWidth: "42ch",
          fontSize: "14px",
          opacity: 0.75,
          overflowWrap: "anywhere",
        }}
      >
        {error.message || "The app hit an unexpected error."}
      </p>
      <button
        type="button"
        onClick={() => window.location.reload()}
        style={{
          padding: "8px 18px",
          borderRadius: "8px",
          border: "1px solid var(--border, #c2ccd6)",
          background: "var(--accent, #0c7a82)",
          color: "#fff",
          fontSize: "14px",
          cursor: "pointer",
        }}
      >
        Reload
      </button>
    </div>
  );
}
