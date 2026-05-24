// Shared UI primitives. Inline styles use design tokens from globals.css.
// Keep this file lean — only generic primitives, no business logic.
"use client";

import type React from "react";

// ============================================================================
// Button
// ============================================================================
type ButtonProps = {
  variant?: "primary" | "secondary" | "ghost" | "danger" | "dev";
  size?: "sm" | "md";
  loading?: boolean;
  children: React.ReactNode;
} & Omit<React.ButtonHTMLAttributes<HTMLButtonElement>, "size">;

export function Button({
  variant = "secondary",
  size = "md",
  loading,
  children,
  disabled,
  style,
  ...rest
}: ButtonProps) {
  const base: React.CSSProperties = {
    display: "inline-flex",
    alignItems: "center",
    justifyContent: "center",
    gap: 6,
    padding: size === "sm" ? "5px 10px" : "8px 14px",
    fontSize: size === "sm" ? 12 : 13,
    fontWeight: 500,
    borderRadius: "var(--r-md)",
    cursor: disabled || loading ? "not-allowed" : "pointer",
    border: "1px solid transparent",
    transition: "background 120ms, border-color 120ms, color 120ms",
    opacity: disabled || loading ? 0.55 : 1,
    whiteSpace: "nowrap",
    lineHeight: 1.2,
  };
  const variants: Record<NonNullable<ButtonProps["variant"]>, React.CSSProperties> = {
    primary: { background: "var(--accent)", color: "#fff", border: "1px solid var(--accent)" },
    secondary: { background: "var(--bg-elev-2)", color: "var(--text)", border: "1px solid var(--border)" },
    ghost: { background: "transparent", color: "var(--text-muted)", border: "1px solid var(--border)" },
    danger: { background: "var(--red-bg)", color: "var(--red)", border: "1px solid #5a2a2a" },
    dev: { background: "var(--amber-bg)", color: "var(--amber)", border: "1px solid #5a4a2a" },
  };
  return (
    <button
      {...rest}
      disabled={disabled || loading}
      style={{ ...base, ...variants[variant], ...style }}
    >
      {loading && <span className="spinner" />}
      {children}
    </button>
  );
}

// ============================================================================
// Input
// ============================================================================
export const inputStyle: React.CSSProperties = {
  padding: "8px 12px",
  background: "var(--bg-input-solid)",
  border: "1px solid var(--border)",
  borderRadius: "var(--r-md)",
  color: "var(--text)",
  fontSize: 13,
  outline: "none",
  width: "100%",
};

export function Input(props: React.InputHTMLAttributes<HTMLInputElement>) {
  return <input {...props} style={{ ...inputStyle, ...props.style }} />;
}

export function Select(props: React.SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select
      {...props}
      style={{
        ...inputStyle,
        appearance: "none",
        backgroundImage:
          "url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='10' height='6' viewBox='0 0 10 6'%3E%3Cpath fill='%23aaa' d='M0 0l5 6 5-6z'/%3E%3C/svg%3E\")",
        backgroundRepeat: "no-repeat",
        backgroundPosition: "right 10px center",
        paddingRight: 28,
        ...props.style,
      }}
    />
  );
}

// ============================================================================
// Card / Section
// ============================================================================
export function Card({
  children,
  style,
  padded = true,
}: {
  children: React.ReactNode;
  style?: React.CSSProperties;
  padded?: boolean;
}) {
  return (
    <div
      style={{
        background: "var(--bg-elev)",
        border: "1px solid var(--border)",
        borderRadius: "var(--r-lg)",
        padding: padded ? 20 : 0,
        ...style,
      }}
    >
      {children}
    </div>
  );
}

// ============================================================================
// Page header (title + subtitle + actions)
// ============================================================================
export function PageHeader({
  title,
  subtitle,
  actions,
}: {
  title: React.ReactNode;
  subtitle?: React.ReactNode;
  actions?: React.ReactNode;
}) {
  return (
    <div
      style={{
        display: "flex",
        alignItems: "flex-start",
        justifyContent: "space-between",
        gap: 16,
        marginBottom: 24,
        paddingBottom: 16,
        borderBottom: "1px solid var(--border)",
      }}
    >
      <div>
        <h1 style={{ margin: 0, fontSize: 22, fontWeight: 600, letterSpacing: "-0.01em" }}>
          {title}
        </h1>
        {subtitle && (
          <div style={{ marginTop: 4, color: "var(--text-dim)", fontSize: 13 }}>{subtitle}</div>
        )}
      </div>
      {actions && <div style={{ display: "flex", gap: 8, alignItems: "center" }}>{actions}</div>}
    </div>
  );
}

