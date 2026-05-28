# Elevate: Shared Components
Backdrop, aurora, toast, login, sidebar pieces, markdown, dialogs.

---
## `src/components/AutoField.tsx`
```tsx
import { useEffect, useMemo, useState } from "react";
import { Input } from "@/components/ui/input";
import { Select, SelectOption } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";

function FieldLabel({
  label,
  schema,
}: {
  label: string;
  schema: Record<string, unknown>;
}) {
  const description = schema.description ? String(schema.description) : "";
  return (
    <div className="min-w-0 flex-1 pr-6">
      <div className="text-[0.92rem] font-medium text-foreground leading-tight">
        {label}
      </div>
      {description && (
        <div className="mt-1 text-[0.8rem] leading-snug text-foreground/80">
          {description}
        </div>
      )}
    </div>
  );
}

export function AutoField({
  schemaKey,
  schema,
  value,
  onChange,
}: AutoFieldProps) {
  const rawLabel = schemaKey.split(".").pop() ?? schemaKey;
  const label = rawLabel.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
  const jsonValue = useMemo(() => {
    if (schema.type !== "json") return "";
    return JSON.stringify(value ?? null, null, 2);
  }, [schema.type, value]);
  const [jsonText, setJsonText] = useState(jsonValue);
  const [jsonError, setJsonError] = useState("");

  useEffect(() => {
    setJsonText(jsonValue);
    setJsonError("");
  }, [jsonValue]);

  if (schema.type === "boolean") {
    return (
      <div className="flex items-start justify-between gap-4">
        <FieldLabel label={label} schema={schema} />
        <div className="shrink-0 pt-0.5">
          <Switch checked={!!value} onCheckedChange={onChange} />
        </div>
      </div>
    );
  }

  if (schema.type === "select") {
    const options = (schema.options as string[]) ?? [];
    return (
      <div className="flex items-start justify-between gap-4">
        <FieldLabel label={label} schema={schema} />
        <div className="w-72 shrink-0">
          <Select value={String(value ?? "")} onValueChange={(v) => onChange(v)}>
            {options.map((opt) => (
              <SelectOption key={opt} value={opt}>
                {opt || "(none)"}
              </SelectOption>
            ))}
          </Select>
        </div>
      </div>
    );
  }

  if (schema.type === "number") {
    return (
      <div className="flex items-start justify-between gap-4">
        <FieldLabel label={label} schema={schema} />
        <div className="w-40 shrink-0">
          <Input
            type="number"
            value={value === undefined || value === null ? "" : String(value)}
            onChange={(e) => {
              const raw = e.target.value;
              if (raw === "") {
                onChange(0);
                return;
              }
              const n = Number(raw);
              if (!Number.isNaN(n)) {
                onChange(n);
              }
            }}
          />
        </div>
      </div>
    );
  }

  if (schema.type === "text") {
    return (
      <div className="flex flex-col gap-2">
        <FieldLabel label={label} schema={schema} />
        <textarea
          className="flex min-h-[80px] w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm shadow-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
          value={String(value ?? "")}
          onChange={(e) => onChange(e.target.value)}
        />
      </div>
    );
  }

  if (schema.type === "list") {
    return (
      <div className="flex items-start justify-between gap-4">
        <FieldLabel label={label} schema={schema} />
        <div className="w-80 shrink-0">
          <Input
            value={Array.isArray(value) ? value.join(", ") : String(value ?? "")}
            onChange={(e) =>
              onChange(
                e.target.value
                  .split(",")
                  .map((s) => s.trim())
                  .filter(Boolean),
              )
            }
            placeholder="comma-separated values"
          />
        </div>
      </div>
    );
  }

  if (schema.type === "json") {
    return (
      <div className="flex flex-col gap-2">
        <FieldLabel label={label} schema={schema} />
        <textarea
          className="flex min-h-[200px] w-full rounded-md border border-input bg-transparent px-3 py-2 font-mono text-xs leading-relaxed shadow-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
          value={jsonText}
          onChange={(e) => {
            const next = e.target.value;
            setJsonText(next);
            try {
              onChange(JSON.parse(next));
              setJsonError("");
            } catch (err) {
              setJsonError(err instanceof Error ? err.message : "Invalid JSON");
            }
          }}
          spellCheck={false}
        />
        {jsonError && <div className="text-xs text-destructive">{jsonError}</div>}
      </div>
    );
  }

  if (typeof value === "object" && value !== null && !Array.isArray(value)) {
    const obj = value as Record<string, unknown>;
    return (
      <div className="flex items-start justify-between gap-4">
        <FieldLabel label={label} schema={schema} />
        <div className="w-80 shrink-0 space-y-2">
          {Object.entries(obj).map(([subKey, subVal]) => (
            <div key={subKey} className="flex items-center gap-2">
              <span className="w-24 shrink-0 text-xs text-muted-foreground">{subKey}</span>
              <Input
                value={String(subVal ?? "")}
                onChange={(e) => onChange({ ...obj, [subKey]: e.target.value })}
                aria-label={`${label} – ${subKey}`}
              />
            </div>
          ))}
        </div>
      </div>
    );
  }

  // Default: string input
  return (
    <div className="flex items-start justify-between gap-4">
      <FieldLabel label={label} schema={schema} />
      <div className="w-80 shrink-0">
        <Input value={String(value ?? "")} onChange={(e) => onChange(e.target.value)} />
      </div>
    </div>
  );
}

interface AutoFieldProps {
  schemaKey: string;
  schema: Record<string, unknown>;
  value: unknown;
  onChange: (v: unknown) => void;
}

```

---
## `src/components/Backdrop.tsx`
```tsx
/**
 * Elevate's local-first app backdrop.
 *
 * The previous blueprint/noise texture made the shell feel like a skin. The
 * new app chrome is intentionally quiet: a solid product canvas with a soft
 * vertical wash so dashboard pages and chat share the same visual language.
 */
export function Backdrop() {
  return (
    <>
      <div
        aria-hidden
        className="pointer-events-none fixed inset-0 z-[1]"
        style={{
          backgroundColor: "var(--background-base)",
        }}
      />

      <div
        aria-hidden
        className="pointer-events-none fixed inset-0 z-[2]"
        style={{
          background:
            "linear-gradient(180deg, color-mix(in srgb, var(--midground-base) 3%, transparent), transparent 28rem)",
          opacity: "var(--component-backdrop-filler-opacity, 1)",
        }}
      />

      <div
        aria-hidden
        className="pointer-events-none fixed inset-x-0 top-0 z-[3] h-px"
        style={{
          background:
            "linear-gradient(90deg, transparent, color-mix(in srgb, var(--midground-base) 22%, transparent), transparent)",
        }}
      />
    </>
  );
}

```

---
## `src/components/ChatSidebar.tsx`
```tsx
/**
 * ChatSidebar — structured-events panel that sits next to the xterm.js
 * terminal in the dashboard Chat tab.
 *
 * Two WebSockets, one per concern:
 *
 *   1. **JSON-RPC sidecar** (`GatewayClient` → /api/ws) — drives the
 *      sidebar's own slot of the dashboard's in-process gateway.  Owns
 *      the model badge / picker / connection state / error banner.
 *      Independent of the PTY pane's session by design — those are the
 *      pieces the sidebar needs to be able to drive directly (model
 *      switch via slash.exec, etc.).
 *
 *   2. **Event subscriber** (/api/events?channel=…) — passive, receives
 *      every dispatcher emit from the PTY-side `tui_gateway.entry` that
 *      the dashboard fanned out.  This is how `tool.start/progress/
 *      complete` from the agent loop reach the sidebar even though the
 *      PTY child runs three processes deep from us.  The `channel` id
 *      ties this listener to the same chat tab's PTY child — see
 *      `ChatPage.tsx` for where the id is generated.
 *
 * Best-effort throughout: WS failures show in the badge / banner, the
 * terminal pane keeps working unimpaired.
 */

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";

import { ModelPickerDialog } from "@/components/ModelPickerDialog";
import { ToolCall, type ToolEntry } from "@/components/ToolCall";
import { GatewayClient, type ConnectionState } from "@/lib/gatewayClient";

import { cn } from "@/lib/utils";
import { AlertCircle, ChevronDown, RefreshCw } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

interface SessionInfo {
  cwd?: string;
  model?: string;
  provider?: string;
  credential_warning?: string;
}

interface RpcEnvelope {
  method?: string;
  params?: { type?: string; payload?: unknown };
}

const TOOL_LIMIT = 20;

const STATE_LABEL: Record<ConnectionState, string> = {
  idle: "idle",
  connecting: "connecting",
  open: "live",
  closed: "closed",
  error: "error",
};

const STATE_TONE: Record<ConnectionState, string> = {
  idle: "bg-muted text-muted-foreground",
  connecting: "bg-muted text-primary",
  open: "bg-muted text-[var(--color-success)]",
  closed: "bg-muted text-muted-foreground",
  error: "bg-muted text-destructive",
};

interface ChatSidebarProps {
  channel: string;
  className?: string;
}

export function ChatSidebar({ channel, className }: ChatSidebarProps) {
  // `version` bumps on reconnect; gw is derived so we never call setState
  // for it inside an effect (React 19's set-state-in-effect rule). The
  // counter is the dependency on purpose — it's not read in the memo body,
  // it's the signal that says "rebuild the client".
  const [version, setVersion] = useState(0);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const gw = useMemo(() => new GatewayClient(), [version]);

  const [state, setState] = useState<ConnectionState>("idle");
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [info, setInfo] = useState<SessionInfo>({});
  const [tools, setTools] = useState<ToolEntry[]>([]);
  const [modelOpen, setModelOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const offState = gw.onState(setState);

    const offSessionInfo = gw.on<SessionInfo>("session.info", (ev) => {
      if (ev.session_id) {
        setSessionId(ev.session_id);
      }

      if (ev.payload) {
        setInfo((prev) => ({ ...prev, ...ev.payload }));
      }
    });

    const offError = gw.on<{ message?: string }>("error", (ev) => {
      const message = ev.payload?.message;

      if (message) {
        setError(message);
      }
    });

    // Adopt whichever session the gateway hands us. session.create on the
    // sidecar is independent of the PTY pane's session by design — we
    // only need a sid to drive the model picker's slash.exec calls.
    gw.connect()
      .then(() => {
        if (cancelled) {
          return;
        }
        return gw.request<{ session_id: string }>("session.create", {});
      })
      .then((created) => {
        if (cancelled || !created?.session_id) {
          return;
        }
        setSessionId(created.session_id);
      })
      .catch((e: Error) => {
        if (!cancelled) {
          setError(e.message);
        }
      });

    return () => {
      cancelled = true;
      offState();
      offSessionInfo();
      offError();
      gw.close();
    };
  }, [gw]);

  // Event subscriber WebSocket — receives the rebroadcast of every
  // dispatcher emit from the PTY child's gateway.  See /api/pub +
  // /api/events in elevate_cli/web_server.py for the broadcast hop.
  //
  // Failures (auth/loopback rejection, server too old to expose the
  // endpoint, transient drops) surface in the same banner as the
  // JSON-RPC sidecar so the sidebar matches its documented best-effort
  // UX and the user always has a reconnect affordance.
  useEffect(() => {
    const token = window.__ELEVATE_SESSION_TOKEN__;

    if (!token || !channel) {
      return;
    }

    const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
    const qs = new URLSearchParams({ token, channel });
    const ws = new WebSocket(
      `${proto}//${window.location.host}/api/events?${qs.toString()}`,
    );

    // `unmounting` suppresses the banner during cleanup — `ws.close()`
    // from the effect's return fires a close event with code 1005 that
    // would otherwise look like an unexpected drop.
    const DISCONNECTED = "events feed disconnected — tool calls may not appear";
    let unmounting = false;
    const surface = (msg: string) => !unmounting && setError(msg);

    ws.addEventListener("error", () => surface(DISCONNECTED));

    ws.addEventListener("close", (ev) => {
      if (ev.code === 4401 || ev.code === 4403) {
        surface(`events feed rejected (${ev.code}) — reload the page`);
      } else if (ev.code !== 1000) {
        surface(DISCONNECTED);
      }
    });

    ws.addEventListener("message", (ev) => {
      let frame: RpcEnvelope;

      try {
        frame = JSON.parse(ev.data);
      } catch {
        return;
      }

      if (frame.method !== "event" || !frame.params) {
        return;
      }

      const { type, payload } = frame.params;

      if (type === "tool.start") {
        const p = payload as
          | { tool_id?: string; name?: string; context?: string }
          | undefined;
        const toolId = p?.tool_id;

        if (!toolId) {
          return;
        }

        setTools((prev) =>
          [
            ...prev,
            {
              kind: "tool" as const,
              id: `tool-${toolId}-${prev.length}`,
              tool_id: toolId,
              name: p?.name ?? "tool",
              context: p?.context,
              status: "running" as const,
              startedAt: Date.now(),
            },
          ].slice(-TOOL_LIMIT),
        );
      } else if (type === "tool.progress") {
        const p = payload as
          | { name?: string; preview?: string }
          | undefined;

        if (!p?.name || !p.preview) {
          return;
        }

        setTools((prev) =>
          prev.map((t) =>
            t.status === "running" && t.name === p.name
              ? { ...t, preview: p.preview }
              : t,
          ),
        );
      } else if (type === "tool.complete") {
        const p = payload as
          | {
              tool_id?: string;
              summary?: string;
              error?: string;
              inline_diff?: string;
            }
          | undefined;

        if (!p?.tool_id) {
          return;
        }

        setTools((prev) =>
          prev.map((t) =>
            t.tool_id === p.tool_id
              ? {
                  ...t,
                  status: p.error ? "error" : "done",
                  summary: p.summary,
                  error: p.error,
                  inline_diff: p.inline_diff,
                  completedAt: Date.now(),
                }
              : t,
          ),
        );
      }
    });

    return () => {
      unmounting = true;
      ws.close();
    };
  }, [channel, version]);

  const reconnect = useCallback(() => {
    setError(null);
    setTools([]);
    setVersion((v) => v + 1);
  }, []);

  // Picker hands us a fully-formed slash command (e.g. "/model anthropic/...").
  // Fire-and-forget through `slash.exec`; the TUI pane will render the result
  // via PTY, so the sidebar doesn't need to surface output of its own.
  const onModelSubmit = useCallback(
    (slashCommand: string) => {
      if (!sessionId) {
        return;
      }

      void gw.request("slash.exec", {
        session_id: sessionId,
        command: slashCommand,
      });
      setModelOpen(false);
    },
    [gw, sessionId],
  );

  const canPickModel = state === "open" && !!sessionId;
  const modelLabel = (info.model ?? "—").split("/").slice(-1)[0] ?? "—";
  const banner = error ?? info.credential_warning ?? null;

  return (
    <aside
      className={cn(
        "flex h-full w-full min-w-0 shrink-0 flex-col gap-3 normal-case lg:w-80",
        className,
      )}
    >
      <Card className="flex items-center justify-between gap-2 px-3 py-2">
        <div className="min-w-0">
          <div className="text-xs uppercase tracking-wider text-muted-foreground">
            model
          </div>

          <button
            type="button"
            disabled={!canPickModel}
            onClick={() => setModelOpen(true)}
            className="flex items-center gap-1 truncate text-sm font-medium hover:underline disabled:cursor-not-allowed disabled:opacity-60 disabled:no-underline"
            title={info.model ?? "switch model"}
          >
            <span className="truncate">{modelLabel}</span>

            {canPickModel && (
              <ChevronDown className="h-3 w-3 shrink-0 opacity-60" />
            )}
          </button>
        </div>

        <Badge className={STATE_TONE[state]}>{STATE_LABEL[state]}</Badge>
      </Card>

      {banner && (
        <Card className="flex items-start gap-2 bg-card px-3 py-2 text-xs">
          <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-destructive" />

          <div className="min-w-0 flex-1">
            <div className="wrap-break-word text-destructive">{banner}</div>

            {error && (
              <Button
                variant="ghost"
                size="sm"
                className="mt-1 h-6 px-1.5 text-xs"
                onClick={reconnect}
              >
                <RefreshCw className="mr-1 h-3 w-3" />
                reconnect
              </Button>
            )}
          </div>
        </Card>
      )}

      <Card className="flex min-h-0 flex-1 flex-col px-2 py-2">
        <div className="px-1 pb-2 text-xs uppercase tracking-wider text-muted-foreground">
          tools
        </div>

        <div className="flex min-h-0 flex-1 flex-col gap-1.5 overflow-y-auto pr-1">
          {tools.length === 0 ? (
            <div className="px-2 py-4 text-center text-xs text-muted-foreground">
              no tool calls yet
            </div>
          ) : (
            tools.map((t) => <ToolCall key={t.id} tool={t} />)
          )}
        </div>
      </Card>

      {modelOpen && canPickModel && sessionId && (
        <ModelPickerDialog
          gw={gw}
          sessionId={sessionId}
          onClose={() => setModelOpen(false)}
          onSubmit={onModelSubmit}
        />
      )}
    </aside>
  );
}

```

---
## `src/components/DeleteConfirmDialog.tsx`
```tsx
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { useI18n } from "@/i18n";

export function DeleteConfirmDialog({
  cancelLabel,
  confirmLabel,
  description,
  loading,
  onCancel,
  onConfirm,
  open,
  title,
}: DeleteConfirmDialogProps) {
  const { t } = useI18n();

  return (
    <ConfirmDialog
      open={open}
      onCancel={onCancel}
      onConfirm={onConfirm}
      title={title}
      description={description}
      loading={loading}
      destructive
      confirmLabel={confirmLabel ?? t.common.delete}
      cancelLabel={cancelLabel ?? t.common.cancel}
    />
  );
}

interface DeleteConfirmDialogProps {
  cancelLabel?: string;
  confirmLabel?: string;
  description?: string;
  loading: boolean;
  onCancel: () => void;
  onConfirm: () => void;
  open: boolean;
  title: string;
}

```

---
## `src/components/FullWindowAurora.tsx`
```tsx
import { createPortal } from "react-dom";
import { Loader2 } from "lucide-react";
import { useTheme } from "@/themes/context";

export function FullWindowAurora({
  label,
  title = "Starting Elevate",
  subtitle = "Bringing the local agent runtime online.",
}: {
  label: string;
  title?: string;
  subtitle?: string;
}) {
  const { themeName } = useTheme();
  const logoSrc =
    themeName === "light" ? "/elevateos-wordmark.png" : "/elevateos-wordmark-dark.png";
  if (typeof document === "undefined") return null;
  return createPortal(
    <div
      role="status"
      aria-live="polite"
      className="onboarding-overlay fixed inset-0 z-[150] flex items-center justify-center overflow-hidden bg-background px-6 py-10"
    >
      <div className="onboarding-aurora-bg pointer-events-none absolute inset-0" aria-hidden />
      <div className="relative flex flex-col items-center text-center">
        <div className="onboarding-rise flex h-7 items-center">
          <img
            src={logoSrc}
            alt="Elevation"
            className="h-6 w-auto object-contain"
            draggable={false}
          />
        </div>
        <div className="onboarding-rise-delay-1 mt-7 font-mono-ui text-[10px] uppercase tracking-[0.18em] text-muted-foreground">
          {label}
        </div>
        <h2 className="onboarding-rise-delay-2 mt-2 text-[26px] font-medium leading-[1.1] tracking-tight text-foreground">
          {title}
        </h2>
        <p className="onboarding-rise-delay-3 mt-2 max-w-sm text-[13px] leading-6 text-muted-foreground">
          {subtitle}
        </p>
        <Loader2 className="onboarding-rise-delay-3 mt-6 h-4 w-4 animate-spin text-muted-foreground/70" />
      </div>
    </div>,
    document.body,
  );
}

