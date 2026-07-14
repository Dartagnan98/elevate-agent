import { useEffect, useState, useCallback, useMemo, useRef } from "react";
import { ShieldCheck, ShieldOff, Copy, ExternalLink, RefreshCw, LogOut, Terminal, LogIn } from "lucide-react";
import { api, type OAuthProvider } from "@/lib/api";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { OAuthLoginModal } from "@/components/OAuthLoginModal";
import { ListSkeleton } from "@/components/ui/skeleton";
import { useI18n } from "@/i18n";
import {
  isOAuthProviderAllowedInOnboarding,
  oauthProviderRowsForOnboarding,
  refreshOAuthProvidersForOnboarding,
} from "@/pages/agent-onboarding/beta-provider-ui";

interface Props {
  onError?: (msg: string) => void;
  onSuccess?: (msg: string) => void;
  onProvidersChange?: (providers: OAuthProvider[] | null) => void;
  realtorBeta?: boolean;
}

function formatExpiresAt(expiresAt: string | number | null | undefined, expiresInTemplate: string): string | null {
  if (!expiresAt) return null;
  try {
    const numeric = typeof expiresAt === "number" ? expiresAt : Number(expiresAt);
    const value = Number.isFinite(numeric)
      ? Math.abs(numeric) < 100_000_000_000
        ? numeric * 1000
        : numeric
      : expiresAt;
    const dt = new Date(value);
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

export function OAuthProvidersCard({
  onError,
  onSuccess,
  onProvidersChange,
  realtorBeta = false,
}: Props) {
  const [providers, setProviders] = useState<OAuthProvider[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const [loginFor, setLoginFor] = useState<OAuthProvider | null>(null);
  const [disconnectTarget, setDisconnectTarget] = useState<OAuthProvider | null>(null);
  const { t } = useI18n();

  const onErrorRef = useRef(onError);
  const onSuccessRef = useRef(onSuccess);
  const onProvidersChangeRef = useRef(onProvidersChange);

  useEffect(() => {
    onErrorRef.current = onError;
    onSuccessRef.current = onSuccess;
    onProvidersChangeRef.current = onProvidersChange;
  }, [onError, onProvidersChange, onSuccess]);

  const refresh = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    const result = await refreshOAuthProvidersForOnboarding({
      load: api.getOAuthProviders,
      realtorBeta,
      publish: (nextProviders) => {
        setProviders(nextProviders);
        onProvidersChangeRef.current?.(nextProviders);
      },
    });
    if (result.error) {
      setLoadError(result.error);
      onErrorRef.current?.(result.error);
    }
    setLoading(false);
  }, [realtorBeta]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const handleCopy = async (provider: OAuthProvider) => {
    if (!isOAuthProviderAllowedInOnboarding(provider.id, realtorBeta)) {
      onErrorRef.current?.("Realtor Beta supports only OpenAI Codex sign-in.");
      return;
    }
    try {
      await navigator.clipboard.writeText(provider.cli_command);
      setCopiedId(provider.id);
      onSuccessRef.current?.(`Copied: ${provider.cli_command}`);
      setTimeout(() => setCopiedId((v) => (v === provider.id ? null : v)), 1500);
    } catch {
      onErrorRef.current?.("Clipboard write failed — copy the command manually");
    }
  };

  const handleDisconnect = async (provider: OAuthProvider) => {
    if (!isOAuthProviderAllowedInOnboarding(provider.id, realtorBeta)) {
      onErrorRef.current?.("Realtor Beta supports only OpenAI Codex sign-in.");
      return;
    }
    setBusyId(provider.id);
    try {
      await api.disconnectOAuthProvider(provider.id);
      onSuccessRef.current?.(`${provider.name} ${t.oauth.disconnect.toLowerCase()}ed`);
      await refresh();
      setDisconnectTarget(null);
    } catch (e) {
      onErrorRef.current?.(`${t.oauth.disconnect} failed: ${e}`);
    } finally {
      setBusyId(null);
    }
  };

  const providerRows = useMemo(
    () => oauthProviderRowsForOnboarding(providers ?? [], realtorBeta),
    [providers, realtorBeta],
  );
  const connectedCount = providerRows.filter((row) => row.provider.status.logged_in).length;
  const totalCount = providerRows.length;

  const beginLogin = (provider: OAuthProvider) => {
    if (!isOAuthProviderAllowedInOnboarding(provider.id, realtorBeta)) {
      onErrorRef.current?.("Realtor Beta supports only OpenAI Codex sign-in.");
      return;
    }
    setLoginFor(provider);
  };

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <ShieldCheck className="h-5 w-5 text-muted-foreground" />
            <CardTitle className="text-base">
              {realtorBeta ? "OpenAI Codex sign-in" : t.oauth.providerLogins}
            </CardTitle>
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
          {realtorBeta
            ? connectedCount > 0
              ? "Connected to this Realtor Beta profile."
              : "Sign in once so Elevation can work on your real estate tasks."
            : t.oauth.description.replace("{connected}", String(connectedCount)).replace("{total}", String(totalCount))}
        </CardDescription>
      </CardHeader>
      <CardContent>
        {loading && providers === null && (
          <ListSkeleton rows={3} />
        )}
        {loadError && (
          <p role="alert" className="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-xs leading-5 text-destructive">
            {loadError}
          </p>
        )}
        {providers && providers.length === 0 && (
          <p className="px-1 py-1 text-xs text-muted-foreground/80">
            {t.oauth.noProviders}
          </p>
        )}
        <div className="flex flex-col divide-y divide-border">
          {providerRows.map((row) => {
            const p = row.provider;
            const expiresLabel = formatExpiresAt(p.status.expires_at, t.oauth.expiresIn);
            const isBusy = busyId === p.id;
            const isExpired = expiresLabel === "expired";
            // Show Login on every non-external row so the user can swap
            // accounts or refresh credentials without first disconnecting.
            // External-CLI providers (Qwen) still can't take a Login click
            // (they need the third-party tool to run), so they stay hidden.
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
                    {!p.status.logged_in && realtorBeta && (
                      <span className="text-xs text-muted-foreground/80">
                        Not signed in on this Beta profile.
                      </span>
                    )}
                    {!p.status.logged_in && !realtorBeta && (
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
                  {row.showDocs && p.docs_url && (
                    <a
                      href={p.docs_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      aria-label={`Open ${p.name} docs`}
                      className="inline-flex h-7 w-7 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-foreground/8 hover:text-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring/70"
                      title={`Open ${p.name} docs`}
                    >
                      <ExternalLink className="h-3.5 w-3.5" aria-hidden="true" />
                    </a>
                  )}
                  {row.canStartLogin && (
                    <Button
                      variant="default"
                      size="sm"
                      onClick={() => beginLogin(p)}
                      className="text-xs h-7"
                    >
                      <LogIn className="h-3 w-3 mr-1" />
                      {loginLabel}
                    </Button>
                  )}
                  {row.showCopyCommand && (
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
                  {row.canDisconnect && (
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => setDisconnectTarget(p)}
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
      {loginFor && isOAuthProviderAllowedInOnboarding(loginFor.id, realtorBeta) && (
        <OAuthLoginModal
          provider={loginFor}
          onClose={() => {
            setLoginFor(null);
          }}
          onSuccess={(msg) => {
            onSuccessRef.current?.(msg);
            void refresh();
          }}
          onError={(msg) => onErrorRef.current?.(msg)}
        />
      )}
      <ConfirmDialog
        open={
          disconnectTarget !== null &&
          isOAuthProviderAllowedInOnboarding(disconnectTarget.id, realtorBeta)
        }
        title={`${t.oauth.disconnect} ${disconnectTarget?.name ?? "provider"}?`}
        description="This removes the stored OAuth credentials for this provider. You can log in again later."
        confirmLabel={t.oauth.disconnect}
        destructive
        loading={disconnectTarget ? busyId === disconnectTarget.id : false}
        onCancel={() => setDisconnectTarget(null)}
        onConfirm={() => {
          if (disconnectTarget) void handleDisconnect(disconnectTarget);
        }}
      />
    </Card>
  );
}