// ============================================================================
// Badge
// ============================================================================
type BadgeTone = "neutral" | "sage" | "amber" | "red" | "accent" | "dev";
export function Badge({
  tone = "neutral",
  children,
  size = "md",
}: {
  tone?: BadgeTone;
  children: React.ReactNode;
  size?: "sm" | "md";
}) {
  const tones: Record<BadgeTone, React.CSSProperties> = {
    neutral: { background: "var(--bg-input-solid)", color: "var(--text-muted)", borderColor: "var(--border)" },
    sage: { background: "var(--sage-bg)", color: "var(--sage)", borderColor: "#3a5a44" },
    amber: { background: "var(--amber-bg)", color: "var(--amber)", borderColor: "#5a4a2a" },
    red: { background: "var(--red-bg)", color: "var(--red)", borderColor: "#5a2a2a" },
    accent: { background: "var(--accent-bg)", color: "var(--accent)", borderColor: "#5a2e1e" },
    dev: { background: "var(--amber-bg)", color: "var(--amber)", borderColor: "#5a4a2a" },
  };
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        padding: size === "sm" ? "1px 6px" : "2px 8px",
        borderRadius: 999,
        border: "1px solid",
        fontSize: size === "sm" ? 10 : 11,
        fontFamily: "var(--font-mono)",
        textTransform: "uppercase",
        letterSpacing: "0.06em",
        lineHeight: 1.4,
        whiteSpace: "nowrap",
        ...tones[tone],
      }}
    >
      {children}
    </span>
  );
}

// ============================================================================
// Status dot
// ============================================================================
export function StatusDot({ status }: { status: string }) {
  const tone = ["active", "trialing"].includes(status)
    ? "sage"
    : ["past_due"].includes(status)
      ? "amber"
      : ["canceled", "inactive"].includes(status)
        ? "red"
        : "dim";
  const colors: Record<string, string> = {
    sage: "var(--sage)",
    amber: "var(--amber)",
    red: "var(--red)",
    dim: "var(--text-faint)",
  };
  return (
    <span
      style={{
        display: "inline-block",
        width: 6,
        height: 6,
        borderRadius: "50%",
        background: colors[tone],
        boxShadow: tone === "sage" || tone === "amber" ? `0 0 6px ${colors[tone]}` : "none",
        marginRight: 6,
        verticalAlign: "middle",
      }}
    />
  );
}

// ============================================================================
// Avatar (initials)
// ============================================================================
export function Avatar({ email, size = 32 }: { email: string; size?: number }) {
  const initials = email.slice(0, 2).toUpperCase();
  // Stable color hash from email
  let h = 0;
  for (let i = 0; i < email.length; i++) h = (h * 31 + email.charCodeAt(i)) >>> 0;
  const hues = [12, 28, 142, 35, 200, 270, 320, 95];
  const hue = hues[h % hues.length];
  return (
    <div
      style={{
        width: size,
        height: size,
        borderRadius: "50%",
        background: `hsl(${hue}, 25%, 22%)`,
        color: `hsl(${hue}, 60%, 75%)`,
        display: "grid",
        placeItems: "center",
        fontSize: size * 0.38,
        fontWeight: 600,
        fontFamily: "var(--font-mono)",
        flexShrink: 0,
        border: `1px solid hsl(${hue}, 25%, 30%)`,
      }}
    >
      {initials}
    </div>
  );
}

// ============================================================================
// Empty state
// ============================================================================
export function EmptyState({
  title,
  subtitle,
  action,
}: {
  title: React.ReactNode;
  subtitle?: React.ReactNode;
  action?: React.ReactNode;
}) {
  return (
    <div
      style={{
        padding: "48px 24px",
        textAlign: "center",
        border: "1px dashed var(--border)",
        borderRadius: "var(--r-lg)",
        background: "var(--bg-input-solid)",
      }}
    >
      <div style={{ fontSize: 14, fontWeight: 600, color: "var(--text)" }}>{title}</div>
      {subtitle && (
        <div style={{ marginTop: 6, fontSize: 13, color: "var(--text-dim)" }}>{subtitle}</div>
      )}
      {action && <div style={{ marginTop: 16 }}>{action}</div>}
    </div>
  );
}

// ============================================================================
// Error / loading inline
// ============================================================================
export function ErrorBanner({ children }: { children: React.ReactNode }) {
  if (!children) return null;
  return (
    <div
      style={{
        padding: "10px 14px",
        background: "var(--red-bg)",
        border: "1px solid #5a2a2a",
        borderLeft: "3px solid var(--red)",
        borderRadius: "var(--r-md)",
        color: "var(--red)",
        fontSize: 13,
        marginBottom: 16,
      }}
    >
      {children}
    </div>
  );
}

export function LoadingRow() {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8, color: "var(--text-dim)", fontSize: 13 }}>
      <span className="spinner" />
      loading
    </div>
  );
}

// ============================================================================
// Label (form label, all-caps mono)
// ============================================================================
export function Label({ children }: { children: React.ReactNode }) {
  return (
    <div
      style={{
        fontFamily: "var(--font-mono)",
        fontSize: 10,
        textTransform: "uppercase",
        letterSpacing: "0.08em",
        color: "var(--text-dim)",
        marginBottom: 6,
        fontWeight: 500,
      }}
    >
      {children}
    </div>
  );
}