```

---
## `src/components/LanguageSwitcher.tsx`
```tsx
import { Typography } from "@nous-research/ui/ui/components/typography/index";
import { useI18n } from "@/i18n/context";

/**
 * Compact language toggle — shows a clickable flag that switches between
 * English and Chinese.  Persists choice to localStorage.
 */
export function LanguageSwitcher() {
  const { locale, setLocale, t } = useI18n();

  const toggle = () => setLocale(locale === "en" ? "zh" : "en");

  return (
    <button
      type="button"
      onClick={toggle}
      className="group relative inline-flex items-center gap-1.5 px-2 py-1 text-[0.82rem] text-[var(--sidebar-text)] hover:text-[var(--sidebar-text-active)] transition-colors cursor-pointer focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
      title={t.language.switchTo}
      aria-label={t.language.switchTo}
    >
      {/* Show the *current* language's flag — tooltip advertises the click action */}
      <span className="text-base leading-none">
        {locale === "en" ? "🇬🇧" : "🇨🇳"}
      </span>
      <Typography
        mondwest
        className="hidden sm:inline tracking-wide uppercase text-[0.72rem]"
      >
        {locale === "en" ? "EN" : "中文"}
      </Typography>
    </button>
  );
}

```

---
## `src/components/LoginCard.tsx`
```tsx
import { useCallback, useEffect, useState } from "react";
import { Check, ChevronDown, Loader2, LogOut, Package } from "lucide-react";
import { api } from "@/lib/api";
import { useTheme } from "@/themes/context";
import type {
  LicenseStatusResponse,
  LicenseActivateResponse,
} from "@/lib/api-types";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

type Phase =
  | "loading"
  | "logged_out"
  | "signing_in"
  | "syncing"
  | "success"
  | "authenticated"
  | "error";

interface Props {
  onAuthChange?: (authenticated: boolean, packs?: LicenseStatusResponse["packs"]) => void;
}

