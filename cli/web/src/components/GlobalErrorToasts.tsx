import { useEffect, useState } from "react";

interface Toast {
  id: number;
  message: string;
}

/**
 * Surfaces uncaught async errors (window "error") and unhandled promise
 * rejections as a small dismissible toast. React error boundaries only catch
 * render/lifecycle errors, so without this a failed fetch or a rejected
 * promise fails silently — the realtor sees a stuck UI with no explanation.
 * (A4) There is no global toast bus in the app (useToast is per-component),
 * so this is intentionally self-contained.
 */
export function GlobalErrorToasts(): React.ReactElement | null {
  const [toasts, setToasts] = useState<Toast[]>([]);

  useEffect(() => {
    let seq = 0;
    const push = (message: string): void => {
      const id = ++seq;
      setToasts((prev) => [...prev.slice(-2), { id, message }]);
      window.setTimeout(
        () => setToasts((prev) => prev.filter((t) => t.id !== id)),
        8000,
      );
    };
    const onError = (event: ErrorEvent): void => {
      if (event.message) push(event.message);
    };
    const onRejection = (event: PromiseRejectionEvent): void => {
      const reason = event.reason;
      const message =
        typeof reason === "string"
          ? reason
          : reason?.message || "Unhandled error";
      push(message);
    };
    window.addEventListener("error", onError);
    window.addEventListener("unhandledrejection", onRejection);
    return () => {
      window.removeEventListener("error", onError);
      window.removeEventListener("unhandledrejection", onRejection);
    };
  }, []);

  if (!toasts.length) return null;

  return (
    <div
      style={{
        position: "fixed",
        bottom: "16px",
        right: "16px",
        zIndex: 2147483647,
        display: "flex",
        flexDirection: "column",
        gap: "8px",
        maxWidth: "min(92vw, 380px)",
      }}
    >
      {toasts.map((toast) => (
        <div
          key={toast.id}
          role="alert"
          onClick={() => setToasts((prev) => prev.filter((t) => t.id !== toast.id))}
          style={{
            padding: "10px 14px",
            borderRadius: "8px",
            border: "1px solid var(--chat-danger, #cf3b57)",
            background: "var(--surface, #fff)",
            color: "var(--fg, #14181f)",
            fontSize: "13px",
            fontFamily:
              'system-ui, -apple-system, "Segoe UI", Roboto, sans-serif',
            boxShadow: "0 6px 24px rgba(0,0,0,0.18)",
            cursor: "pointer",
            overflowWrap: "anywhere",
          }}
          title="Click to dismiss"
        >
          {toast.message}
        </div>
      ))}
    </div>
  );
}
