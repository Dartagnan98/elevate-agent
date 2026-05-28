import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import type { GatewayClient } from "@/lib/gatewayClient";
import { cn } from "@/lib/utils";
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
      className="fixed inset-0 z-[100] flex items-center justify-center bg-[color-mix(in_srgb,var(--chat-bg)_82%,transparent)] p-4 backdrop-blur-sm"
      onClick={(e) => e.target === e.currentTarget && onClose()}
      role="dialog"
      aria-modal="true"
      aria-labelledby="model-picker-title"
    >
      <div className="relative flex max-h-[80vh] w-full max-w-3xl flex-col overflow-hidden rounded-xl border border-[var(--chat-border)] bg-[var(--chat-surface)] text-[var(--chat-text)] shadow-[0_24px_60px_-16px_rgba(0,0,0,0.72),0_1px_0_rgba(255,255,255,0.03)_inset]">
        <button
          type="button"
          onClick={onClose}
          className="absolute right-3 top-3 inline-flex h-7 w-7 cursor-pointer items-center justify-center rounded-[7px] text-[var(--chat-muted)] transition-colors hover:bg-[var(--chat-surface-strong)] hover:text-[var(--chat-text)]"
          aria-label="Close"
        >
          <X className="h-5 w-5" />
        </button>

        <header className="border-b border-[var(--chat-border)] p-5 pb-3">
          <h2
            id="model-picker-title"
            className="text-[15px] font-semibold tracking-normal normal-case"
          >
            Switch Model
          </h2>
          <p className="mt-1 text-[12px] text-[var(--chat-muted)]">
            current: {currentModel || "(unknown)"}
            {currentProviderSlug && ` · ${currentProviderSlug}`}
          </p>
        </header>

        <div className="border-b border-[var(--chat-border)] px-5 pb-2 pt-3">
          <div className="relative">
            <Search className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-[var(--chat-muted)]" />
            <Input
              autoFocus
              placeholder="Filter providers and models…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              className="h-8 rounded-[8px] border-[var(--chat-border)] bg-[var(--chat-surface-soft)] pl-8 text-sm text-[var(--chat-text)] placeholder:text-[var(--chat-muted)]"
            />
          </div>
        </div>

        <div className="grid min-h-0 flex-1 grid-cols-[200px_1fr] overflow-hidden">
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

        <footer className="flex flex-wrap items-center justify-between gap-3 border-t border-[var(--chat-border)] p-3">
          <label className="flex cursor-pointer select-none items-center gap-2 text-xs text-[var(--chat-muted)]">
            <input
              type="checkbox"
              checked={persistGlobal}
              onChange={(e) => setPersistGlobal(e.target.checked)}
              className="cursor-pointer"
            />
            Persist globally (otherwise this session only)
          </label>

          <div className="ml-auto flex items-center gap-2">
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
    <div className="overflow-y-auto border-r border-[var(--chat-border)]">
      {loading && (
        <div className="flex items-center gap-2 p-4 text-xs text-[var(--chat-muted)]">
          <Loader2 className="h-3 w-3 animate-spin" /> loading…
        </div>
      )}

      {error && <div className="p-4 text-xs text-[var(--chat-danger)]">{error}</div>}

      {!loading && !error && providers.length === 0 && (
        <div className="p-4 text-xs italic text-[var(--chat-muted)]">
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
            className={cn(
              "flex w-full cursor-pointer items-start gap-2 px-3 py-2 text-left text-xs transition-colors",
              active
                ? "bg-[var(--chat-accent-soft)] text-[var(--chat-text)]"
                : "text-[var(--chat-muted-strong)] hover:bg-[var(--chat-surface-soft)] hover:text-[var(--chat-text)]",
            )}
          >
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-1.5">
                <span className="font-medium truncate">{p.name}</span>
                {p.is_current && <CurrentTag />}
              </div>
              <div className="truncate font-mono text-[11px] text-[var(--chat-muted)]">
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
        <div className="p-4 text-xs italic text-[var(--chat-muted)]">
          pick a provider →
        </div>
      </div>
    );
  }

  return (
    <div className="overflow-y-auto">
      {provider.warning && (
        <div className="border-b border-[var(--chat-border)] p-3 text-xs text-[var(--chat-danger)]">
          {provider.warning}
        </div>
      )}

      {models.length === 0 ? (
        <div className="p-4 text-xs italic text-[var(--chat-muted)]">
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
              className={cn(
                "flex w-full cursor-pointer items-center gap-2 px-3 py-1.5 text-left font-mono text-xs transition-colors",
                active
                  ? "bg-[var(--chat-accent-soft)] text-[var(--chat-text)]"
                  : "text-[var(--chat-muted-strong)] hover:bg-[var(--chat-surface-soft)] hover:text-[var(--chat-text)]",
              )}
            >
              <Check
                className={cn("h-3 w-3 shrink-0", active ? "text-[var(--chat-accent)]" : "text-transparent")}
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
    <span className="shrink-0 text-[11px] font-medium tracking-normal text-[var(--chat-accent)]">
      current
    </span>
  );
}