export function LoginCard({ onAuthChange }: Props) {
  const { themeName } = useTheme();
  const logoSrc =
    themeName === "light" ? "/elevateos-wordmark.png" : "/elevateos-wordmark-dark.png";
  const [phase, setPhase] = useState<Phase>("loading");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [backendUrl, setBackendUrl] = useState("");
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [licenseStatus, setLicenseStatus] = useState<LicenseStatusResponse | null>(null);
  const [activationResult, setActivationResult] = useState<LicenseActivateResponse | null>(null);

  const loadStatus = useCallback(async () => {
    try {
      const status = await api.getLicenseStatus();
      setLicenseStatus(status);
      if (status.authenticated) {
        setPhase("authenticated");
        onAuthChange?.(true, status.packs);
      } else {
        setPhase("logged_out");
        onAuthChange?.(false, status.packs);
      }
    } catch {
      setPhase("logged_out");
    }
  }, [onAuthChange]);

  useEffect(() => { loadStatus(); }, [loadStatus]);

  // Self-heal: if the desktop main process refreshes the license (admin
  // revokes a pack on HQ, sign-out from another tab, etc.) or the window
  // regains focus, re-fetch status so the form/card flips without a reload.
  useEffect(() => {
    const handler = () => loadStatus();
    window.addEventListener("elevate:auth-changed", handler);
    window.addEventListener("focus", handler);
    document.addEventListener("visibilitychange", () => {
      if (document.visibilityState === "visible") handler();
    });
    return () => {
      window.removeEventListener("elevate:auth-changed", handler);
      window.removeEventListener("focus", handler);
    };
  }, [loadStatus]);

  const handleSignIn = async () => {
    if (!email.trim() || !password) return;
    setPhase("signing_in");
    setError(null);

    try {
      const result = await api.activateLicense(
        email.trim(),
        password,
        backendUrl.trim() || undefined,
      );
      setActivationResult(result);

      if (result.skill_count > 0) {
        setPhase("success");
      } else {
        setPhase("syncing");
        try {
          await api.syncLicenseSkills();
        } catch {
          // skill sync is best-effort
        }
        setPhase("success");
      }

      onAuthChange?.(true, result.packs);
      window.dispatchEvent(new Event("elevate:auth-changed"));
      await loadStatus();
    } catch (err: unknown) {
      setPhase("error");
      const message = err instanceof Error ? err.message : String(err);
      if (message.includes("401") || message.includes("Invalid")) {
        setError("Invalid email or password.");
      } else if (message.includes("402")) {
        setError("No active subscription. Contact Elevation Real Estate HQ.");
      } else {
        setError(message);
      }
    }
  };

  const handleLogout = async () => {
    try {
      const result = await api.logoutLicense();
      setLicenseStatus(null);
      setActivationResult(null);
      setPhase("logged_out");
      setEmail("");
      setPassword("");
      onAuthChange?.(false, result.packs);
      window.dispatchEvent(new Event("elevate:auth-changed"));
    } catch {
      setPhase("logged_out");
    }
  };

  if (phase === "loading") {
    return (
      <Card>
        <CardContent className="flex items-center justify-center py-12">
          <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
        </CardContent>
      </Card>
    );
  }

  if (phase === "authenticated" && licenseStatus) {
    const enabledPacks = Object.entries(licenseStatus.packs)
      .filter(([key, val]) => val && key !== "realEstateAny")
      .map(([key]) => {
        const labels: Record<string, string> = {
          realEstateSales: "Leads",
          realEstateMarketing: "Social & Marketing",
          realEstateAdmin: "Admin",
          realEstateCma: "CMA",
        };
        return labels[key] ?? key;
      });

    return (
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <div>
              <CardTitle>Elevation HQ</CardTitle>
              <CardDescription>Signed in as {licenseStatus.email}</CardDescription>
            </div>
            <div className="flex items-center gap-2">
              <span className="inline-flex items-center gap-1 rounded bg-[var(--color-success)]/10 px-2.5 py-1 font-mono-ui text-[0.66rem] font-semibold uppercase tracking-[0.06em] text-[var(--color-success)]">
                <Check className="h-3 w-3" />
                Active
              </span>
            </div>
          </div>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex items-center justify-between text-sm">
            <span className="text-muted-foreground">Tier</span>
            <span className="font-medium capitalize">{licenseStatus.tier}</span>
          </div>
          {enabledPacks.length > 0 && (
            <div className="flex items-center justify-between text-sm">
              <span className="text-muted-foreground">Skill Packs</span>
              <div className="flex flex-wrap justify-end gap-1">
                {enabledPacks.map((pack) => (
                  <span
                    key={pack}
                    className="inline-flex items-center gap-1 rounded-sm border border-border bg-card px-2 py-0.5 text-[0.72rem] font-medium text-primary"
                  >
                    <Package className="h-3 w-3" />
                    {pack}
                  </span>
                ))}
              </div>
            </div>
          )}
          <div className="pt-2">
            <Button variant="ghost" size="sm" onClick={handleLogout} className="text-muted-foreground">
              <LogOut className="h-3.5 w-3.5" />
              Sign out
            </Button>
          </div>
        </CardContent>
      </Card>
    );
  }

  if (phase === "success" && activationResult) {
    const packs = activationResult.packs;
    const enabledPacks = Object.entries(packs)
      .filter(([key, val]) => val && key !== "realEstateAny")
      .map(([key]) => {
        const labels: Record<string, string> = {
          realEstateSales: "Leads",
          realEstateMarketing: "Social & Marketing",
          realEstateAdmin: "Admin",
          realEstateCma: "CMA",
        };
        return labels[key] ?? key;
      });

    return (
      <Card>
        <CardHeader>
          <CardTitle>Welcome to Elevation</CardTitle>
          <CardDescription>Signed in as {activationResult.email}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {enabledPacks.length > 0 && (
            <div className="space-y-2">
              <p className="text-xs font-medium text-muted-foreground">Unlocked Skill Packs</p>
              <div className="grid gap-2">
                {enabledPacks.map((pack) => (
                  <div
                    key={pack}
                    className="flex items-center gap-2.5 rounded-md border border-[var(--color-success)]/20 bg-[var(--color-success)]/5 px-3 py-2"
                  >
                    <Check className="h-4 w-4 text-[var(--color-success)]" />
                    <span className="text-sm font-medium">{pack}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
          {activationResult.skill_count > 0 && (
            <p className="text-xs text-muted-foreground">
              {activationResult.skill_count} skills synced
            </p>
          )}
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader className="items-center text-center">
        <div className="flex h-8 items-center justify-center">
          <img
            src={logoSrc}
            alt="Elevation"
            className="h-7 w-auto object-contain"
            draggable={false}
          />
        </div>
        <CardDescription className="pt-1">
          Enter your Elevation Real Estate HQ credentials to unlock your skill packs.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <form
          onSubmit={(e) => { e.preventDefault(); handleSignIn(); }}
          className="space-y-3"
        >
          <div className="space-y-1.5">
            <label htmlFor="login-email" className="text-xs font-medium text-muted-foreground">
              Email
            </label>
            <Input
              id="login-email"
              type="email"
              placeholder="you@elevationrealestatehq.com"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              disabled={phase === "signing_in" || phase === "syncing"}
              autoComplete="email"
              autoFocus
            />
          </div>
          <div className="space-y-1.5">
            <label htmlFor="login-password" className="text-xs font-medium text-muted-foreground">
              Password
            </label>
            <Input
              id="login-password"
              type="password"
              placeholder="Password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              disabled={phase === "signing_in" || phase === "syncing"}
              autoComplete="current-password"
            />
          </div>

          <button
            type="button"
            onClick={() => setShowAdvanced((v) => !v)}
            className={cn(
              "flex items-center gap-1 text-[0.72rem] text-muted-foreground/60 transition-colors hover:text-muted-foreground",
              showAdvanced && "text-muted-foreground",
            )}
          >
            <ChevronDown className={cn("h-3 w-3 transition-transform", showAdvanced && "rotate-180")} />
            Advanced
          </button>
          {showAdvanced && (
            <div className="space-y-1.5">
              <label htmlFor="login-backend" className="text-xs font-medium text-muted-foreground">
                Backend URL
              </label>
              <Input
                id="login-backend"
                type="url"
                placeholder="https://api.elevationrealestatehq.com"
                value={backendUrl}
                onChange={(e) => setBackendUrl(e.target.value)}
                disabled={phase === "signing_in" || phase === "syncing"}
              />
            </div>
          )}

          {error && (
            <p className="rounded-sm border border-border bg-card px-3 py-2 text-xs font-medium text-destructive">
              {error}
            </p>
          )}

          <Button
            type="submit"
            className="w-full"
            disabled={phase === "signing_in" || phase === "syncing" || !email.trim() || !password}
          >
            {phase === "signing_in" ? (
              <>
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
                Signing in...
              </>
            ) : phase === "syncing" ? (
              <>
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
                Syncing skill packs...
              </>
            ) : phase === "error" ? (
              "Try again"
            ) : (
              "Sign in"
            )}
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}

```

---
## `src/components/Markdown.tsx`
```tsx
import { useMemo, type ReactNode } from "react";

/**
 * Lightweight markdown renderer for LLM output.
 * Handles: code blocks, inline code, bold, italic, headers, links, lists, horizontal rules.
 * NOT a full CommonMark parser — optimized for typical assistant message patterns.
 *
 * `streaming` renders a blinking caret at the tail of the last block so it
 * appears to hug the final character instead of wrapping onto a new line
 * after a block element (paragraph/list/code/…).
 */
export function Markdown({
  content,
  highlightTerms,
  streaming,
}: {
  content: string;
  highlightTerms?: string[];
  streaming?: boolean;
}) {
  const blocks = useMemo(() => parseBlocks(content), [content]);
  const caret = streaming ? <StreamingCaret /> : null;

  return (
    <div className="text-sm text-foreground leading-relaxed space-y-2">
      {blocks.map((block, i) => (
        <Block
          key={i}
          block={block}
          highlightTerms={highlightTerms}
          caret={caret && i === blocks.length - 1 ? caret : null}
        />
      ))}
      {blocks.length === 0 && caret}
    </div>
  );
}

function StreamingCaret() {
  return (
    <span
      aria-hidden
      className="inline-block w-[0.5em] h-[1em] ml-0.5 align-[-0.15em] bg-foreground/50 animate-pulse"
    />
  );
}

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

type BlockNode =
  | { type: "code"; lang: string; content: string }
  | { type: "heading"; level: number; content: string }
  | { type: "hr" }
  | { type: "list"; ordered: boolean; items: string[] }
  | { type: "paragraph"; content: string };

/* ------------------------------------------------------------------ */
/*  Block parser                                                       */
/* ------------------------------------------------------------------ */

function parseBlocks(text: string): BlockNode[] {
  const lines = text.split("\n");
  const blocks: BlockNode[] = [];
  let i = 0;

  while (i < lines.length) {
    const line = lines[i];

    // Fenced code block
    const fenceMatch = line.match(/^```(\w*)/);
    if (fenceMatch) {
      const lang = fenceMatch[1] || "";
      const codeLines: string[] = [];
      i++;
      while (i < lines.length && !lines[i].startsWith("```")) {
        codeLines.push(lines[i]);
        i++;
      }
      i++; // skip closing ```
      blocks.push({ type: "code", lang, content: codeLines.join("\n") });
      continue;
    }

    // Heading
    const headingMatch = line.match(/^(#{1,4})\s+(.+)/);
    if (headingMatch) {
      blocks.push({
        type: "heading",
        level: headingMatch[1].length,
        content: headingMatch[2],
      });
      i++;
      continue;
    }

    // Horizontal rule
    if (/^[-*_]{3,}\s*$/.test(line)) {
      blocks.push({ type: "hr" });
      i++;
      continue;
    }

    // Unordered list
    if (/^[-*+]\s/.test(line)) {
      const items: string[] = [];
      while (i < lines.length && /^[-*+]\s/.test(lines[i])) {
        items.push(lines[i].replace(/^[-*+]\s/, ""));
        i++;
      }
      blocks.push({ type: "list", ordered: false, items });
      continue;
    }

    // Ordered list
    if (/^\d+[.)]\s/.test(line)) {
      const items: string[] = [];
      while (i < lines.length && /^\d+[.)]\s/.test(lines[i])) {
        items.push(lines[i].replace(/^\d+[.)]\s/, ""));
        i++;
      }
      blocks.push({ type: "list", ordered: true, items });
      continue;
    }

    // Empty line
    if (line.trim() === "") {
      i++;
      continue;
    }

    // Paragraph — collect consecutive non-empty, non-special lines
    const paraLines: string[] = [];
    while (
      i < lines.length &&
      lines[i].trim() !== "" &&
      !lines[i].match(/^```/) &&
      !lines[i].match(/^#{1,4}\s/) &&
      !lines[i].match(/^[-*+]\s/) &&
      !lines[i].match(/^\d+[.)]\s/) &&
      !lines[i].match(/^[-*_]{3,}\s*$/)
    ) {
      paraLines.push(lines[i]);
      i++;
    }
    if (paraLines.length > 0) {
      blocks.push({ type: "paragraph", content: paraLines.join("\n") });
    }
  }

  return blocks;
}

/* ------------------------------------------------------------------ */
/*  Block renderer                                                     */
/* ------------------------------------------------------------------ */

function Block({
  block,
  highlightTerms,
  caret,
}: {
  block: BlockNode;
  highlightTerms?: string[];
  caret?: ReactNode;
}) {
  switch (block.type) {
    case "code":
      return (
        <pre className="rounded-md bg-foreground/[0.06] border border-border px-3 py-2.5 text-xs font-mono leading-relaxed overflow-x-auto text-foreground">
          <code className="text-foreground">
            {block.content}
            {caret}
          </code>
        </pre>
      );

    case "heading": {
      const Tag = `h${Math.min(block.level, 4)}` as "h1" | "h2" | "h3" | "h4";
      const sizes: Record<string, string> = {
        h1: "text-base font-bold",
        h2: "text-sm font-bold",
        h3: "text-sm font-semibold",
        h4: "text-sm font-medium",
      };
      return (
        <Tag className={sizes[Tag]}>
          <InlineContent text={block.content} highlightTerms={highlightTerms} />
          {caret}
        </Tag>
      );
    }

    case "hr":
      return (
        <>
          <hr className="border-border" />
          {caret}
        </>
      );

    case "list": {
      const Tag = block.ordered ? "ol" : "ul";
      const last = block.items.length - 1;
      return (
        <Tag
          className={`space-y-0.5 ${block.ordered ? "list-decimal" : "list-disc"} pl-5 text-sm`}
        >
          {block.items.map((item, i) => (
            <li key={i}>
              <InlineContent text={item} highlightTerms={highlightTerms} />
              {i === last ? caret : null}
            </li>
          ))}
        </Tag>
      );
    }

    case "paragraph":
      return (
        <p>
          <InlineContent text={block.content} highlightTerms={highlightTerms} />
          {caret}
        </p>
      );
  }
}

/* ------------------------------------------------------------------ */
/*  Inline parser + renderer                                           */
/* ------------------------------------------------------------------ */

type InlineNode =
  | { type: "text"; content: string }
  | { type: "code"; content: string }
  | { type: "bold"; content: string }
  | { type: "italic"; content: string }
  | { type: "link"; text: string; href: string }
  | { type: "br" };

function parseInline(text: string): InlineNode[] {
  const nodes: InlineNode[] = [];
  // Pattern priority: code > link > bold > italic > bare URL > line break
  const pattern =
    /(`[^`]+`)|(\[([^\]]+)\]\(([^)]+)\))|(\*\*([^*]+)\*\*)|(\*([^*]+)\*)|(\bhttps?:\/\/[^\s<>)\]]+)|(\n)/g;
  let lastIndex = 0;
  let match: RegExpExecArray | null;

  while ((match = pattern.exec(text)) !== null) {
    if (match.index > lastIndex) {
      nodes.push({ type: "text", content: text.slice(lastIndex, match.index) });
    }

    if (match[1]) {
      // Inline code
      nodes.push({ type: "code", content: match[1].slice(1, -1) });
    } else if (match[2]) {
      // [text](url) link
      nodes.push({ type: "link", text: match[3], href: match[4] });
    } else if (match[5]) {
      // **bold**
      nodes.push({ type: "bold", content: match[6] });
    } else if (match[7]) {
      // *italic*
      nodes.push({ type: "italic", content: match[8] });
    } else if (match[9]) {
      // Bare URL
      nodes.push({ type: "link", text: match[9], href: match[9] });
    } else if (match[10]) {
      // Line break within paragraph
      nodes.push({ type: "br" });
    }

    lastIndex = match.index + match[0].length;
  }

  if (lastIndex < text.length) {
    nodes.push({ type: "text", content: text.slice(lastIndex) });
  }

  return nodes;
}

function InlineContent({
  text,
  highlightTerms,
}: {
  text: string;
  highlightTerms?: string[];
}) {
  const nodes = useMemo(() => parseInline(text), [text]);

  return (
    <>
      {nodes.map((node, i) => {
        switch (node.type) {
          case "text":
            return (
              <HighlightedText
                key={i}
                text={node.content}
                terms={highlightTerms}
              />
            );
          case "code":
            return (
              <code
                key={i}
                className="rounded-sm bg-foreground/[0.08] px-1.5 py-0.5 text-[0.85em] font-mono text-foreground"
              >
                {node.content}
              </code>
            );
          case "bold":
            return (
              <strong key={i} className="font-semibold">
                <HighlightedText text={node.content} terms={highlightTerms} />
              </strong>
            );
          case "italic":
            return (
              <em key={i}>
                <HighlightedText text={node.content} terms={highlightTerms} />
              </em>
            );
          case "link":
            return (
              <a
                key={i}
                href={node.href}
                target="_blank"
                rel="noreferrer"
                className="text-primary underline underline-offset-2 decoration-primary/30 hover:decoration-primary/60 transition-colors"
              >
                {node.text}
              </a>
            );
          case "br":
            return <br key={i} />;
        }
      })}
    </>
  );
}

/** Highlight search terms within a plain text string. */
function HighlightedText({ text, terms }: { text: string; terms?: string[] }) {
  if (!terms || terms.length === 0) return <>{text}</>;

  // Build a regex that matches any of the search terms (case-insensitive)
  const escaped = terms.map((t) => t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
  const regex = new RegExp(`(${escaped.join("|")})`, "gi");
  const parts = text.split(regex);

  return (
    <>
      {parts.map((part, i) =>
        regex.test(part) ? (
          <mark key={i} className="bg-transparent text-warning underline decoration-warning decoration-2 underline-offset-2 px-0.5">
            {part}
          </mark>
        ) : (
          <span key={i}>{part}</span>
        ),
      )}
    </>
  );
}

```

---
## `src/components/MemoryConstellation.tsx`
```tsx
import { useCallback, useId, useMemo, useRef, useState } from "react";
import type { CSSProperties } from "react";
import type { AgentHubMemoryEdge, AgentHubMemoryNode } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

type PositionedNode = {
  degree: number;
  groupKey: string;
  kind: NodeKind;
  node: AgentHubMemoryNode;
  x: number;
  y: number;
  r: number;
  opacity: number;
  rank: number;
};

type NodeKind =
  | "asset"
  | "chunk"
  | "community"
  | "document"
  | "entity"
  | "fact"
  | "general"
  | "plaud"
  | "project"
  | "tool"
  | "user_pref";

const WIDTH = 1280;
const HEIGHT = 780;
const VIEW_X = 120;
const VIEW_Y = 105;
const VIEW_WIDTH = 1080;
const VIEW_HEIGHT = 650;
const CENTER_X = WIDTH / 2;
const CENTER_Y = HEIGHT / 2 + 10;
const BOUNDS = {
  maxX: VIEW_X + VIEW_WIDTH - 72,
  maxY: VIEW_Y + VIEW_HEIGHT - 72,
  minX: VIEW_X + 72,
  minY: VIEW_Y + 72,
};

const KIND_ORDER: NodeKind[] = [
  "entity",
  "fact",
  "community",
  "project",
  "document",
  "chunk",
  "tool",
  "user_pref",
  "plaud",
  "asset",
  "general",
];

const NODE_TONE: Record<NodeKind, { accent: string; fill: string; halo: string; label: string }> = {
  asset: {
    accent: "var(--memory-node-asset)",
    fill: "var(--memory-node-asset-fill)",
    halo: "var(--memory-node-asset-halo)",
    label: "Asset",
  },
  chunk: {
    accent: "var(--memory-node-chunk)",
    fill: "var(--memory-node-chunk-fill)",
    halo: "var(--memory-node-chunk-halo)",
    label: "Chunk",
  },
  community: {
    accent: "var(--memory-node-community)",
    fill: "var(--memory-node-community-fill)",
    halo: "var(--memory-node-community-halo)",
    label: "Community",
  },
  document: {
    accent: "var(--memory-node-document)",
    fill: "var(--memory-node-document-fill)",
    halo: "var(--memory-node-document-halo)",
    label: "Document",
  },
  entity: {
    accent: "var(--memory-node-entity)",
    fill: "var(--memory-node-entity-fill)",
    halo: "var(--memory-node-entity-halo)",
    label: "Entity",
  },
  fact: {
    accent: "var(--memory-node-fact)",
    fill: "var(--memory-node-fact-fill)",
    halo: "var(--memory-node-fact-halo)",
    label: "Fact",
  },
  general: {
    accent: "var(--memory-node-general)",
    fill: "var(--memory-node-general-fill)",
    halo: "var(--memory-node-general-halo)",
    label: "General",
  },
  plaud: {
    accent: "var(--memory-node-plaud)",
    fill: "var(--memory-node-plaud-fill)",
    halo: "var(--memory-node-plaud-halo)",
    label: "Plaud",
  },
  project: {
    accent: "var(--memory-node-project)",
    fill: "var(--memory-node-project-fill)",
    halo: "var(--memory-node-project-halo)",
    label: "Project",
  },
  tool: {
    accent: "var(--memory-node-tool)",
    fill: "var(--memory-node-tool-fill)",
    halo: "var(--memory-node-tool-halo)",
    label: "Tool",
  },
  user_pref: {
    accent: "var(--memory-node-user)",
    fill: "var(--memory-node-user-fill)",
    halo: "var(--memory-node-user-halo)",
    label: "User preference",
  },
};

function hashString(value: string): number {
  let hash = 2166136261;
  for (let i = 0; i < value.length; i += 1) {
    hash ^= value.charCodeAt(i);
    hash = Math.imul(hash, 16777619);
  }
  return hash >>> 0;
}

function jitter(seed: string, amount: number): number {
  return ((hashString(seed) % 1000) / 1000 - 0.5) * amount;
}

function clamp(value: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, value));
}

function normalizeKey(value: string | undefined): string {
  return (value ?? "").trim().toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "");
}

function nodeKind(node: AgentHubMemoryNode): NodeKind {
  const category = normalizeKey(node.category);
  const type = normalizeKey(node.type);
  const key = category || type;

  if (key.includes("user_pref") || key.includes("preference")) return "user_pref";
  if (key.includes("community")) return "community";
  if (key.includes("project")) return "project";
  if (key.includes("tool")) return "tool";
  if (key.includes("plaud") || key.includes("transcript")) return "plaud";
  if (key.includes("document") || type === "document") return "document";
  if (key.includes("chunk") || type === "chunk") return "chunk";
  if (key.includes("asset") || type === "asset") return "asset";
  if (type === "entity") return "entity";
  if (type === "fact") return "fact";
  return "general";
}

function clusterKey(node: AgentHubMemoryNode): string {
  if (node.category) return node.category;
  if (node.type && node.type !== "fact") return node.type;
  const firstWord = node.label.trim().split(/\s+/)[0]?.toLowerCase();
  return firstWord || "memory";
}

function nodeWeight(node: AgentHubMemoryNode, degree: number): number {
  const raw = Number.isFinite(node.weight) ? Number(node.weight) : 1;
  return Math.max(raw, 1) + degree * 0.7;
}

function labelFor(node: AgentHubMemoryNode): string {
  return node.label.trim().replace(/\s+/g, " ");
}

function buildVisualEdges(
  nodes: AgentHubMemoryNode[],
  positions: Map<string, PositionedNode>,
  edges: AgentHubMemoryEdge[],
): AgentHubMemoryEdge[] {
  if (edges.length > 0) return edges;
  const grouped = new Map<string, AgentHubMemoryNode[]>();
  for (const node of nodes) {
    const key = clusterKey(node);
    grouped.set(key, [...(grouped.get(key) ?? []), node]);
  }
  const visualEdges: AgentHubMemoryEdge[] = [];
  for (const group of grouped.values()) {
    const sorted = [...group].sort((a, b) => {
      const pa = positions.get(a.id);
      const pb = positions.get(b.id);
      if (!pa || !pb) return 0;
      return pa.x - pb.x || pa.y - pb.y;
    });
    for (let i = 1; i < sorted.length; i += 1) {
      visualEdges.push({
        source: sorted[Math.max(0, i - 1)].id,
        target: sorted[i].id,
        type: "visual-cluster",
      });
    }
  }
  return visualEdges;
}

function relaxConstellation(nodes: PositionedNode[], edges: AgentHubMemoryEdge[], compact: boolean) {
  const byId = new Map(nodes.map((item) => [item.node.id, item]));
  const anchors = new Map(nodes.map((item) => [item.node.id, { x: item.x, y: item.y }]));
  const iterations = compact ? 46 : 76;
  const linkStrength = compact ? 0.01 : 0.011;
  const anchorStrength = compact ? 0.068 : 0.086;
  const collisionPad = compact ? 10 : 16;

  for (let iteration = 0; iteration < iterations; iteration += 1) {
    for (const item of nodes) {
      const anchor = anchors.get(item.node.id);
      if (!anchor) continue;
      item.x += (anchor.x - item.x) * anchorStrength;
      item.y += (anchor.y - item.y) * anchorStrength;
    }

    for (const edge of edges) {
      const source = byId.get(edge.source);
      const target = byId.get(edge.target);
      if (!source || !target) continue;
      const dx = target.x - source.x;
      const dy = target.y - source.y;
      const distance = Math.max(1, Math.hypot(dx, dy));
      const preferred = edge.type === "visual-cluster" ? (compact ? 108 : 154) : (compact ? 142 : 205);
      const pull = ((distance - preferred) / distance) * linkStrength;
      const fx = dx * pull;
      const fy = dy * pull;
      source.x += fx;
      source.y += fy;
      target.x -= fx;
      target.y -= fy;
    }

    for (let i = 0; i < nodes.length; i += 1) {
      for (let j = i + 1; j < nodes.length; j += 1) {
        const a = nodes[i];
        const b = nodes[j];
        const dx = b.x - a.x;
        const dy = b.y - a.y;
        const distance = Math.max(1, Math.hypot(dx, dy));
        const minDistance = a.r + b.r + collisionPad;
        if (distance >= minDistance) continue;
        const push = ((minDistance - distance) / distance) * 0.5;
        const fx = dx * push;
        const fy = dy * push;
        a.x -= fx;
        a.y -= fy;
        b.x += fx;
        b.y += fy;
      }
    }

    for (const item of nodes) {
      item.x = clamp(item.x, BOUNDS.minX, BOUNDS.maxX);
      item.y = clamp(item.y, BOUNDS.minY, BOUNDS.maxY);
    }
  }
}

function convexHull(points: Array<{ x: number; y: number }>): Array<{ x: number; y: number }> {
  if (points.length < 3) return points;
  const sorted = [...points].sort((a, b) => a.x - b.x || a.y - b.y);
  const cross = (o: { x: number; y: number }, a: { x: number; y: number }, b: { x: number; y: number }) =>
    (a.x - o.x) * (b.y - o.y) - (a.y - o.y) * (b.x - o.x);
  const lower: Array<{ x: number; y: number }> = [];
  for (const p of sorted) {
    while (lower.length >= 2 && cross(lower[lower.length - 2], lower[lower.length - 1], p) <= 0) lower.pop();
    lower.push(p);
  }
  const upper: Array<{ x: number; y: number }> = [];
  for (let i = sorted.length - 1; i >= 0; i--) {
    const p = sorted[i];
    while (upper.length >= 2 && cross(upper[upper.length - 2], upper[upper.length - 1], p) <= 0) upper.pop();
    upper.push(p);
  }
  lower.pop();
  upper.pop();
  return lower.concat(upper);
}

function expandHull(hull: Array<{ x: number; y: number }>, pad: number): string {
  if (hull.length < 2) return "";
  const cx = hull.reduce((s, p) => s + p.x, 0) / hull.length;
  const cy = hull.reduce((s, p) => s + p.y, 0) / hull.length;
  return hull
    .map((p) => {
      const dx = p.x - cx;
      const dy = p.y - cy;
      const d = Math.max(1, Math.hypot(dx, dy));
      return `${p.x + (dx / d) * pad},${p.y + (dy / d) * pad}`;
    })
    .join(" ");
}

function isEdgeConnected(edge: AgentHubMemoryEdge, nodeId: string | null) {
  return Boolean(nodeId && (edge.source === nodeId || edge.target === nodeId));
}

export function MemoryConstellation({
  className,
  compact = false,
  edges,
  nodes,
}: {
  className?: string;
  compact?: boolean;
  edges: AgentHubMemoryEdge[];
  nodes: AgentHubMemoryNode[];
}) {
  const [hoveredNodeId, setHoveredNodeId] = useState<string | null>(null);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const rawId = useId().replace(/:/g, "");
  const gridId = `memory-grid-${rawId}`;
  const glowId = `memory-glow-${rawId}`;
  const summaryId = `memory-summary-${rawId}`;

  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const panRef = useRef(pan);
  panRef.current = pan;
  const zoomRef = useRef(zoom);
  zoomRef.current = zoom;
  const dragRef = useRef<{ startX: number; startY: number; panX: number; panY: number } | null>(null);
  const svgRef = useRef<SVGSVGElement>(null);

  const handleWheel = useCallback((e: React.WheelEvent) => {
    e.preventDefault();
    const delta = e.deltaY > 0 ? 1.08 : 0.93;
    setZoom((z) => clamp(z * delta, 0.4, 3));
  }, []);

  const handlePointerDown = useCallback((e: React.PointerEvent) => {
    if (e.button !== 0) return;
    const target = e.target as Element;
    if (target.closest(".memory-constellation-node")) return;
    (e.currentTarget as Element).setPointerCapture(e.pointerId);
    dragRef.current = { startX: e.clientX, startY: e.clientY, panX: panRef.current.x, panY: panRef.current.y };
  }, []);

  const handlePointerMove = useCallback((e: React.PointerEvent) => {
    if (!dragRef.current) return;
    const svg = svgRef.current;
    if (!svg) return;
    const rect = svg.getBoundingClientRect();
    const z = zoomRef.current;
    const scaleX = (VIEW_WIDTH * z) / rect.width;
    const scaleY = (VIEW_HEIGHT * z) / rect.height;
    setPan({
      x: dragRef.current.panX - (e.clientX - dragRef.current.startX) * scaleX,
      y: dragRef.current.panY - (e.clientY - dragRef.current.startY) * scaleY,
    });
  }, []);

  const handlePointerUp = useCallback(() => {
    dragRef.current = null;
  }, []);

  const layout = useMemo(() => {
    const degree = new Map<string, number>();
    for (const edge of edges) {
      degree.set(edge.source, (degree.get(edge.source) ?? 0) + 1);
      degree.set(edge.target, (degree.get(edge.target) ?? 0) + 1);
    }
    const isolatedNodes = nodes
      .filter((node) => (degree.get(node.id) ?? 0) === 0)
      .sort((a, b) => nodeKind(a).localeCompare(nodeKind(b)) || labelFor(a).localeCompare(labelFor(b)));
    const isolatedRank = new Map(isolatedNodes.map((node, index) => [node.id, index]));

    const grouped = new Map<NodeKind, AgentHubMemoryNode[]>();
    for (const node of nodes) {
      const key = nodeKind(node);
      grouped.set(key, [...(grouped.get(key) ?? []), node]);
    }

    const sortedGroups = [...grouped.entries()].sort((a, b) => {
      const orderA = KIND_ORDER.indexOf(a[0]);
      const orderB = KIND_ORDER.indexOf(b[0]);
      return orderA - orderB || b[1].length - a[1].length;
    });
    const activeKinds = sortedGroups.map(([kind]) => kind);
    const kindAngles = new Map<NodeKind, number>();
    activeKinds.forEach((kind, index) => {
      kindAngles.set(kind, -0.18 + (index / Math.max(activeKinds.length, 1)) * Math.PI * 2);
    });

    const positioned: PositionedNode[] = [];

    sortedGroups.forEach(([kind, group]) => {
      const angleBase = kindAngles.get(kind) ?? 0;
      const angleBand = clamp((Math.PI * 2) / Math.max(activeKinds.length, 1) * 0.68, 0.42, 1.04);

      group
        .slice()
        .sort((a, b) => nodeWeight(b, degree.get(b.id) ?? 0) - nodeWeight(a, degree.get(a.id) ?? 0))
        .forEach((node, index) => {
          const nodeDegree = degree.get(node.id) ?? 0;
          const weight = nodeWeight(node, nodeDegree);
          const r = Math.min(compact ? 10 : 12, (compact ? 2.8 : 3) + Math.sqrt(weight) * (compact ? 1.1 : 1.2));
          const isolatedIndex = isolatedRank.get(node.id);
          const isolated = isolatedIndex !== undefined;
          const ratio = isolated
            ? isolatedIndex / Math.max(isolatedNodes.length, 1)
            : group.length <= 1
              ? 0.5
              : index / (group.length - 1);
          const angle = isolated
            ? -Math.PI / 2 + ratio * Math.PI * 2 + jitter(`${node.id}:isolated-angle`, 0.08)
            : angleBase +
              (ratio - 0.5) * angleBand +
              (index % 2 === 0 ? 1 : -1) * (0.06 + (hashString(node.id) % 9) / 180);
          const ring = isolated ? isolatedIndex % 3 : index % (compact ? 3 : 4);
          const orbit = isolated
            ? (compact ? 180 : 280) + ring * (compact ? 16 : 24)
            : (compact ? 120 : 190) + ring * (compact ? 34 : 50) + Math.floor(index / (compact ? 3 : 4)) * (compact ? 10 : 14);
          const weightedOrbit = isolated ? orbit : orbit - Math.min(weight, 18) * (compact ? 1.2 : 1.65);
          positioned.push({
            degree: nodeDegree,
            groupKey: kind,
            kind,
            node,
            opacity: Math.min(0.98, 0.62 + Math.min(weight, 12) * 0.032),
            r,
            x: clamp(
              CENTER_X + Math.cos(angle) * weightedOrbit * (compact ? 1.04 : 1.18) + jitter(`${node.id}:x`, compact ? 10 : 18),
              BOUNDS.minX,
              BOUNDS.maxX,
            ),
            y: clamp(
              CENTER_Y + Math.sin(angle) * weightedOrbit * (compact ? 0.82 : 0.8) + jitter(`${node.id}:y`, compact ? 10 : 18),
              BOUNDS.minY,
              BOUNDS.maxY,
            ),
            rank: 0,
          });
        });
    });

    const ranked = [...positioned].sort((a, b) => {
      const aw = nodeWeight(a.node, a.degree);
      const bw = nodeWeight(b.node, b.degree);
      return bw - aw || b.degree - a.degree || labelFor(a.node).localeCompare(labelFor(b.node));
    });
    ranked.forEach((item, rank) => {
      item.rank = rank;
    });

    const initialById = new Map(positioned.map((item) => [item.node.id, item]));
    const visualEdges = buildVisualEdges(nodes, initialById, edges);
    relaxConstellation(positioned, visualEdges, compact);

    const byId = new Map(positioned.map((item) => [item.node.id, item]));
    const kinds = new Map<NodeKind, number>();
    for (const item of positioned) {
      kinds.set(item.kind, (kinds.get(item.kind) ?? 0) + 1);
    }

    const clusterGroups = new Map<string, PositionedNode[]>();
    for (const item of positioned) {
      const key = clusterKey(item.node);
      clusterGroups.set(key, [...(clusterGroups.get(key) ?? []), item]);
    }
    const hulls: Array<{ key: string; kind: NodeKind; path: string }> = [];
    for (const [key, members] of clusterGroups) {
      if (members.length < 3) continue;
      const hull = convexHull(members.map((m) => ({ x: m.x, y: m.y })));
      if (hull.length < 3) continue;
      hulls.push({ key, kind: members[0].kind, path: expandHull(hull, 28) });
    }

    return {
      byId,
      edges: visualEdges,
      groups: [...kinds.entries()]
        .sort((a, b) => b[1] - a[1])
        .map(([kind, total]) => ({ kind, name: NODE_TONE[kind].label, total }))
        .slice(0, compact ? 5 : 9),
      hulls,
      positioned: [...positioned].sort((a, b) => a.r - b.r),
      ranked,
    };
  }, [compact, edges, nodes]);

  const activeNodeId = hoveredNodeId ?? selectedNodeId;
  const activeConnections = useMemo(() => {
    const connected = new Set<string>();
    if (!activeNodeId) return connected;
    connected.add(activeNodeId);
    for (const edge of layout.edges) {
      if (edge.source === activeNodeId) connected.add(edge.target);
      if (edge.target === activeNodeId) connected.add(edge.source);
    }
    return connected;
  }, [activeNodeId, layout.edges]);
  const activeNode = activeNodeId ? layout.byId.get(activeNodeId) ?? null : null;
  const activeEdgeTypes = useMemo(() => {
    if (!activeNodeId) return [] as Array<{ type: string; count: number }>;
    const counts = new Map<string, number>();
    for (const edge of layout.edges) {
      if (!isEdgeConnected(edge, activeNodeId)) continue;
      const label = edge.type === "visual-cluster" ? "visual" : edge.type.replace(/_/g, " ");
      counts.set(label, (counts.get(label) ?? 0) + 1);
    }
    return [...counts.entries()]
      .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
      .slice(0, 4)
      .map(([type, count]) => ({ type, count }));
  }, [activeNodeId, layout.edges]);
  const focusNode = activeNode ?? layout.ranked[0] ?? null;
  const displayedLinks = activeNode
    ? layout.edges.filter((edge) => isEdgeConnected(edge, activeNode.node.id)).length
    : layout.edges.length;
  const realLinks = edges.length || layout.edges.length;
  const graphStyle = {
    "--memory-bg": "color-mix(in srgb, var(--background-base) 92%, var(--midground-base))",
    "--memory-panel": "color-mix(in srgb, var(--midground-base) 6%, var(--background-base))",
    "--memory-panel-strong": "color-mix(in srgb, var(--midground-base) 10%, var(--background-base))",
    "--memory-grid": "color-mix(in srgb, var(--midground-base) 8%, transparent)",
    "--memory-edge": "color-mix(in srgb, var(--midground-base) 26%, transparent)",
    "--memory-edge-soft": "color-mix(in srgb, var(--midground-base) 14%, transparent)",
    "--memory-edge-active": "color-mix(in srgb, var(--color-primary) 72%, var(--midground-base))",
    "--memory-node-entity": "color-mix(in srgb, var(--color-primary) 82%, var(--midground-base))",
    "--memory-node-entity-fill": "color-mix(in srgb, var(--color-primary) 74%, var(--midground-base))",
    "--memory-node-entity-halo": "color-mix(in srgb, var(--color-primary) 25%, transparent)",
    "--memory-node-fact": "color-mix(in srgb, var(--color-success) 84%, var(--midground-base))",
    "--memory-node-fact-fill": "color-mix(in srgb, var(--color-success) 66%, var(--midground-base))",
    "--memory-node-fact-halo": "color-mix(in srgb, var(--color-success) 22%, transparent)",
    "--memory-node-document": "color-mix(in srgb, var(--color-warning) 82%, var(--midground-base))",
    "--memory-node-document-fill": "color-mix(in srgb, var(--color-warning) 66%, var(--midground-base))",
    "--memory-node-document-halo": "color-mix(in srgb, var(--color-warning) 23%, transparent)",
    "--memory-node-chunk": "color-mix(in srgb, var(--midground-base) 78%, var(--background-base))",
    "--memory-node-chunk-fill": "color-mix(in srgb, var(--midground-base) 62%, var(--background-base))",
    "--memory-node-chunk-halo": "color-mix(in srgb, var(--midground-base) 14%, transparent)",
    "--memory-node-community": "color-mix(in srgb, var(--color-primary) 48%, var(--color-success) 44%)",
    "--memory-node-community-fill": "color-mix(in srgb, var(--color-primary) 35%, var(--color-success) 38%)",
    "--memory-node-community-halo": "color-mix(in srgb, var(--color-primary) 20%, transparent)",
    "--memory-node-project": "color-mix(in srgb, var(--color-primary) 60%, var(--color-warning) 34%)",
    "--memory-node-project-fill": "color-mix(in srgb, var(--color-primary) 48%, var(--color-warning) 26%)",
    "--memory-node-project-halo": "color-mix(in srgb, var(--color-warning) 24%, transparent)",
    "--memory-node-user": "color-mix(in srgb, var(--color-warning) 72%, var(--color-success) 20%)",
    "--memory-node-user-fill": "color-mix(in srgb, var(--color-warning) 56%, var(--color-success) 18%)",
    "--memory-node-user-halo": "color-mix(in srgb, var(--color-warning) 22%, transparent)",
    "--memory-node-tool": "color-mix(in srgb, var(--color-success) 72%, var(--color-primary) 22%)",
    "--memory-node-tool-fill": "color-mix(in srgb, var(--color-success) 54%, var(--color-primary) 18%)",
    "--memory-node-tool-halo": "color-mix(in srgb, var(--color-success) 24%, transparent)",
    "--memory-node-plaud": "color-mix(in srgb, var(--color-primary) 45%, var(--midground-base))",
    "--memory-node-plaud-fill": "color-mix(in srgb, var(--color-primary) 34%, var(--midground-base))",
    "--memory-node-plaud-halo": "color-mix(in srgb, var(--color-primary) 18%, transparent)",
    "--memory-node-asset": "color-mix(in srgb, var(--color-destructive) 64%, var(--midground-base))",
    "--memory-node-asset-fill": "color-mix(in srgb, var(--color-destructive) 50%, var(--midground-base))",
    "--memory-node-asset-halo": "color-mix(in srgb, var(--color-destructive) 20%, transparent)",
    "--memory-node-general": "color-mix(in srgb, var(--midground-base) 86%, var(--color-primary) 12%)",
    "--memory-node-general-fill": "color-mix(in srgb, var(--midground-base) 68%, var(--color-primary) 10%)",
    "--memory-node-general-halo": "color-mix(in srgb, var(--midground-base) 16%, transparent)",
  } as CSSProperties;

  if (!nodes.length) {
    return (
      <div
        className={cn(
          "flex min-h-[30rem] items-center justify-center rounded-lg border border-dashed border-border bg-background/30 px-6 text-center text-sm text-muted-foreground",
          className,
        )}
      >
        No memory graph nodes yet. Session facts and entities will appear after memory processing.
      </div>
    );
  }

  return (
    <div
      style={graphStyle}
      onClick={() => setSelectedNodeId(null)}
      className={cn(
        "memory-constellation relative isolate min-h-[34rem] overflow-hidden rounded-md border border-[var(--page-border)] bg-[var(--memory-bg)] text-foreground",
        compact && "min-h-[18rem]",
        className,
      )}
    >
      <p id={summaryId} className="sr-only">
        Memory knowledge graph with {nodes.length} nodes and {realLinks} links. Use Tab to inspect prominent nodes.
        Press Enter to pin a node and reveal its connected memories.
      </p>
      <svg
        ref={svgRef}
        aria-label="Memory knowledge graph"
        aria-describedby={summaryId}
        className="absolute inset-0 h-full w-full cursor-grab active:cursor-grabbing"
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={handlePointerUp}
        onWheel={handleWheel}
        preserveAspectRatio="xMidYMid meet"
        role="img"
        viewBox={(() => {
          const baseW = VIEW_WIDTH + Math.max(0, Math.sqrt(nodes.length) - 8) * 18;
          const baseH = VIEW_HEIGHT + Math.max(0, Math.sqrt(nodes.length) - 8) * 12;
          const w = baseW * zoom;
          const h = baseH * zoom;
          const cx = VIEW_X + baseW / 2 + pan.x;
          const cy = VIEW_Y + baseH / 2 + pan.y;
          return `${cx - w / 2} ${cy - h / 2} ${w} ${h}`;
        })()}
      >
        <defs>
          <pattern id={gridId} width="48" height="48" patternUnits="userSpaceOnUse">
            <path d="M 48 0 L 0 0 0 48" fill="none" stroke="var(--memory-grid)" strokeWidth="0.8" />
          </pattern>
          <radialGradient id={glowId} cx="50%" cy="44%" r="62%">
            <stop offset="0%" stopColor="var(--memory-panel-strong)" />
            <stop offset="58%" stopColor="var(--memory-panel)" />
            <stop offset="100%" stopColor="var(--memory-bg)" />
          </radialGradient>
        </defs>
        <rect x="-40" y="-40" width={WIDTH + 80} height={HEIGHT + 80} fill={`url(#${glowId})`} />
        <rect x="-40" y="-40" width={WIDTH + 80} height={HEIGHT + 80} fill={`url(#${gridId})`} opacity="0.3" />
        {!compact && (
          <g className="memory-constellation-hulls">
            {layout.hulls.map((hull) => (
              <polygon
                key={hull.key}
                points={hull.path}
                fill={NODE_TONE[hull.kind].halo}
                stroke={NODE_TONE[hull.kind].accent}
                strokeWidth="0.8"
                strokeDasharray="4 3"
                opacity="0.18"
              />
            ))}
          </g>
        )}
        <g>
          {layout.edges.map((edge, index) => {
            const source = layout.byId.get(edge.source);
            const target = layout.byId.get(edge.target);
            if (!source || !target) return null;
            const visual = edge.type === "visual-cluster";
            const connected = isEdgeConnected(edge, activeNodeId);
            const dormant = Boolean(activeNodeId && !connected);
            const prominent = !activeNodeId && !visual && index < 8;
            return (
              <g key={`${edge.source}-${edge.target}-${index}`}>
                <line
                  className={cn(
                    "memory-constellation-edge",
                    prominent && "memory-constellation-edge-flow",
                    connected && "memory-constellation-edge-active",
                  )}
                  x1={source.x}
                  x2={target.x}
                  y1={source.y}
                  y2={target.y}
                  opacity={dormant ? 0.06 : connected ? 0.9 : visual ? 0.14 : 0.38}
                  stroke={connected ? "var(--memory-edge-active)" : visual ? "var(--memory-edge-soft)" : "var(--memory-edge)"}
                  strokeLinecap="round"
                  strokeWidth={connected ? 1.8 : visual ? 0.6 : 0.9}
                  style={{ "--memory-edge-delay": `${index * 46}ms` } as CSSProperties}
                />
                {connected && edge.type !== "visual-cluster" && (
                  <text
                    x={(source.x + target.x) / 2}
                    y={(source.y + target.y) / 2 - 5}
                    className="memory-constellation-edge-label"
                    fill="var(--memory-edge-active)"
                    textAnchor="middle"
                  >
                    {edge.type.replace(/_/g, " ")}
                  </text>
                )}
              </g>
            );
          })}
        </g>
        <g>
          {layout.positioned.map((item, index) => {
            const { degree, kind, node, opacity, r, rank, x, y } = item;
            const tone = NODE_TONE[kind];
            const active = activeNodeId === node.id;
            const connected = activeConnections.has(node.id);
            const linked = Boolean(activeNodeId && connected && !active);
            const muted = Boolean(activeNodeId && !connected);
            const label = labelFor(node);
            const showLabel = !compact && (active || linked || rank < 18 || (kind === "community" && rank < 24));
            const labelLeft = x > WIDTH - 240;
            return (
              <g
                key={node.id}
                aria-label={`${tone.label}: ${label}. ${degree} link${degree === 1 ? "" : "s"}.`}
                aria-pressed={selectedNodeId === node.id}
                className={cn(
                  "memory-constellation-node",
                  active && "is-active",
                  linked && "is-linked",
                  selectedNodeId === node.id && "is-pinned",
                  muted && "is-muted",
                )}
                focusable="true"
                onBlur={() => setHoveredNodeId(null)}
                onClick={(event) => {
                  event.stopPropagation();
                  setSelectedNodeId((current) => (current === node.id ? null : node.id));
                }}
                onFocus={() => setHoveredNodeId(node.id)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" || event.key === " ") {
                    event.preventDefault();
                    setSelectedNodeId((current) => (current === node.id ? null : node.id));
                  }
                  if (event.key === "Escape") {
                    setSelectedNodeId(null);
                    setHoveredNodeId(null);
                  }
                }}
                onMouseEnter={() => setHoveredNodeId(node.id)}
                onMouseLeave={() => setHoveredNodeId(null)}
                role="button"
                style={{ "--memory-node-delay": `${Math.min(index, 30) * 32}ms` } as CSSProperties}
                tabIndex={0}
              >
                <circle
                  cx={x}
                  cy={y}
                  className="memory-constellation-halo"
                  fill={tone.halo}
                  r={r * (active ? 2.2 : linked ? 1.9 : 1.6)}
                />
                <circle
                  cx={x}
                  cy={y}
                  className="memory-constellation-ring"
                  fill="none"
                  r={r * 1.2}
                  stroke={tone.accent}
                  strokeWidth={active ? 1.8 : 0.85}
                />
                <circle
                  cx={x}
                  cy={y}
                  className="memory-constellation-core"
                  fill={tone.fill}
                  opacity={muted ? 0.42 : opacity}
                  r={active ? r + 1.5 : r}
                  stroke={tone.accent}
                  strokeWidth={active ? 2 : 1}
                />
                {showLabel && (
                  <text
                    x={labelLeft ? x - r - 7 : x + r + 7}
                    y={y + 4}
                    className="memory-constellation-label"
                    fill="var(--midground)"
                    textAnchor={labelLeft ? "end" : "start"}
                  >
                    {label.length > 26 ? `${label.slice(0, 26)}...` : label}
                  </text>
                )}
                <title>{node.label}</title>
              </g>
            );
          })}
        </g>
      </svg>

      <div className="pointer-events-none absolute inset-x-0 top-0 flex items-start justify-between gap-4 p-4">
        <div className="rounded-lg border border-border/60 bg-background/95 px-3 py-2 shadow-sm">
          <div className="text-xs font-semibold text-foreground">Knowledge graph</div>
          <div className="mt-1 text-[0.72rem] text-muted-foreground">
            {nodes.length} nodes / {displayedLinks} {activeNode ? "related" : "links"}
          </div>
        </div>
        <div className="hidden max-w-[54%] flex-wrap justify-end gap-1.5 sm:flex">
          {layout.groups.map((group) => (
            <Badge
              key={group.kind}
              variant="outline"
              className="border-border/60 bg-background/95 text-[0.68rem] text-muted-foreground shadow-sm"
            >
              <span
                aria-hidden="true"
                className="mr-1.5 inline-block h-1.5 w-1.5 rounded-full"
                style={{ background: NODE_TONE[group.kind].accent }}
              />
              {group.name} {group.total}
            </Badge>
          ))}
        </div>
      </div>

      {focusNode && (
        <div className="pointer-events-none absolute inset-x-4 bottom-4 flex flex-col gap-2 sm:max-w-[28rem]">
          <div className="w-fit rounded border border-border/60 bg-background/95 px-2 py-0.5 font-mono-ui text-[0.68rem] uppercase tracking-[0.06em] text-muted-foreground shadow-sm">
            {activeNode && selectedNodeId === activeNode.node.id ? "Pinned" : activeNode ? "Inspecting" : "Strongest signal"}
          </div>
          <div className="rounded-lg border border-border/70 bg-background/95 p-3 shadow-sm">
            <div className="flex items-center gap-2">
              <span
                aria-hidden="true"
                className="h-2.5 w-2.5 shrink-0 rounded-full"
                style={{ background: NODE_TONE[focusNode.kind].accent }}
              />
              <span className="text-xs font-semibold text-foreground">
                {NODE_TONE[focusNode.kind].label}
              </span>
              <span className="text-[0.7rem] text-muted-foreground">
                {focusNode.degree} link{focusNode.degree === 1 ? "" : "s"}
              </span>
            </div>
            <div className="mt-1 line-clamp-2 text-sm leading-5 text-foreground">
              {labelFor(focusNode.node)}
            </div>
            {activeEdgeTypes.length > 0 && (
              <div className="mt-2 flex flex-wrap gap-1.5">
                {activeEdgeTypes.map((edge) => (
                  <span
                    key={edge.type}
                    className="rounded-full border border-border/60 bg-background/60 px-2 py-0.5 text-[0.66rem] text-muted-foreground"
                  >
                    {edge.type} {edge.count}
                  </span>
                ))}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

```

---
## `src/components/ModelInfoCard.tsx`
```tsx
import { useEffect, useRef, useState } from "react";
import {
  Brain,
  Eye,
  Gauge,
  Lightbulb,
  Wrench,
  Loader2,
} from "lucide-react";
import { api } from "@/lib/api";
import type { ModelInfoResponse } from "@/lib/api";
import { formatTokenCount } from "@/lib/format";

interface ModelInfoCardProps {
  /** Current model string from config state — used to detect changes */
  currentModel: string;
  /** Bumped after config saves to trigger re-fetch */
  refreshKey?: number;
}

export function ModelInfoCard({ currentModel, refreshKey = 0 }: ModelInfoCardProps) {
  const [info, setInfo] = useState<ModelInfoResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const lastFetchKeyRef = useRef("");

  useEffect(() => {
    if (!currentModel) return;
    // Re-fetch when model changes OR when refreshKey bumps (after save)
    const fetchKey = `${currentModel}:${refreshKey}`;
    if (fetchKey === lastFetchKeyRef.current) return;
    lastFetchKeyRef.current = fetchKey;
    setLoading(true);
    api
      .getModelInfo()
      .then(setInfo)
      .catch(() => setInfo(null))
      .finally(() => setLoading(false));
  }, [currentModel, refreshKey]);

  if (loading) {
    return (
      <div className="flex items-center gap-2 py-2 text-xs text-muted-foreground">
        <Loader2 className="h-3 w-3 animate-spin" />
        Loading model info…
      </div>
    );
  }

  if (!info || !info.model || info.effective_context_length <= 0) return null;

  const caps = info.capabilities;
  const hasCaps = caps && Object.keys(caps).length > 0;

  return (
    <div className="space-y-2 rounded-md border border-border bg-card px-3 py-2.5">
      {/* Context window */}
      <div className="flex items-center gap-4 text-xs">
        <div className="flex items-center gap-1.5 text-muted-foreground">
          <Gauge className="h-3.5 w-3.5" />
          <span className="font-medium">Context Window</span>
        </div>
        <div className="flex items-center gap-2">
          <span className="font-mono font-semibold text-foreground">
            {formatTokenCount(info.effective_context_length)}
          </span>
          {info.config_context_length > 0 ? (
            <span className="text-[10px] text-[var(--color-warning)]/80">
              (override — auto: {formatTokenCount(info.auto_context_length)})
            </span>
          ) : (
            <span className="text-muted-foreground/60 text-[10px]">auto-detected</span>
          )}
        </div>
      </div>

      {/* Max output */}
      {hasCaps && caps.max_output_tokens && caps.max_output_tokens > 0 && (
        <div className="flex items-center gap-4 text-xs">
          <div className="flex items-center gap-1.5 text-muted-foreground">
            <Lightbulb className="h-3.5 w-3.5" />
            <span className="font-medium">Max Output</span>
          </div>
          <span className="font-mono font-semibold text-foreground">
            {formatTokenCount(caps.max_output_tokens)}
          </span>
        </div>
      )}

      {/* Capability badges */}
      {hasCaps && (
        <div className="flex flex-wrap items-center gap-1.5 pt-0.5">
          {caps.supports_tools && (
            <span className="inline-flex items-center gap-1 bg-[var(--color-success)]/10 px-2 py-0.5 text-[10px] font-medium text-[var(--color-success)]">
              <Wrench className="h-2.5 w-2.5" /> Tools
            </span>
          )}
          {caps.supports_vision && (
            <span className="inline-flex items-center gap-1 bg-muted px-2 py-0.5 text-[10px] font-medium text-muted-foreground">
              <Eye className="h-2.5 w-2.5" /> Vision
            </span>
          )}
          {caps.supports_reasoning && (
            <span className="inline-flex items-center gap-1 bg-muted px-2 py-0.5 text-[10px] font-medium text-muted-foreground">
              <Brain className="h-2.5 w-2.5" /> Reasoning
            </span>
          )}
          {caps.model_family && (
            <span className="inline-flex items-center gap-1 bg-muted px-2 py-0.5 text-[10px] font-medium text-muted-foreground">
              {caps.model_family}
            </span>
          )}
        </div>
      )}
    </div>
  );
}

```

---
## `src/components/ModelPickerDialog.tsx`
```tsx
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import type { GatewayClient } from "@/lib/gatewayClient";
import { Check, Loader2, Search, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

/**
 * Two-stage model picker modal.
 *
 * Mirrors ui-tui/src/components/modelPicker.tsx:
 *   Stage 1: pick provider (authenticated providers only)
 *   Stage 2: pick model within that provider
 *
 * On confirm, emits `/model <model> --provider <slug> [--global]` through
 * the parent callback so ChatPage can dispatch it via the existing slash
 * pipeline. That keeps persistence + actual switch logic in one place.
 */

interface ModelOptionProvider {
  name: string;
  slug: string;
  models?: string[];
  total_models?: number;
  is_current?: boolean;
  warning?: string;
}

interface ModelOptionsResponse {
  model?: string;
  provider?: string;
  providers?: ModelOptionProvider[];
}

interface Props {
  gw: GatewayClient;
  sessionId: string;
  onClose(): void;
  /** Parent runs the resulting slash command through slashExec. */
  onSubmit(slashCommand: string): void;
}

export function ModelPickerDialog({ gw, sessionId, onClose, onSubmit }: Props) {
  const [providers, setProviders] = useState<ModelOptionProvider[]>([]);
  const [currentModel, setCurrentModel] = useState("");
  const [currentProviderSlug, setCurrentProviderSlug] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedSlug, setSelectedSlug] = useState("");
  const [selectedModel, setSelectedModel] = useState("");
  const [query, setQuery] = useState("");
  const [persistGlobal, setPersistGlobal] = useState(false);
  const closedRef = useRef(false);

  // Load providers + models on open.
  useEffect(() => {
    closedRef.current = false;

    gw.request<ModelOptionsResponse>(
      "model.options",
      sessionId ? { session_id: sessionId } : {},
    )
      .then((r) => {
        if (closedRef.current) return;
        const next = r?.providers ?? [];
        setProviders(next);
        setCurrentModel(String(r?.model ?? ""));
        setCurrentProviderSlug(String(r?.provider ?? ""));
        setSelectedSlug(
          (next.find((p) => p.is_current) ?? next[0])?.slug ?? "",
        );
        setSelectedModel("");
        setLoading(false);
      })
      .catch((e) => {
        if (closedRef.current) return;
        setError(e instanceof Error ? e.message : String(e));
        setLoading(false);
      });

    return () => {
      closedRef.current = true;
    };
  }, [gw, sessionId]);

  // Esc closes.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        onClose();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const selectedProvider = useMemo(
    () => providers.find((p) => p.slug === selectedSlug) ?? null,
    [providers, selectedSlug],
  );

  const models = useMemo(
    () => selectedProvider?.models ?? [],
    [selectedProvider],
  );

  const needle = query.trim().toLowerCase();

  const filteredProviders = useMemo(
    () =>
      !needle
        ? providers
        : providers.filter(
            (p) =>
              p.name.toLowerCase().includes(needle) ||
              p.slug.toLowerCase().includes(needle) ||
              (p.models ?? []).some((m) => m.toLowerCase().includes(needle)),
          ),
    [providers, needle],
  );

  const filteredModels = useMemo(
    () =>
      !needle ? models : models.filter((m) => m.toLowerCase().includes(needle)),
    [models, needle],
  );

  const canConfirm = !!selectedProvider && !!selectedModel;

  const confirm = () => {
    if (!canConfirm) return;
    const global = persistGlobal ? " --global" : "";
    onSubmit(
      `/model ${selectedModel} --provider ${selectedProvider.slug}${global}`,
    );
    onClose();
  };

  return (
    <div
      className="fixed inset-0 z-[100] flex items-center justify-center bg-background/80 p-4"
      onClick={(e) => e.target === e.currentTarget && onClose()}
      role="dialog"
      aria-modal="true"
      aria-labelledby="model-picker-title"
    >
      <div className="relative flex max-h-[80vh] w-full max-w-3xl flex-col overflow-hidden rounded-md border border-border bg-card">
        <button
          type="button"
          onClick={onClose}
          className="absolute right-3 top-3 text-muted-foreground hover:text-foreground transition-colors cursor-pointer"
          aria-label="Close"
        >
          <X className="h-5 w-5" />
        </button>

        <header className="border-b border-border p-5 pb-3">
          <h2
            id="model-picker-title"
            className="font-display text-base font-semibold tracking-normal normal-case"
          >
            Switch Model
          </h2>
          <p className="mt-1 text-xs text-muted-foreground">
            current: {currentModel || "(unknown)"}
            {currentProviderSlug && ` · ${currentProviderSlug}`}
          </p>
        </header>

        <div className="border-b border-border px-5 pb-2 pt-3">
          <div className="relative">
            <Search className="absolute left-2 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
            <Input
              autoFocus
              placeholder="Filter providers and models…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              className="pl-7 h-8 text-sm"
            />
          </div>
        </div>

        <div className="flex-1 min-h-0 grid grid-cols-[200px_1fr] overflow-hidden">
          <ProviderColumn
            loading={loading}
            error={error}
            providers={filteredProviders}
            total={providers.length}
            selectedSlug={selectedSlug}
            query={needle}
            onSelect={(slug) => {
              setSelectedSlug(slug);
              setSelectedModel("");
            }}
          />

          <ModelColumn
            provider={selectedProvider}
            models={filteredModels}
            allModels={models}
            selectedModel={selectedModel}
            currentModel={currentModel}
            currentProviderSlug={currentProviderSlug}
            onSelect={setSelectedModel}
            onConfirm={(m) => {
              setSelectedModel(m);
              // Confirm on next tick so state settles.
              window.setTimeout(confirm, 0);
            }}
          />
        </div>

        <footer className="border-t border-border p-3 flex items-center justify-between gap-3 flex-wrap">
          <label className="flex items-center gap-2 text-xs text-muted-foreground cursor-pointer select-none">
            <input
              type="checkbox"
              checked={persistGlobal}
              onChange={(e) => setPersistGlobal(e.target.checked)}
              className="cursor-pointer"
            />
            Persist globally (otherwise this session only)
          </label>

          <div className="flex items-center gap-2 ml-auto">
            <Button variant="ghost" size="sm" onClick={onClose}>
              Cancel
            </Button>
            <Button size="sm" onClick={confirm} disabled={!canConfirm}>
              Switch
            </Button>
          </div>
        </footer>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Provider column                                                    */
/* ------------------------------------------------------------------ */

function ProviderColumn({
  loading,
  error,
  providers,
  total,
  selectedSlug,
  query,
  onSelect,
}: {
  loading: boolean;
  error: string | null;
  providers: ModelOptionProvider[];
  total: number;
  selectedSlug: string;
  query: string;
  onSelect(slug: string): void;
}) {
  return (
    <div className="border-r border-border overflow-y-auto">
      {loading && (
        <div className="flex items-center gap-2 p-4 text-xs text-muted-foreground">
          <Loader2 className="h-3 w-3 animate-spin" /> loading…
        </div>
      )}

      {error && <div className="p-4 text-xs text-destructive">{error}</div>}

      {!loading && !error && providers.length === 0 && (
        <div className="p-4 text-xs text-muted-foreground italic">
          {query
            ? "no matches"
            : total === 0
              ? "no authenticated providers"
              : "no matches"}
        </div>
      )}

      {providers.map((p) => {
        const active = p.slug === selectedSlug;
        return (
          <button
            key={p.slug}
            type="button"
            onClick={() => onSelect(p.slug)}
            className={`w-full text-left px-3 py-2 text-xs transition-colors cursor-pointer flex items-start gap-2 ${
              active
                ? "bg-muted text-foreground"
                : "text-muted-foreground hover:text-foreground hover:bg-muted/40"
            }`}
          >
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-1.5">
                <span className="font-medium truncate">{p.name}</span>
                {p.is_current && <CurrentTag />}
              </div>
              <div className="text-[0.65rem] text-muted-foreground/80 font-mono truncate">
                {p.slug} · {p.total_models ?? p.models?.length ?? 0} models
              </div>
            </div>
          </button>
        );
      })}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Model column                                                       */
/* ------------------------------------------------------------------ */

function ModelColumn({
  provider,
  models,
  allModels,
  selectedModel,
  currentModel,
  currentProviderSlug,
  onSelect,
  onConfirm,
}: {
  provider: ModelOptionProvider | null;
  models: string[];
  allModels: string[];
  selectedModel: string;
  currentModel: string;
  currentProviderSlug: string;
  onSelect(model: string): void;
  onConfirm(model: string): void;
}) {
  if (!provider) {
    return (
      <div className="overflow-y-auto">
        <div className="p-4 text-xs text-muted-foreground italic">
          pick a provider →
        </div>
      </div>
    );
  }

  return (
    <div className="overflow-y-auto">
      {provider.warning && (
        <div className="p-3 text-xs text-destructive border-b border-border">
          {provider.warning}
        </div>
      )}

      {models.length === 0 ? (
        <div className="p-4 text-xs text-muted-foreground italic">
          {allModels.length
            ? "no models match your filter"
            : "no models listed for this provider"}
        </div>
      ) : (
        models.map((m) => {
          const active = m === selectedModel;
          const isCurrent =
            m === currentModel && provider.slug === currentProviderSlug;

          return (
            <button
              key={m}
              type="button"
              onClick={() => onSelect(m)}
              onDoubleClick={() => onConfirm(m)}
              className={`w-full text-left px-3 py-1.5 text-xs font-mono transition-colors cursor-pointer flex items-center gap-2 ${
                active
                  ? "bg-muted text-foreground"
                  : "text-muted-foreground hover:text-foreground hover:bg-muted/40"
              }`}
            >
              <Check
                className={`h-3 w-3 shrink-0 ${active ? "text-primary" : "text-transparent"}`}
              />
              <span className="flex-1 truncate">{m}</span>
              {isCurrent && <CurrentTag />}
            </button>
          );
        })
      )}
    </div>
  );
}

function CurrentTag() {
  return (
    <span className="shrink-0 text-[0.68rem] font-medium tracking-normal text-primary/80">
      current
    </span>
  );
}

```

---
## `src/components/OAuthLoginModal.tsx`
```tsx
import { useEffect, useRef, useState } from "react";
import { ExternalLink, Copy, X, Check, Loader2 } from "lucide-react";
import { H2 } from "@nous-research/ui/ui/components/typography/h2";
import { api, type OAuthProvider, type OAuthStartResponse } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useI18n } from "@/i18n";

interface Props {
  provider: OAuthProvider;
  onClose: () => void;
  onSuccess: (msg: string) => void;
  onError: (msg: string) => void;
}

type Phase =
  | "idle"
  | "starting"
  | "awaiting_user"
  | "submitting"
  | "polling"
  | "approved"
  | "error";

export function OAuthLoginModal({
  provider,
  onClose,
  onSuccess,
  onError,
}: Props) {
  const [phase, setPhase] = useState<Phase>("starting");
  const [start, setStart] = useState<OAuthStartResponse | null>(null);
  const [pkceCode, setPkceCode] = useState("");
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [secondsLeft, setSecondsLeft] = useState<number | null>(null);
  const [codeCopied, setCodeCopied] = useState(false);
  const isMounted = useRef(true);
  const pollTimer = useRef<number | null>(null);
  const { t } = useI18n();

  // Initiate flow on mount
  useEffect(() => {
    isMounted.current = true;
    api
      .startOAuthLogin(provider.id)
      .then((resp) => {
        if (!isMounted.current) return;
        setStart(resp);
        setSecondsLeft(resp.expires_in);
        setPhase(resp.flow === "device_code" ? "polling" : "awaiting_user");
        if (resp.flow === "pkce") {
          window.open(resp.auth_url, "_blank", "noopener,noreferrer");
        } else {
          window.open(resp.verification_url, "_blank", "noopener,noreferrer");
        }
      })
      .catch((e) => {
        if (!isMounted.current) return;
        setPhase("error");
        setErrorMsg(`Failed to start login: ${e}`);
      });
    return () => {
      isMounted.current = false;
      if (pollTimer.current !== null) window.clearInterval(pollTimer.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Tick the countdown
  useEffect(() => {
    if (secondsLeft === null) return;
    if (phase === "approved" || phase === "error") return;
    const tick = window.setInterval(() => {
      if (!isMounted.current) return;
      setSecondsLeft((s) => {
        if (s !== null && s <= 1) {
          setPhase("error");
          setErrorMsg(t.oauth.sessionExpired);
          return 0;
        }
        return s !== null && s > 0 ? s - 1 : 0;
      });
    }, 1000);
    return () => window.clearInterval(tick);
  }, [secondsLeft, phase, t]);

  // Device-code: poll backend every 2s
  useEffect(() => {
    if (!start || start.flow !== "device_code" || phase !== "polling") return;
    const sid = start.session_id;
    pollTimer.current = window.setInterval(async () => {
      try {
        const resp = await api.pollOAuthSession(provider.id, sid);
        if (!isMounted.current) return;
        if (resp.status === "approved") {
          setPhase("approved");
          if (pollTimer.current !== null)
            window.clearInterval(pollTimer.current);
          onSuccess(`${provider.name} connected`);
          window.setTimeout(() => isMounted.current && onClose(), 1500);
        } else if (resp.status !== "pending") {
          setPhase("error");
          setErrorMsg(resp.error_message || `Login ${resp.status}`);
          if (pollTimer.current !== null)
            window.clearInterval(pollTimer.current);
        }
      } catch (e) {
        if (!isMounted.current) return;
        setPhase("error");
        setErrorMsg(`Polling failed: ${e}`);
        if (pollTimer.current !== null) window.clearInterval(pollTimer.current);
      }
    }, 2000);
    return () => {
      if (pollTimer.current !== null) window.clearInterval(pollTimer.current);
    };
  }, [start, phase, provider.id, provider.name, onSuccess, onClose]);

  const handleSubmitPkceCode = async () => {
    if (!start || start.flow !== "pkce") return;
    if (!pkceCode.trim()) return;
    setPhase("submitting");
    setErrorMsg(null);
    try {
      const resp = await api.submitOAuthCode(
        provider.id,
        start.session_id,
        pkceCode.trim(),
      );
      if (!isMounted.current) return;
      if (resp.ok && resp.status === "approved") {
        setPhase("approved");
        onSuccess(`${provider.name} connected`);
        window.setTimeout(() => isMounted.current && onClose(), 1500);
      } else {
        setPhase("error");
        setErrorMsg(resp.message || "Token exchange failed");
      }
    } catch (e) {
      if (!isMounted.current) return;
      setPhase("error");
      setErrorMsg(`Submit failed: ${e}`);
    }
  };

  const handleClose = async () => {
    if (start && phase !== "approved" && phase !== "error") {
      try {
        await api.cancelOAuthSession(start.session_id);
      } catch {
        // ignore
      }
    }
    onClose();
  };

  const handleCopyUserCode = async (code: string) => {
    try {
      await navigator.clipboard.writeText(code);
      setCodeCopied(true);
      window.setTimeout(() => isMounted.current && setCodeCopied(false), 1500);
    } catch {
      onError("Clipboard write failed");
    }
  };

  const handleBackdrop = (e: React.MouseEvent) => {
    if (e.target === e.currentTarget) handleClose();
  };

  const fmtTime = (s: number | null) => {
    if (s === null) return "";
    const m = Math.floor(s / 60);
    const r = s % 60;
    return `${m}:${String(r).padStart(2, "0")}`;
  };

  return (
    <div
      className="fixed inset-0 z-[100] flex items-center justify-center bg-background/80 p-4"
      onClick={handleBackdrop}
      role="dialog"
      aria-modal="true"
      aria-labelledby="oauth-modal-title"
    >
      <div className="relative w-full max-w-md overflow-hidden rounded-md border border-border bg-card">
        <button
          type="button"
          onClick={handleClose}
          className="absolute right-3 top-3 text-muted-foreground hover:text-foreground transition-colors"
          aria-label={t.common.close}
        >
          <X className="h-5 w-5" />
        </button>
        <div className="p-6 flex flex-col gap-4">
          <div>
            <H2
              id="oauth-modal-title"
              variant="sm"
              mondwest
              className="tracking-normal normal-case"
            >
              {t.oauth.connect} {provider.name}
            </H2>
            {secondsLeft !== null &&
              phase !== "approved" &&
              phase !== "error" && (
                <p className="text-xs text-muted-foreground mt-1">
                  {t.oauth.sessionExpires.replace(
                    "{time}",
                    fmtTime(secondsLeft),
                  )}
                </p>
              )}
          </div>

          {/* ── starting ───────────────────────────────────── */}
          {phase === "starting" && (
            <div className="flex items-center gap-3 py-6 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" />
              {t.oauth.initiatingLogin}
            </div>
          )}

          {/* ── PKCE: paste code ───────────────────────────── */}
          {start?.flow === "pkce" && phase === "awaiting_user" && (
            <>
              <ol className="text-sm space-y-2 list-decimal list-inside text-muted-foreground">
                <li>{t.oauth.pkceStep1}</li>
                <li>{t.oauth.pkceStep2}</li>
                <li>{t.oauth.pkceStep3}</li>
              </ol>
              <div className="flex flex-col gap-2">
                <Input
                  value={pkceCode}
                  onChange={(e) => setPkceCode(e.target.value)}
                  placeholder={t.oauth.pasteCode}
                  onKeyDown={(e) => e.key === "Enter" && handleSubmitPkceCode()}
                  autoFocus
                />
                <div className="flex items-center gap-2 justify-between">
                  <a
                    href={
                      (start as Extract<OAuthStartResponse, { flow: "pkce" }>)
                        .auth_url
                    }
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-xs text-muted-foreground hover:text-foreground inline-flex items-center gap-1"
                  >
                    <ExternalLink className="h-3 w-3" />
                    {t.oauth.reOpenAuth}
                  </a>
                  <Button
                    onClick={handleSubmitPkceCode}
                    disabled={!pkceCode.trim()}
                    size="sm"
                  >
                    {t.oauth.submitCode}
                  </Button>
                </div>
              </div>
            </>
          )}

          {/* ── PKCE: submitting exchange ──────────────────── */}
          {phase === "submitting" && (
            <div className="flex items-center gap-3 py-6 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" />
              {t.oauth.exchangingCode}
            </div>
          )}

          {/* ── Device code: show code + URL, polling ──────── */}
          {start?.flow === "device_code" && phase === "polling" && (
            <>
              <p className="text-sm text-muted-foreground">
                {t.oauth.enterCodePrompt}
              </p>
              <div className="flex items-center justify-between gap-2 border border-border bg-secondary/30 p-4">
                <code className="font-mono-ui text-2xl tracking-widest text-foreground">
                  {
                    (
                      start as Extract<
                        OAuthStartResponse,
                        { flow: "device_code" }
                      >
                    ).user_code
                  }
                </code>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() =>
                    handleCopyUserCode(
                      (
                        start as Extract<
                          OAuthStartResponse,
                          { flow: "device_code" }
                        >
                      ).user_code,
                    )
                  }
                  className="text-xs"
                >
                  {codeCopied ? (
                    <Check className="h-3 w-3" />
                  ) : (
                    <Copy className="h-3 w-3" />
                  )}
                </Button>
              </div>
              <a
                href={
                  (
                    start as Extract<
                      OAuthStartResponse,
                      { flow: "device_code" }
                    >
                  ).verification_url
                }
                target="_blank"
                rel="noopener noreferrer"
                className="text-xs text-muted-foreground hover:text-foreground inline-flex items-center gap-1"
              >
                <ExternalLink className="h-3 w-3" />
                {t.oauth.reOpenVerification}
              </a>
              <div className="flex items-center gap-2 text-xs text-muted-foreground border-t border-border pt-3">
                <Loader2 className="h-3 w-3 animate-spin" />
                {t.oauth.waitingAuth}
              </div>
            </>
          )}

          {/* ── approved ───────────────────────────────────── */}
          {phase === "approved" && (
            <div className="flex items-center gap-3 py-6 text-sm text-success">
              <Check className="h-5 w-5" />
              {t.oauth.connectedClosing}
            </div>
          )}

          {/* ── error ──────────────────────────────────────── */}
          {phase === "error" && (
            <>
              <div className="rounded-md border border-border bg-card p-3 text-sm text-destructive">
                {errorMsg || t.oauth.loginFailed}
              </div>
              <div className="flex justify-end gap-2">
                <Button variant="outline" size="sm" onClick={handleClose}>
                  {t.common.close}
                </Button>
                <Button
                  size="sm"
                  onClick={() => {
                    if (start?.session_id) {
                      api.cancelOAuthSession(start.session_id).catch(() => {});
                    }
                    setErrorMsg(null);
                    setStart(null);
                    setPkceCode("");
                    setPhase("starting");
                    api
                      .startOAuthLogin(provider.id)
                      .then((resp) => {
                        if (!isMounted.current) return;
                        setStart(resp);
                        setSecondsLeft(resp.expires_in);
                        setPhase(
                          resp.flow === "device_code"
                            ? "polling"
                            : "awaiting_user",
                        );
                        if (resp.flow === "pkce") {
                          window.open(
                            resp.auth_url,
                            "_blank",
                            "noopener,noreferrer",
                          );
                        } else {
                          window.open(
                            resp.verification_url,
                            "_blank",
                            "noopener,noreferrer",
                          );
                        }
                      })
                      .catch((e) => {
                        if (!isMounted.current) return;
                        setPhase("error");
                        setErrorMsg(`${t.common.retry} failed: ${e}`);
                      });
                  }}
                >
                  {t.common.retry}
                </Button>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

```

---
## `src/components/OAuthProvidersCard.tsx`
```tsx
import { useEffect, useState, useCallback, useRef } from "react";
import { ShieldCheck, ShieldOff, Copy, ExternalLink, RefreshCw, LogOut, Terminal, LogIn } from "lucide-react";
import { api, type OAuthProvider } from "@/lib/api";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { OAuthLoginModal } from "@/components/OAuthLoginModal";
import { useI18n } from "@/i18n";

interface Props {
  onError?: (msg: string) => void;
  onSuccess?: (msg: string) => void;
}

function formatExpiresAt(expiresAt: string | null | undefined, expiresInTemplate: string): string | null {
  if (!expiresAt) return null;
  try {
    const dt = new Date(expiresAt);
    if (Number.isNaN(dt.getTime())) return null;
    const now = Date.now();
    const diff = dt.getTime() - now;
    if (diff < 0) return "expired";
    const mins = Math.floor(diff / 60_000);
    if (mins < 60) return expiresInTemplate.replace("{time}", `${mins}m`);
    const hours = Math.floor(mins / 60);
    if (hours < 24) return expiresInTemplate.replace("{time}", `${hours}h`);
    const days = Math.floor(hours / 24);
    return expiresInTemplate.replace("{time}", `${days}d`);
  } catch {
    return null;
  }
}

export function OAuthProvidersCard({ onError, onSuccess }: Props) {
  const [providers, setProviders] = useState<OAuthProvider[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const [loginFor, setLoginFor] = useState<OAuthProvider | null>(null);
  const { t } = useI18n();

  const onErrorRef = useRef(onError);
  onErrorRef.current = onError;

  const refresh = useCallback(() => {
    setLoading(true);
    api
      .getOAuthProviders()
      .then((resp) => setProviders(resp.providers))
      .catch((e) => onErrorRef.current?.(`Failed to load providers: ${e}`))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const handleCopy = async (provider: OAuthProvider) => {
    try {
      await navigator.clipboard.writeText(provider.cli_command);
      setCopiedId(provider.id);
      onSuccess?.(`Copied: ${provider.cli_command}`);
      setTimeout(() => setCopiedId((v) => (v === provider.id ? null : v)), 1500);
    } catch {
      onError?.("Clipboard write failed — copy the command manually");
    }
  };

  const handleDisconnect = async (provider: OAuthProvider) => {
    if (!confirm(`${t.oauth.disconnect} ${provider.name}?`)) {
      return;
    }
    setBusyId(provider.id);
    try {
      await api.disconnectOAuthProvider(provider.id);
      onSuccess?.(`${provider.name} ${t.oauth.disconnect.toLowerCase()}ed`);
      refresh();
    } catch (e) {
      onError?.(`${t.oauth.disconnect} failed: ${e}`);
    } finally {
      setBusyId(null);
    }
  };

  const connectedCount = providers?.filter((p) => p.status.logged_in).length ?? 0;
  const totalCount = providers?.length ?? 0;

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <ShieldCheck className="h-5 w-5 text-muted-foreground" />
            <CardTitle className="text-base">{t.oauth.providerLogins}</CardTitle>
          </div>
          <Button
            variant="ghost"
            size="sm"
            onClick={refresh}
            disabled={loading}
            className="text-xs"
          >
            <RefreshCw className={`h-3 w-3 mr-1 ${loading ? "animate-spin" : ""}`} />
            {t.common.refresh}
          </Button>
        </div>
        <CardDescription>
          {t.oauth.description.replace("{connected}", String(connectedCount)).replace("{total}", String(totalCount))}
        </CardDescription>
      </CardHeader>
      <CardContent>
        {loading && providers === null && (
          <div className="flex items-center justify-center py-8">
            <div className="h-5 w-5 animate-spin rounded-full border-2 border-primary border-t-transparent" />
          </div>
        )}
        {providers && providers.length === 0 && (
          <p className="px-1 py-1 text-xs text-muted-foreground/80">
            {t.oauth.noProviders}
          </p>
        )}
        <div className="flex flex-col divide-y divide-border">
          {providers?.map((p) => {
            const expiresLabel = formatExpiresAt(p.status.expires_at, t.oauth.expiresIn);
            const isBusy = busyId === p.id;
            const isExpired = expiresLabel === "expired";
            // Show Login on every non-external row so the user can swap
            // accounts or refresh credentials without first disconnecting.
            // External-CLI providers (Qwen) still can't take a Login click
            // (they need the third-party tool to run), so they stay hidden.
            const showLoginButton = p.flow !== "external";
            const loginLabel = !p.status.logged_in
              ? t.oauth.login
              : isExpired
                ? "Re-login"
                : "Switch account";
            return (
              <div
                key={p.id}
                className="flex items-center justify-between gap-4 py-3"
              >
                {/* Left: status icon + name + source */}
                <div className="flex items-start gap-3 min-w-0 flex-1">
                  {p.status.logged_in ? (
                    <ShieldCheck className="h-5 w-5 text-success shrink-0 mt-0.5" />
                  ) : (
                    <ShieldOff className="h-5 w-5 text-muted-foreground shrink-0 mt-0.5" />
                  )}
                  <div className="flex flex-col min-w-0 gap-0.5">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="font-medium text-sm">{p.name}</span>
                      <Badge variant="outline" className="text-[11px] tracking-normal normal-case">
                        {t.oauth.flowLabels[p.flow]}
                      </Badge>
                      {p.status.logged_in && (
                        <Badge variant="success" className="text-[11px]">
                          {t.oauth.connected}
                        </Badge>
                      )}
                      {expiresLabel === "expired" && (
                        <Badge variant="destructive" className="text-[11px]">
                          {t.oauth.expired}
                        </Badge>
                      )}
                      {expiresLabel && expiresLabel !== "expired" && (
                        <Badge variant="outline" className="text-[11px]">
                          {expiresLabel}
                        </Badge>
                      )}
                    </div>
                    {p.status.logged_in && p.status.token_preview && (
                      <code className="text-xs font-mono-ui truncate !bg-transparent !p-0 text-muted-foreground/80">
                        <span className="opacity-70">token{" "}</span>
                        {p.status.token_preview}
                        {p.status.source_label && (
                          <span className="opacity-60">
                            {" "}· {p.status.source_label}
                          </span>
                        )}
                      </code>
                    )}
                    {!p.status.logged_in && (
                      <span className="text-xs text-muted-foreground/80">
                        {t.oauth.notConnected.split("{command}")[0]}
                        <code className="text-foreground bg-secondary/40 px-1">
                          {p.cli_command}
                        </code>
                        {t.oauth.notConnected.split("{command}")[1]}
                      </span>
                    )}
                    {p.status.error && (
                      <span className="text-xs text-destructive">
                        {p.status.error}
                      </span>
                    )}
                  </div>
                </div>
                {/* Right: action buttons */}
                <div className="flex items-center gap-1.5 shrink-0">
                  {p.docs_url && (
                    <a
                      href={p.docs_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="inline-flex"
                      title={`Open ${p.name} docs`}
                    >
                      <Button variant="ghost" size="sm" className="h-7 w-7 p-0">
                        <ExternalLink className="h-3.5 w-3.5" />
                      </Button>
                    </a>
                  )}
                  {showLoginButton && (
                    <Button
                      variant="default"
                      size="sm"
                      onClick={() => setLoginFor(p)}
                      className="text-xs h-7"
                    >
                      <LogIn className="h-3 w-3 mr-1" />
                      {loginLabel}
                    </Button>
                  )}
                  {!p.status.logged_in && (
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => handleCopy(p)}
                      className="text-xs h-7"
                      title={t.oauth.copyCliCommand}
                    >
                      {copiedId === p.id ? (
                        <>{t.oauth.copied}</>
                      ) : (
                        <>
                          <Copy className="h-3 w-3 mr-1" />
                          {t.oauth.cli}
                        </>
                      )}
                    </Button>
                  )}
                  {p.status.logged_in && p.flow !== "external" && (
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => handleDisconnect(p)}
                      disabled={isBusy}
                      className="text-xs h-7"
                    >
                      {isBusy ? (
                        <RefreshCw className="h-3 w-3 mr-1 animate-spin" />
                      ) : (
                        <LogOut className="h-3 w-3 mr-1" />
                      )}
                      {t.oauth.disconnect}
                    </Button>
                  )}
                  {p.status.logged_in && p.flow === "external" && (
                    <span className="text-[11px] text-muted-foreground italic px-2">
                      <Terminal className="h-3 w-3 inline mr-0.5" />
                      {t.oauth.managedExternally}
                    </span>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </CardContent>
      {loginFor && (
        <OAuthLoginModal
          provider={loginFor}
          onClose={() => {
            setLoginFor(null);
            refresh();
          }}
          onSuccess={(msg) => onSuccess?.(msg)}
          onError={(msg) => onError?.(msg)}
        />
      )}
    </Card>
  );
}

```

---
## `src/components/PlatformsCard.tsx`
```tsx
import { AlertTriangle, Radio, Wifi, WifiOff } from "lucide-react";
import type { PlatformStatus } from "@/lib/api";
import { isoTimeAgo } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useI18n } from "@/i18n";

export function PlatformsCard({ platforms }: PlatformsCardProps) {
  const { t } = useI18n();
  const platformStateBadge: Record<
    string,
    { variant: "success" | "warning" | "destructive"; label: string }
  > = {
    connected: { variant: "success", label: t.status.connected },
    disconnected: { variant: "warning", label: t.status.disconnected },
    fatal: { variant: "destructive", label: t.status.error },
  };

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center gap-2">
          <Radio className="h-5 w-5 text-muted-foreground" />
          <CardTitle className="text-base">
            {t.status.connectedPlatforms}
          </CardTitle>
        </div>
      </CardHeader>

      <CardContent className="grid gap-3">
        {platforms.map(([name, info]) => {
          const display = platformStateBadge[info.state] ?? {
            variant: "outline" as const,
            label: info.state,
          };
          const IconComponent =
            info.state === "connected"
              ? Wifi
              : info.state === "fatal"
                ? AlertTriangle
                : WifiOff;

          return (
            <div
              key={name}
              className="flex w-full flex-col gap-2 rounded-md border border-border p-3 sm:flex-row sm:items-center sm:justify-between"
            >
              <div className="flex items-center gap-3 min-w-0 w-full">
                <IconComponent
                  className={`h-4 w-4 shrink-0 ${
                    info.state === "connected"
                      ? "text-success"
                      : info.state === "fatal"
                        ? "text-destructive"
                        : "text-warning"
                  }`}
                />

                <div className="flex flex-col gap-0.5 min-w-0">
                  <span className="text-sm font-medium capitalize truncate">
                    {name}
                  </span>

                  {info.error_message && (
                    <span className="text-xs text-destructive">
                      {info.error_message}
                    </span>
                  )}

                  {info.updated_at && (
                    <span className="text-xs text-muted-foreground">
                      {t.status.lastUpdate}: {isoTimeAgo(info.updated_at)}
                    </span>
                  )}
                </div>
              </div>

              <Badge
                variant={display.variant}
                className="shrink-0 self-start sm:self-center"
              >
                {display.variant === "success" && (
                  <span className="mr-1 inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-current" />
                )}
                {display.label}
              </Badge>
            </div>
          );
        })}
      </CardContent>
    </Card>
  );
}

interface PlatformsCardProps {
  platforms: [string, PlatformStatus][];
}

```

---
## `src/components/SidebarFooter.tsx`
```tsx
import { Typography } from "@nous-research/ui/ui/components/typography/index";
import { useSidebarStatus } from "@/hooks/useSidebarStatus";
import { cn } from "@/lib/utils";
import { useI18n } from "@/i18n";

export function SidebarFooter() {
  const status = useSidebarStatus();
  const { t } = useI18n();

  return (
    <div
      className={cn(
        "flex shrink-0 items-center justify-between gap-2",
        "px-3 py-2 lg:px-2 lg:py-1.5",
      )}
    >
      <Typography
        mondwest
        className="font-mono-ui text-[0.78rem] tabular-nums tracking-[0.06em] text-[var(--sidebar-text-muted)] lg:text-[0.72rem]"
      >
        {status?.version != null ? `v${status.version}` : "—"}
      </Typography>

      <a
        href="https://github.com/Dartagnan98/elevate-agent"
        target="_blank"
        rel="noopener noreferrer"
        className={cn(
          "font-mondwest text-[0.76rem] tracking-[0.08em] text-[var(--sidebar-text-strong)] lg:text-[0.7rem]",
          "transition-opacity hover:opacity-90",
          "focus-visible:rounded-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-midground/40",
        )}
      >
        {t.app.footer.org}
      </a>
    </div>
  );
}

```

---
## `src/components/SidebarStatusStrip.tsx`
```tsx
import { Link } from "react-router-dom";
import type { StatusResponse } from "@/lib/api";
import { useSidebarStatus } from "@/hooks/useSidebarStatus";
import { cn } from "@/lib/utils";
import { useI18n } from "@/i18n";
import { isDashboardEmbeddedChatEnabled } from "@/lib/dashboard-flags";

/** Gateway + session summary for the System sidebar block (no separate strip chrome). */
export function SidebarStatusStrip() {
  const status = useSidebarStatus();
  const { t } = useI18n();

  if (status === null) {
    return (
      <div className="px-5 py-1.5" aria-hidden>
        <div className="h-2 w-[80%] max-w-full animate-pulse rounded-sm bg-midground/10" />
      </div>
    );
  }

  const gw = gatewayLine(status, t);
  const { activeSessionsLabel, gatewayStatusLabel } = t.app;
  const overviewPath = isDashboardEmbeddedChatEnabled() ? "/chat" : "/tasks";

  return (
    <Link
      to={overviewPath}
      title={t.app.statusOverview}
      className={cn(
        "flex min-h-11 items-center text-left lg:min-h-0",
        "px-5 pb-2 pt-1 lg:px-4 lg:pb-1 lg:pt-0.5",
        "text-[var(--sidebar-text-muted)]",
        "transition-colors hover:text-[var(--sidebar-text)]",
        "focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-midground/40",
        "focus-visible:ring-inset",
      )}
    >
      <div className="flex flex-col gap-1 font-mondwest text-[0.72rem] leading-snug tracking-[0.06em] lg:gap-0.5 lg:text-[0.68rem]">
        <p className="break-words">
          <span className="text-[var(--sidebar-text-faint)]">{gatewayStatusLabel}</span>{" "}
          <span className={cn("font-medium", gw.tone)}>{gw.label}</span>
        </p>

        <p className="break-words">
          <span className="text-[var(--sidebar-text-faint)]">{activeSessionsLabel}</span>{" "}
          <span className="tabular-nums text-[var(--sidebar-text-muted)]">
            {status.active_sessions}
          </span>
        </p>
      </div>
    </Link>
  );
}

function gatewayLine(
  status: StatusResponse,
  t: ReturnType<typeof useI18n>["t"],
): { label: string; tone: string } {
  const g = t.app.gatewayStrip;
  const byState: Record<string, { label: string; tone: string }> = {
    running: { label: g.running, tone: "text-success" },
    starting: { label: g.starting, tone: "text-warning" },
    startup_failed: { label: g.failed, tone: "text-destructive" },
    stopped: { label: g.stopped, tone: "text-[var(--sidebar-text-muted)]" },
  };
  if (status.gateway_state && byState[status.gateway_state]) {
    return byState[status.gateway_state];
  }
  return status.gateway_running
    ? { label: g.running, tone: "text-success" }
    : { label: g.off, tone: "text-[var(--sidebar-text-muted)]" };
}

```

---
## `src/components/SidebarUserPill.tsx`
```tsx
import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ChevronUp, LogOut, Settings, Sparkles, User } from "lucide-react";
import { api } from "@/lib/api";
import type { LicenseStatusResponse } from "@/lib/api-types";
import { cn } from "@/lib/utils";
import { ThemeSwitcher } from "@/components/ThemeSwitcher";
import { LanguageSwitcher } from "@/components/LanguageSwitcher";

export function SidebarUserPill() {
  const navigate = useNavigate();
  const [license, setLicense] = useState<LicenseStatusResponse | null>(null);
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  const load = useCallback(() => {
    api.getLicenseStatus().then(setLicense).catch(() => setLicense(null));
  }, []);

  useEffect(() => { load(); }, [load]);

  useEffect(() => {
    const handler = () => load();
    window.addEventListener("elevate:auth-changed", handler);
    return () => window.removeEventListener("elevate:auth-changed", handler);
  }, [load]);

  // Re-poll license state when the user looks back at the window or the tab
  // becomes visible again. The CLI gateway can clear ~/.elevate/license.json
  // out from under us (refresh token rejected, explicit logout from another
  // surface) and without this listener the pill would keep rendering a stale
  // "signed in as foo@bar" until the next manual reload.
  useEffect(() => {
    const onVisible = () => {
      if (document.visibilityState === "visible") load();
    };
    document.addEventListener("visibilitychange", onVisible);
    window.addEventListener("focus", load);
    const tick = window.setInterval(load, 30_000);
    return () => {
      document.removeEventListener("visibilitychange", onVisible);
      window.removeEventListener("focus", load);
      window.clearInterval(tick);
    };
  }, [load]);

  useEffect(() => {
    if (!open) return;
    const handleClick = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", handleClick);
    document.addEventListener("keydown", handleKey);
    return () => {
      document.removeEventListener("mousedown", handleClick);
      document.removeEventListener("keydown", handleKey);
    };
  }, [open]);

  const handleSignOut = async () => {
    try {
      await api.logoutLicense();
      window.dispatchEvent(new Event("elevate:auth-changed"));
    } catch { /* ignore */ }
    setOpen(false);
  };

  const emailLabel = license?.authenticated
    ? license.email ?? "Signed in"
    : "Not signed in";

  const tierLabel = license?.authenticated
    ? (license.tier === "builder" ? "Builder" : "Pro")
    : null;

  return (
    <div ref={ref} className="relative">
      {open && (
        <div
          className={cn(
            "absolute bottom-full left-0 right-0 mb-1 rounded-md",
            "border border-[var(--sidebar-border)] bg-[var(--sidebar-bg)]",
            "animate-in fade-in slide-in-from-bottom-2 duration-150",
            "z-50 overflow-hidden",
          )}
        >
          <div className="px-3.5 pb-1 pt-3">
            <p className="truncate text-[0.78rem] font-medium text-[var(--sidebar-text-muted)]">
              {emailLabel}
            </p>
          </div>

          <div className="px-1.5 py-1">
            <button
              type="button"
              onClick={() => { navigate("/config"); setOpen(false); }}
              className={cn(
                "flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-left text-[0.86rem]",
                "text-[var(--sidebar-text)] transition-colors hover:bg-[var(--sidebar-row-hover)]",
              )}
            >
              <Settings className="h-4 w-4 text-[var(--sidebar-icon)]" />
              Settings
            </button>

            <button
              type="button"
              onClick={() => { navigate("/agent-onboarding?run=1"); setOpen(false); }}
              className={cn(
                "flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-left text-[0.86rem]",
                "text-[var(--sidebar-text)] transition-colors hover:bg-[var(--sidebar-row-hover)]",
              )}
            >
              <Sparkles className="h-4 w-4 text-[var(--sidebar-icon)]" />
              Run onboarding
            </button>

            <button
              type="button"
              onClick={() => { navigate("/desktop-setup"); setOpen(false); }}
              className={cn(
                "flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-left text-[0.86rem]",
                "text-[var(--sidebar-text)] transition-colors hover:bg-[var(--sidebar-row-hover)]",
              )}
            >
              <User className="h-4 w-4 text-[var(--sidebar-icon)]" />
              Account
            </button>
          </div>

          <div className="flex items-center gap-2 border-t border-[var(--sidebar-border)] px-3.5 py-2">
            <ThemeSwitcher dropUp />
            <LanguageSwitcher />
          </div>

          {license?.authenticated && (
            <div className="border-t border-[var(--sidebar-border)] px-1.5 py-1">
              <button
                type="button"
                onClick={handleSignOut}
                className={cn(
                  "flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-left text-[0.86rem]",
                  "text-[var(--sidebar-text)] transition-colors hover:bg-[var(--sidebar-row-hover)]",
                )}
              >
                <LogOut className="h-4 w-4 text-[var(--sidebar-icon)]" />
                Sign out
              </button>
            </div>
          )}
        </div>
      )}

      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className={cn(
          "flex w-full items-center gap-2 rounded-lg px-2.5 py-2 text-left",
          "transition-colors hover:bg-[var(--sidebar-row-hover)]",
          "focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-midground",
          open && "bg-[var(--sidebar-row-hover)]",
        )}
      >
        <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-[var(--sidebar-row)] text-[0.7rem] font-semibold uppercase text-[var(--sidebar-text-muted)]">
          {license?.authenticated && license.email
            ? license.email[0]
            : "?"}
        </div>
        <div className="min-w-0 flex-1">
          <p className="truncate text-[0.82rem] font-medium leading-tight text-[var(--sidebar-text-strong)]">
            {license?.authenticated && license.email
              ? license.email.split("@")[0]
              : "Not signed in"}
          </p>
          {tierLabel && (
            <p className="text-[0.68rem] leading-tight text-[var(--sidebar-text-muted)]">
              {tierLabel}
            </p>
          )}
        </div>
        <ChevronUp className={cn(
          "h-3.5 w-3.5 shrink-0 text-[var(--sidebar-icon-muted)] transition-transform",
          !open && "rotate-180",
        )} />
      </button>
    </div>
  );
}

```

---
## `src/components/SlashPopover.tsx`
```tsx
import { api, type PluginManifestResponse, type SkillInfo, type ToolsetInfo } from "@/lib/api";
import type { GatewayClient } from "@/lib/gatewayClient";
import { cn } from "@/lib/utils";
import {
  Bot,
  Box,
  Brain,
  CalendarClock,
  CheckSquare,
  Code2,
  FileText,
  Folder,
  GitBranch,
  Globe,
  Hammer,
  ListChecks,
  MessageSquare,
  Plug,
  Sparkles,
  Terminal,
  Zap,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import {
  forwardRef,
  useCallback,
  useEffect,
  useImperativeHandle,
  useMemo,
  useRef,
  useState,
} from "react";

export interface CompletionItem {
  display?: unknown;
  text: string;
  meta?: string;
}

interface PickerItem extends CompletionItem {
  display: string;
  group: string;
  icon: LucideIcon;
  insertText?: string;
  kind: "agent" | "context" | "file" | "plugin" | "skill" | "slash" | "toolset";
}

export interface CompletionAgent {
  description?: string;
  enabled: boolean;
  id: string;
  name: string;
  role?: string;
  status?: string;
}

export interface SlashPopoverHandle {
  /** Returns true if the key was consumed by the popover. */
  handleKey(e: React.KeyboardEvent<HTMLTextAreaElement>): boolean;
}

interface Props {
  agents: CompletionAgent[];
  caretIndex: number;
  gw: GatewayClient | null;
  input: string;
  onApply(nextInput: string, nextCaret: number): void;
  onSubmit?(nextInput: string): void;
}

interface CompletionResponse {
  items?: CompletionItem[];
  replace_from?: number;
}

interface MentionCatalog {
  plugins: PluginManifestResponse[];
  skills: SkillInfo[];
  toolsets: ToolsetInfo[];
}

type Trigger =
  | {
      end: number;
      mode: "mention";
      query: string;
      start: number;
      word: string;
    }
  | {
      end: number;
      mode: "slash";
      start: number;
      text: string;
    };

const DEBOUNCE_MS = 70;
const MAX_GROUP_ITEMS = 12;
// The slash menu is the primary way to reach skills, so it shows the full
// catalog (the popover itself scrolls) instead of the 12-item @-mention cap.
const MAX_SLASH_GROUP_ITEMS = 100;
const EMPTY_CATALOG: MentionCatalog = {
  plugins: [],
  skills: [],
  toolsets: [],
};

const STATIC_CONTEXT_REFS: PickerItem[] = [
  {
    display: "@diff",
    group: "Context",
    icon: GitBranch,
    kind: "context",
    meta: "Git working tree diff",
    text: "@diff",
  },
  {
    display: "@staged",
    group: "Context",
    icon: CheckSquare,
    kind: "context",
    meta: "Git staged diff",
    text: "@staged",
  },
  {
    display: "@file:",
    group: "Files",
    icon: FileText,
    kind: "file",
    meta: "Attach a file",
    text: "@file:",
  },
  {
    display: "@folder:",
    group: "Files",
    icon: Folder,
    kind: "file",
    meta: "Attach a folder",
    text: "@folder:",
  },
  {
    display: "@url:",
    group: "Context",
    icon: Globe,
    kind: "context",
    meta: "Fetch web content",
    text: "@url:",
  },
  {
    display: "@git:",
    group: "Context",
    icon: GitBranch,
    kind: "context",
    meta: "Git log with diffs",
    text: "@git:",
  },
];

function commandIcon(command: string): LucideIcon {
  const name = command.replace(/^\//, "").trim().split(/\s+/)[0];
  if (["fast", "yolo"].includes(name)) return Zap;
  if (["model", "reasoning"].includes(name)) return Box;
  if (name === "personality") return Brain;
  if (["agents", "tasks", "queue", "steer"].includes(name)) return Bot;
  if (["cron", "background"].includes(name)) return CalendarClock;
  if (["skills", "plugins"].includes(name)) return Sparkles;
  if (["tools", "toolsets", "browser"].includes(name)) return Hammer;
  if (["help", "commands", "status", "usage", "insights"].includes(name)) return ListChecks;
  if (["branch", "fork", "resume", "new"].includes(name)) return MessageSquare;
  if (["compact", "compress"].includes(name)) return Code2;
  return Terminal;
}

function asPlainText(value: unknown, fallback = ""): string {
  if (typeof value === "string") return value;
  if (Array.isArray(value)) {
    return value
      .map((part) => {
        if (Array.isArray(part)) return String(part[1] ?? "");
        if (part && typeof part === "object" && "text" in part) {
          return String((part as { text?: unknown }).text ?? "");
        }
        return typeof part === "string" ? part : "";
      })
      .join("");
  }
  return fallback;
}

function displayCommandLabel(display: unknown, text: string): string {
  const raw = asPlainText(display, text).replace(/^\//, "").trim();
  const base = raw.split(/\s+/)[0];
  return base
    .split(/[-_]/)
    .filter(Boolean)
    .map((part) => part.slice(0, 1).toUpperCase() + part.slice(1))
    .join(" ");
}

function displaySkillName(name: string): string {
  return name
    .split(/[-_]/)
    .filter(Boolean)
    .map((part) => part.slice(0, 1).toUpperCase() + part.slice(1))
    .join(" ");
}

function skillCommandText(name: string): string {
  const slug = name
    .toLowerCase()
    .replace(/[ _]+/g, "-")
    .replace(/[^a-z0-9-]/g, "")
    .replace(/-{2,}/g, "-")
    .replace(/^-+|-+$/g, "");
  return slug ? `/${slug}` : "";
}

function detectTrigger(input: string, caretIndex: number): Trigger | null {
  const caret = Math.max(0, Math.min(caretIndex, input.length));
  const before = input.slice(0, caret);
  const firstNonSpace = before.search(/\S/);

  if (firstNonSpace >= 0 && before.slice(firstNonSpace).startsWith("/")) {
    const lineStart = before.lastIndexOf("\n") + 1;
    if (firstNonSpace === lineStart) {
      return {
        end: caret,
        mode: "slash",
        start: firstNonSpace,
        text: before.slice(firstNonSpace),
      };
    }
  }

  let start = caret;
  while (start > 0 && !/\s/.test(input[start - 1] ?? "")) {
    start -= 1;
  }
  const word = input.slice(start, caret);
  if (!word.startsWith("@")) return null;

  return {
    end: caret,
    mode: "mention",
    query: word.slice(1),
    start,
    word,
  };
}

function matchesMention(item: Pick<PickerItem, "display" | "meta" | "text">, query: string): boolean {
  const q = query.toLowerCase();
  if (!q) return true;
  return [asPlainText(item.display), item.text, item.meta ?? ""]
    .join(" ")
    .toLowerCase()
    .includes(q);
}

function matchesSlash(item: Pick<PickerItem, "display" | "meta" | "text">, query: string): boolean {
  const q = query.toLowerCase();
  if (!q) return true;
  return [
    asPlainText(item.display),
    item.text.replace(/^\//, ""),
    item.text,
    item.meta ?? "",
  ]
    .join(" ")
    .toLowerCase()
    .includes(q);
}

function slashCommandQuery(text: string): string | null {
  const body = text.replace(/^\/+/, "");
  if (/\s/.test(body)) return null;
  return body.toLowerCase();
}

function mentionCatalogItems(
  catalog: MentionCatalog,
  agents: CompletionAgent[],
  query: string,
): PickerItem[] {
  const items: PickerItem[] = [];

  for (const agent of agents.filter((agent) => agent.enabled)) {
    items.push({
      display: agent.name,
      group: "Agents",
      icon: Bot,
      kind: "agent",
      meta: agent.role || agent.description || agent.status,
      text: `@agent:${agent.id}`,
    });
  }

  for (const plugin of catalog.plugins) {
    items.push({
      display: plugin.label || plugin.name,
      group: "Plugins",
      icon: Plug,
      kind: "plugin",
      meta: plugin.description || plugin.source || "Dashboard plugin",
      text: `@plugin:${plugin.name}`,
    });
  }

  for (const toolset of catalog.toolsets.filter((toolset) => toolset.enabled)) {
    items.push({
      display: toolset.label || toolset.name,
      group: "Toolsets",
      icon: Hammer,
      kind: "toolset",
      meta: toolset.description || `${toolset.tools.length} tools`,
      text: `@toolset:${toolset.name}`,
    });
  }

  for (const skill of catalog.skills.filter((skill) => skill.enabled)) {
    items.push({
      display: displaySkillName(skill.name),
      group: "Skills",
      icon: Box,
      kind: "skill",
      meta: [skill.description, skill.category].filter(Boolean).join(" · "),
      text: `@skill:${skill.name}`,
    });
  }

  const filtered = items.filter((item) => matchesMention(item, query));
  const grouped = new Map<string, PickerItem[]>();
  for (const item of filtered) {
    const group = grouped.get(item.group) ?? [];
    if (group.length < MAX_GROUP_ITEMS) {
      group.push(item);
      grouped.set(item.group, group);
    }
  }

  return ["Agents", "Plugins", "Toolsets", "Skills"].flatMap(
    (group) => grouped.get(group) ?? [],
  );
}

function classifyPathItem(item: CompletionItem): PickerItem {
  const text = item.text || asPlainText(item.display);
  const isFolder = text.startsWith("@folder:") || text.endsWith("/");
  const isStatic = STATIC_CONTEXT_REFS.some((ref) => ref.text === text);
  return {
    display: asPlainText(item.display, String(text)),
    group: isStatic && !text.startsWith("@file") && !text.startsWith("@folder") ? "Context" : "Files",
    icon: isFolder ? Folder : text.startsWith("@url") ? Globe : text.startsWith("@git") ? GitBranch : FileText,
    kind: isStatic ? "context" : "file",
    meta: item.meta,
    text,
  };
}

function slashSkillItems(catalog: MentionCatalog, query: string | null): PickerItem[] {
  if (query === null) return [];
  return catalog.skills
    .filter((skill) => skill.enabled)
    .map((skill) => {
      const commandText = skillCommandText(skill.name);
      return {
        display: displaySkillName(skill.name),
        group: "Skills",
        icon: Sparkles,
        kind: "skill" as const,
        meta: [skill.description, skill.category].filter(Boolean).join(" · "),
        text: commandText,
      };
    })
    .filter((item) => item.text && matchesSlash(item, query))
    .slice(0, MAX_SLASH_GROUP_ITEMS);
}

function skillCommandMap(catalog: MentionCatalog): Map<string, SkillInfo> {
  const mapped = new Map<string, SkillInfo>();
  for (const skill of catalog.skills.filter((candidate) => candidate.enabled)) {
    const commandText = skillCommandText(skill.name);
    if (commandText) mapped.set(commandText.toLowerCase(), skill);
  }
  return mapped;
}

function normalizeSlashItem(
  item: CompletionItem,
  skillsByCommand: Map<string, SkillInfo>,
): PickerItem {
  const rawText = item.text || asPlainText(item.display);
  const insertText = rawText.startsWith("/") ? rawText : `/${rawText}`;
  const commandText = insertText.trimEnd();
  const skill = skillsByCommand.get(commandText.toLowerCase());
  return {
    display: skill ? displaySkillName(skill.name) : displayCommandLabel(item.display, commandText),
    group: skill ? "Skills" : "Commands",
    icon: skill ? Sparkles : commandIcon(commandText),
    insertText: skill ? commandText : insertText,
    kind: skill ? "skill" : "slash",
    meta: skill ? [skill.description, skill.category].filter(Boolean).join(" · ") : item.meta,
    text: commandText,
  };
}

function shouldShowSlashCommandItem(item: PickerItem, query: string | null, hasSkillMatches: boolean): boolean {
  if (!hasSkillMatches || query === null) return true;
  if (query === "skills") return true;
  return item.text.toLowerCase() !== "/skills";
}

function slashGroupOrder(
  query: string | null,
  slashText: string,
  hasSkillMatches: boolean,
): string[] {
  const normalized =
    query ??
    slashText
      .replace(/^\/+/, "")
      .trim()
      .toLowerCase()
      .split(/\s+/)[0] ??
    "";
  if (hasSkillMatches && normalized && normalized !== "skills") {
    return ["Skills", "Commands"];
  }
  return ["Commands", "Skills"];
}

function orderGroupedItems(
  items: PickerItem[],
  groupOrder: string[],
  maxPerGroup: number = MAX_GROUP_ITEMS,
): PickerItem[] {
  const seen = new Set<string>();
  const grouped = new Map<string, PickerItem[]>();
  for (const item of items) {
    const dedupeKey = `${item.group}:${item.text}`;
    if (seen.has(dedupeKey)) continue;
    seen.add(dedupeKey);

    const group = grouped.get(item.group) ?? [];
    if (group.length < maxPerGroup) {
      group.push(item);
      grouped.set(item.group, group);
    }
  }
  return groupOrder.flatMap((group) => grouped.get(group) ?? []);
}

function shouldAppendSpace(item: PickerItem): boolean {
  if (item.kind === "slash" || item.text.startsWith("/")) {
    return false;
  }
  return !item.text.endsWith(":") && !item.text.endsWith("/");
}

export const SlashPopover = forwardRef<SlashPopoverHandle, Props>(
  function SlashPopover({ agents, caretIndex, input, gw, onApply, onSubmit }, ref) {
    const trigger = useMemo(
      () => detectTrigger(input, caretIndex),
      [caretIndex, input],
    );
    const [items, setItems] = useState<PickerItem[]>([]);
    const [selected, setSelected] = useState(0);
    const [slashReplaceFrom, setSlashReplaceFrom] = useState(1);
    const [catalog, setCatalog] = useState<MentionCatalog>(EMPTY_CATALOG);
    const catalogLoadedRef = useRef(false);
    const requestKeyRef = useRef("");

    useEffect(() => {
      if (!trigger || catalogLoadedRef.current) return;
      catalogLoadedRef.current = true;
      void Promise.allSettled([
        api.getSkills(),
        api.getToolsets(),
        api.getPlugins(),
      ]).then(([skills, toolsets, plugins]) => {
        setCatalog({
          plugins: plugins.status === "fulfilled" ? plugins.value : [],
          skills: skills.status === "fulfilled" ? skills.value : [],
          toolsets: toolsets.status === "fulfilled" ? toolsets.value : [],
        });
      });
    }, [trigger]);

    useEffect(() => {
      if (!trigger || !gw) {
        setItems([]);
        return;
      }

      const key =
        trigger.mode === "slash"
          ? `slash:${trigger.text}:${catalog.skills.length}`
          : `mention:${trigger.word}:${catalog.skills.length}:${catalog.toolsets.length}:${catalog.plugins.length}:${agents.length}`;
      requestKeyRef.current = key;

      const timer = window.setTimeout(async () => {
        try {
          if (trigger.mode === "slash") {
            const response = await gw.request<CompletionResponse>("complete.slash", {
              text: trigger.text,
            });
            if (requestKeyRef.current !== key) return;
            setSlashReplaceFrom(response?.replace_from ?? 1);
            const query = slashCommandQuery(trigger.text);
            const skillsByCommand = skillCommandMap(catalog);
            const commandItems = (response?.items ?? [])
              .map((item) => normalizeSlashItem(item, skillsByCommand))
              .filter((item) => query === null || matchesSlash(item, query));
            const skillItems = slashSkillItems(catalog, query);
            const hasSkillMatches =
              skillItems.length > 0 || commandItems.some((item) => item.kind === "skill");
            setItems(
              orderGroupedItems(
                [
                  ...skillItems,
                  ...commandItems.filter((item) =>
                    shouldShowSlashCommandItem(item, query, hasSkillMatches),
                  ),
                ],
                slashGroupOrder(query, trigger.text, hasSkillMatches),
                MAX_SLASH_GROUP_ITEMS,
              ),
            );
            setSelected(0);
            return;
          }

          const pathResponse = await gw.request<CompletionResponse>("complete.path", {
            word: trigger.word,
          });
          if (requestKeyRef.current !== key) return;

          const fileItems = (pathResponse?.items ?? []).map(classifyPathItem);
          const catalogItems = mentionCatalogItems(catalog, agents, trigger.query);
          const contextItems = STATIC_CONTEXT_REFS.filter((item) =>
            matchesMention(item, trigger.query),
          );
          const merged = [...catalogItems, ...contextItems, ...fileItems];
          setItems(orderGroupedItems(merged, ["Agents", "Plugins", "Toolsets", "Skills", "Context", "Files"]));
          setSelected(0);
        } catch {
          if (requestKeyRef.current === key) {
            setItems([]);
          }
        }
      }, DEBOUNCE_MS);

      return () => window.clearTimeout(timer);
    }, [agents, catalog, gw, trigger]);

    const visible = Boolean(trigger && items.length > 0);

    const inputForItem = useCallback(
      (item: PickerItem): { nextCaret: number; nextInput: string } | null => {
        if (!trigger) return null;

        let replaceStart = trigger.start;
        let replacement = item.insertText ?? item.text;

        if (trigger.mode === "slash") {
          replaceStart = trigger.start + slashReplaceFrom;
          replacement = replacement.replace(/^\//, "");
        }

        if (shouldAppendSpace(item)) {
          replacement = replacement.endsWith(" ") ? replacement : `${replacement} `;
        }

        const nextInput = `${input.slice(0, replaceStart)}${replacement}${input.slice(trigger.end)}`;
        return {
          nextCaret: replaceStart + replacement.length,
          nextInput,
        };
      },
      [input, slashReplaceFrom, trigger],
    );

    const apply = useCallback(
      (item: PickerItem, options?: { submit?: boolean }) => {
        const next = inputForItem(item);
        if (!next) return;
        setItems([]);
        if (options?.submit && onSubmit) {
          onSubmit(next.nextInput);
          return;
        }
        onApply(next.nextInput, next.nextCaret);
      },
      [inputForItem, onApply, onSubmit],
    );

    useImperativeHandle(
      ref,
      () => ({
        handleKey: (event) => {
          if (!visible) return false;

          switch (event.key) {
            case "ArrowDown":
              event.preventDefault();
              setSelected((value) => (value + 1) % items.length);
              return true;
            case "ArrowUp":
              event.preventDefault();
              setSelected((value) => (value - 1 + items.length) % items.length);
              return true;
            case "Enter":
            case "Tab": {
              event.preventDefault();
              const item = items[selected];
              if (item) {
                const next = inputForItem(item);
                const shouldSubmit =
                  event.key === "Enter" &&
                  trigger?.mode === "slash" &&
                  Boolean(onSubmit) &&
                  (item.kind === "skill" || next?.nextInput.trim() === input.trim());
                apply(item, { submit: shouldSubmit });
              }
              return true;
            }
            case "Escape":
              event.preventDefault();
              setItems([]);
              return true;
            default:
              return false;
          }
        },
      }),
      [apply, input, inputForItem, items, onSubmit, selected, trigger?.mode, visible],
    );

    // Keep the keyboard-selected row inside the scrollable popover viewport.
    useEffect(() => {
      if (!visible) return;
      const el = document.getElementById(`slash-item-${selected}`);
      el?.scrollIntoView({ block: "nearest" });
    }, [selected, visible]);

    if (!visible) return null;

    let lastGroup = "";

    const listboxId = "slash-popover-listbox";
    const activeItemId = items[selected] ? `slash-item-${selected}` : undefined;

    return (
      <div
        aria-activedescendant={activeItemId}
        className={cn(
          "absolute bottom-full left-0 right-0 z-40 mb-2 max-h-[20rem] overflow-y-auto rounded-md p-1.5",
          "border border-[var(--chat-border)] bg-[var(--chat-surface-soft)] text-[var(--chat-text)]",
        )}
        id={listboxId}
        role="listbox"
      >
        {items.map((item, index) => {
          const active = index === selected;
          const Icon = item.icon;
          const showGroup = item.group !== lastGroup;
          lastGroup = item.group;

          return (
            <div key={`${item.group}-${item.text}-${index}`}>
              {showGroup && (
                <div className="px-2.5 pb-0.5 pt-1.5 text-[0.68rem] font-medium text-[var(--chat-muted)]">
                  {item.group}
                </div>
              )}
              <button
                aria-selected={active}
                className={cn(
                  "grid min-h-8 w-full grid-cols-[1.35rem_minmax(0,auto)_minmax(0,1fr)_auto] items-center gap-1.5 rounded-sm px-2.5 py-1 text-left transition-colors",
                  active
                    ? "bg-[var(--chat-surface-strong)] text-[var(--chat-text)]"
                    : "text-[var(--chat-muted-strong)] hover:bg-[var(--chat-surface-strong)] hover:text-[var(--chat-text)]",
                )}
                id={`slash-item-${index}`}
                onClick={() =>
                  apply(item, {
                    submit: trigger?.mode === "slash" && item.kind === "skill",
                  })
                }
                onMouseEnter={() => setSelected(index)}
                role="option"
                type="button"
              >
                <Icon className="h-3.5 w-3.5 justify-self-center text-current opacity-85" />
                <span className="min-w-0 truncate text-[0.82rem] font-medium leading-5">
                  {item.display}
                </span>
                {item.meta && (
                  <span className="min-w-0 truncate text-[0.72rem] leading-5 text-[var(--chat-muted)]">
                    {item.meta}
                  </span>
                )}
                {item.kind === "skill" && (
                  <span className="rounded-sm border border-[var(--chat-border)] px-1.5 py-0.5 text-[0.62rem] leading-none text-[var(--chat-muted)]">
                    Personal
                  </span>
                )}
              </button>
            </div>
          );
        })}
        {trigger?.mode === "mention" && trigger.query.length === 0 && (
          <div className="px-2.5 pb-1.5 pt-1 text-[0.72rem] text-[var(--chat-muted)]">
            Type to search for files, skills, agents, toolsets, or plugins.
          </div>
        )}
      </div>
    );
  },
);

```

---
## `src/components/ThemeSwitcher.tsx`
```tsx
import { useCallback, useEffect, useRef, useState } from "react";
import { Check, Moon, Sun } from "lucide-react";
import { Typography } from "@nous-research/ui/ui/components/typography/index";
import { BUILTIN_THEMES, useTheme } from "@/themes";
import { useI18n } from "@/i18n";
import { cn } from "@/lib/utils";

/**
 * Compact light/dark picker mounted next to the language switcher in the
 * header.
 *
 * When placed at the bottom of a container (e.g. the sidebar rail), pass
 * `dropUp` so the menu opens above the trigger instead of clipping below
 * the viewport.
 */
export function ThemeSwitcher({ dropUp = false }: ThemeSwitcherProps) {
  const { themeName, availableThemes, setTheme } = useTheme();
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  const wrapperRef = useRef<HTMLDivElement>(null);

  const close = useCallback(() => setOpen(false), []);

  useEffect(() => {
    if (!open) return;
    const onMouseDown = (e: MouseEvent) => {
      if (
        wrapperRef.current &&
        !wrapperRef.current.contains(e.target as Node)
      ) {
        close();
      }
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") close();
    };
    document.addEventListener("mousedown", onMouseDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onMouseDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open, close]);

  const current = availableThemes.find((th) => th.name === themeName);
  const label = current?.label ?? themeName;
  const ActiveIcon = themeName === "light" ? Sun : Moon;

  return (
    <div ref={wrapperRef} className="relative">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className={cn(
          "inline-flex h-8 items-center gap-2 rounded-lg border border-border px-2.5 text-[0.82rem]",
          "bg-card text-[var(--sidebar-text)] transition-colors hover:text-[var(--sidebar-text-active)]",
          "focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring",
        )}
        title={t.theme?.switchTheme ?? "Switch theme"}
        aria-label={t.theme?.switchTheme ?? "Switch theme"}
        aria-expanded={open}
        aria-haspopup="listbox"
      >
        <ActiveIcon className="h-4 w-4 text-[var(--sidebar-icon)]" />
        <Typography
          className="hidden text-[0.82rem] font-medium normal-case tracking-normal sm:inline"
        >
          {label}
        </Typography>
      </button>

      {open && (
        <div
          role="listbox"
          aria-label={t.theme?.title ?? "Theme"}
          className={cn(
            "absolute z-50 min-w-[240px]",
            dropUp ? "left-0 bottom-full mb-1" : "right-0 top-full mt-1",
            "overflow-hidden rounded-md border border-border bg-card",
          )}
        >
          <div className="border-b border-border px-3 py-2">
            <Typography className="text-xs font-semibold normal-case text-muted-foreground">
              {t.theme?.title ?? "Theme"}
            </Typography>
          </div>

          {availableThemes.map((th) => {
            const isActive = th.name === themeName;
            const preset = BUILTIN_THEMES[th.name];

            return (
              <button
                key={th.name}
                type="button"
                role="option"
                aria-selected={isActive}
                onClick={() => {
                  setTheme(th.name);
                  close();
                }}
                className={cn(
                  "flex w-full items-center gap-3 px-3 py-2 text-left transition-colors cursor-pointer",
                  "hover:bg-accent",
                  isActive ? "text-foreground" : "text-muted-foreground",
                )}
              >
                {preset ? (
                  <ThemeSwatch theme={preset.name} />
                ) : (
                  <PlaceholderSwatch />
                )}

                <div className="flex min-w-0 flex-1 flex-col gap-0.5">
                  <Typography
                    className="truncate text-sm font-medium normal-case tracking-normal"
                  >
                    {th.label}
                  </Typography>
                  {th.description && (
                    <Typography className="truncate text-xs normal-case tracking-normal text-muted-foreground">
                      {th.description}
                    </Typography>
                  )}
                </div>

                <Check
                  className={cn(
                    "h-3.5 w-3.5 shrink-0 text-primary",
                    isActive ? "opacity-100" : "opacity-0",
                  )}
                />
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}

function ThemeSwatch({ theme }: { theme: string }) {
  const preset = BUILTIN_THEMES[theme];
  if (!preset) return <PlaceholderSwatch />;
  const { background, midground, warmGlow } = preset.palette;
  return (
    <div
      aria-hidden
      className="flex h-5 w-10 shrink-0 overflow-hidden rounded-md border border-border"
    >
      <span className="flex-1" style={{ background: background.hex }} />
      <span className="flex-1" style={{ background: midground.hex }} />
      <span className="flex-1" style={{ background: warmGlow }} />
    </div>
  );
}

function PlaceholderSwatch() {
  return (
    <div
      aria-hidden
      className="h-5 w-10 shrink-0 rounded-md border border-dashed border-border"
    />
  );
}

interface ThemeSwitcherProps {
  dropUp?: boolean;
}

```

---
## `src/components/Toast.tsx`
```tsx
import { useEffect, useState } from "react";
import { createPortal } from "react-dom";

export function Toast({ toast }: { toast: { message: string; type: "success" | "error" } | null }) {
  const [visible, setVisible] = useState(false);
  const [current, setCurrent] = useState(toast);

  useEffect(() => {
    if (toast) {
      setCurrent(toast);
      setVisible(true);
    } else {
      setVisible(false);
      const timer = setTimeout(() => setCurrent(null), 200);
      return () => clearTimeout(timer);
    }
  }, [toast]);

  if (!current) return null;

  // Portal to document.body so the toast escapes any ancestor stacking context
  // (e.g. <main> has `relative z-2`, which would trap z-50 below the header's z-40).
  return createPortal(
    <div
      role="status"
      aria-live="polite"
      className={`fixed top-16 right-4 z-50 rounded-md border px-4 py-2.5 text-xs backdrop-blur-sm ${
        current.type === "success"
          ? "bg-success/15 text-success border-success/30"
          : "bg-destructive/15 text-destructive border-destructive/30"
      }`}
      style={{
        animation: visible ? "toast-in 200ms ease-out forwards" : "toast-out 200ms ease-in forwards",
      }}
    >
      {current.message}
    </div>,
    document.body,
  );
}

```

---
## `src/components/ToolCall.tsx`
```tsx
import {
  AlertCircle,
  Check,
  ChevronDown,
  ChevronRight,
  Zap,
} from "lucide-react";
import { useEffect, useState } from "react";

/**
 * Expandable tool call row — the web equivalent of Ink's ToolTrail node.
 *
 * Renders one `tool.start` + `tool.complete` pair (plus any `tool.progress`
 * in between) as a single collapsible item in the transcript:
 *
 *   ▸ ● read_file(path=/foo)                         2.3s
 *
 * Click the header to reveal a preformatted body with context (args), the
 * streaming preview (while running), and the final summary or error. Error
 * rows auto-expand so failures aren't silently collapsed.
 */

export interface ToolEntry {
  kind: "tool";
  id: string;
  tool_id: string;
  name: string;
  context?: string;
  preview?: string;
  summary?: string;
  error?: string;
  inline_diff?: string;
  status: "running" | "done" | "error";
  startedAt: number;
  completedAt?: number;
  messageId?: string;
}

const STATUS_TONE: Record<ToolEntry["status"], string> = {
  running: "border-border bg-card",
  done: "border-border bg-card",
  error: "border-border bg-card",
};

const BULLET_TONE: Record<ToolEntry["status"], string> = {
  running: "text-primary",
  done: "text-primary/80",
  error: "text-destructive",
};

const TICK_MS = 500;

export function ToolCall({ tool }: { tool: ToolEntry }) {
  // `open` is derived: errors default-expanded, everything else collapsed.
  // `null` means "follow the default"; any explicit bool is the user's override.
  // This lets a running tool flip to expanded automatically when it errors,
  // without mirroring state in an effect.
  const [userOverride, setUserOverride] = useState<boolean | null>(null);
  const open = userOverride ?? tool.status === "error";

  // Tick `now` while the tool is running so the elapsed label updates live.
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (tool.status !== "running") return;
    const id = window.setInterval(() => setNow(() => Date.now()), TICK_MS);
    return () => window.clearInterval(id);
  }, [tool.status]);

  // Historical tools (hydrated from session.resume) signal missing timestamps
  // with `startedAt === 0`; we hide the elapsed badge for those rather than
  // rendering a misleading "0ms".
  const hasTimestamps = tool.startedAt > 0;
  const elapsed = hasTimestamps
    ? fmtElapsed((tool.completedAt ?? now) - tool.startedAt)
    : null;

  const hasBody = !!(
    tool.context ||
    tool.preview ||
    tool.summary ||
    tool.error ||
    tool.inline_diff
  );

  const Chevron = open ? ChevronDown : ChevronRight;

  return (
    <div
      className={`rounded-md border overflow-hidden ${STATUS_TONE[tool.status]}`}
    >
      <button
        type="button"
        onClick={() => setUserOverride(!open)}
        disabled={!hasBody}
        aria-expanded={open}
        className="w-full flex items-center gap-2 px-2.5 py-1.5 text-left text-xs hover:bg-foreground/2 disabled:cursor-default cursor-pointer transition-colors"
      >
        {hasBody ? (
          <Chevron className="h-3 w-3 shrink-0 text-muted-foreground" />
        ) : (
          <span className="w-3 shrink-0" />
        )}

        <Zap className={`h-3 w-3 shrink-0 ${BULLET_TONE[tool.status]}`} />

        <span className="font-mono font-medium shrink-0">{tool.name}</span>

        <span className="font-mono text-muted-foreground/80 truncate min-w-0 flex-1">
          {tool.context ?? ""}
        </span>

        {tool.status === "running" && (
          <span
            className="inline-block h-2 w-2 rounded-full bg-primary animate-pulse shrink-0"
            title="running"
          />
        )}
        {tool.status === "error" && (
          <AlertCircle
            className="h-3 w-3 shrink-0 text-destructive"
            aria-label="error"
          />
        )}
        {tool.status === "done" && (
          <Check
            className="h-3 w-3 shrink-0 text-primary/80"
            aria-label="done"
          />
        )}

        {elapsed && (
          <span className="font-mono text-[0.65rem] text-muted-foreground tabular-nums shrink-0">
            {elapsed}
          </span>
        )}
      </button>

      {open && hasBody && (
        <div className="border-t border-border/60 px-3 py-2 space-y-2 text-xs font-mono">
          {tool.context && <Section label="context">{tool.context}</Section>}

          {tool.preview && tool.status === "running" && (
            <Section label="streaming">
              {tool.preview}
              <span className="inline-block w-1.5 h-3 align-middle bg-foreground/40 ml-0.5 animate-pulse" />
            </Section>
          )}

          {tool.inline_diff && (
            <Section label="diff">
              <pre className="whitespace-pre overflow-x-auto text-[0.7rem] leading-snug">
                {colorizeDiff(tool.inline_diff)}
              </pre>
            </Section>
          )}

          {tool.summary && (
            <Section label="result">
              <span className="text-foreground/90 whitespace-pre-wrap">
                {tool.summary}
              </span>
            </Section>
          )}

          {tool.error && (
            <Section label="error" tone="error">
              <span className="text-destructive whitespace-pre-wrap">
                {tool.error}
              </span>
            </Section>
          )}
        </div>
      )}
    </div>
  );
}

function Section({
  label,
  children,
  tone,
}: {
  label: string;
  children: React.ReactNode;
  tone?: "error";
}) {
  return (
    <div className="flex gap-3">
      <span
        className={`uppercase tracking-wider text-[0.6rem] shrink-0 w-14 pt-0.5 ${
          tone === "error" ? "text-destructive/80" : "text-muted-foreground/60"
        }`}
      >
        {label}
      </span>

      <div className="flex-1 min-w-0 text-muted-foreground">{children}</div>
    </div>
  );
}

function fmtElapsed(ms: number): string {
  const sec = Math.max(0, ms) / 1000;
  if (sec < 1) return `${Math.round(ms)}ms`;
  if (sec < 10) return `${sec.toFixed(1)}s`;
  if (sec < 60) return `${Math.round(sec)}s`;

  const m = Math.floor(sec / 60);
  const s = Math.round(sec % 60);
  return s ? `${m}m ${s}s` : `${m}m`;
}

/** Colorize unified-diff lines for the inline diff section. */
function colorizeDiff(diff: string): React.ReactNode {
  return diff.split("\n").map((line, i) => (
    <div key={i} className={diffLineClass(line)}>
      {line || "\u00A0"}
    </div>
  ));
}

function diffLineClass(line: string): string {
  if (line.startsWith("+") && !line.startsWith("+++"))
    return "text-[var(--color-success)]";
  if (line.startsWith("-") && !line.startsWith("---"))
    return "text-destructive";
  if (line.startsWith("@@")) return "text-primary";
  return "text-muted-foreground/80";
}

```
