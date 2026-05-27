import { useCallback, useEffect, useLayoutEffect, useMemo, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import {
  Activity,
  AlertTriangle,
  Bot,
  ChevronRight,
  CheckCircle2,
  CircleAlert,
  Clock,
  Database,
  FileText,
  FolderOpen,
  KeyRound,
  LockKeyhole,
  MessageSquare,
  RefreshCw,
  RotateCw,
  Settings,
  ShieldCheck,
  Sparkles,
  Terminal,
  type LucideIcon,
} from "lucide-react";
import { api } from "@/lib/api";
import { LoginCard } from "@/components/LoginCard";
import type {
  AccessStatusResponse,
  AdminSetupSnapshot,
  AgentHubAgent,
  AgentHubSnapshot,
  ComposioStatus,
  HarnessSnapshot,
  OAuthProvidersResponse,
  PackOnboardingItem,
  PackOnboardingPack,
  PackOnboardingSnapshot,
  SourceConnectorsResponse,
  StatusResponse,
  UpdateStatusResponse,
} from "@/lib/api";
import { cn, isoTimeAgo } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button, buttonVariants } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Toast } from "@/components/Toast";
import { useToast } from "@/hooks/useToast";
import { usePageHeader } from "@/contexts/usePageHeader";

type ReadinessTone = "success" | "warning" | "outline" | "destructive";

interface LoadState {
  access: AccessStatusResponse | null;
  adminSetup: AdminSetupSnapshot | null;
  composio: ComposioStatus | null;
  connectors: SourceConnectorsResponse | null;
  harness: HarnessSnapshot | null;
  hub: AgentHubSnapshot | null;
  oauth: OAuthProvidersResponse | null;
  packOnboarding: PackOnboardingSnapshot | null;
  status: StatusResponse | null;
  updateStatus: UpdateStatusResponse | null;
}

const EMPTY_STATE: LoadState = {
  access: null,
  adminSetup: null,
  composio: null,
  connectors: null,
  harness: null,
  hub: null,
  oauth: null,
  packOnboarding: null,
  status: null,
  updateStatus: null,
};

const REQUIRED_AGENT_IDS = new Set(["executive-assistant", "admin"]);

const PACK_ACCENT: Record<string, string> = {
  elevate_core: "Basic",
  real_estate_admin: "Admin",
  real_estate_sales: "Sales",
  real_estate_marketing: "Marketing",
  real_estate_cma: "CMA",
};

const PACK_CREDENTIAL_FIELDS: Record<string, Array<{ key: string; label: string; password?: boolean }>> = {
  elevate_core: [
    { key: "OPENAI_API_KEY", label: "OpenAI API key", password: true },
    { key: "OPENAI_EMBEDDING_MODEL", label: "Embedding model" },
    { key: "OPENROUTER_API_KEY", label: "OpenRouter API key", password: true },
    { key: "ANTHROPIC_API_KEY", label: "Anthropic API key", password: true },
    { key: "GOOGLE_API_KEY", label: "Google/Gemini API key", password: true },
    { key: "TELEGRAM_BOT_TOKEN", label: "Executive Assistant Telegram bot token", password: true },
    { key: "TELEGRAM_ALLOWED_USERS", label: "Allowed Telegram user IDs" },
    { key: "BROWSER_USE_PROVIDER", label: "Browser-use provider" },
    { key: "BROWSER_USE_API_KEY", label: "Browser-use API key", password: true },
    { key: "COMPOSIO_API_KEY", label: "Composio API key", password: true },
    { key: "ELEVATE_UPDATE_CHANNEL", label: "Update channel" },
  ],
  real_estate_admin: [
    { key: "ELEVATE_AGENT_ADMIN_TELEGRAM_BOT_TOKEN", label: "Admin Telegram bot token", password: true },
    { key: "ELEVATE_AGENT_ADMIN_TELEGRAM_CHANNEL", label: "Admin Telegram chat or topic ID" },
    { key: "MLS_LOGIN_URL", label: "MLS login URL" },
    { key: "MLS_USERNAME", label: "MLS username or credential ref" },
    { key: "SKYSLOPE_USERNAME", label: "Compliance username or credential ref" },
    { key: "SHOWINGTIME_USERNAME", label: "Showing platform username or credential ref" },
    { key: "PHOTO_SOURCE_ROOT", label: "Photo source folder" },
  ],
  real_estate_sales: [
    { key: "CRM_API_KEY", label: "CRM API key", password: true },
    { key: "LOFTY_API_KEY", label: "Lofty API key", password: true },
    { key: "GMAIL_CLIENT_ID", label: "Email/OAuth client ID" },
    { key: "TWILIO_ACCOUNT_SID", label: "SMS account SID" },
    { key: "MLS_USERNAME", label: "Buyer search credential ref" },
  ],
  real_estate_marketing: [
    { key: "GMAIL_CLIENT_ID", label: "Email/OAuth client ID" },
    { key: "AYRSHARE_API_KEY", label: "Social scheduler key", password: true },
    { key: "GOOGLE_DRIVE_ACCOUNT", label: "Asset storage account/ref" },
    { key: "MARKETING_ASSET_ROOT", label: "Marketing asset folder" },
    { key: "PHOTO_SOURCE_ROOT", label: "Approved listing media folder" },
  ],
  real_estate_cma: [
    { key: "MLS_LOGIN_URL", label: "MLS/CMA login URL" },
    { key: "MLS_USERNAME", label: "MLS credential ref" },
    { key: "CLOUD_CMA_API_KEY", label: "Cloud CMA API key", password: true },
    { key: "CMA_TEMPLATE_PATH", label: "CMA template path" },
    { key: "CMA_OUTPUT_ROOT", label: "CMA output folder" },
  ],
};

const ADMIN_MIRROR_PACK_ID = "real_estate_admin";
const BASIC_PACK_ID = "elevate_core";

function badgeTone(ready: boolean, warning = false): ReadinessTone {
  if (ready) return "success";
  if (warning) return "warning";
  return "outline";
}

function statusCopy(ready: boolean, label: string, fallback = "Needs setup") {
  return ready ? label : fallback;
}

function formatTime(value: string | null | undefined) {
  return value ? isoTimeAgo(value) : "Never";
}

function DetailRow({
  icon: Icon,
  label,
  value,
  tone = "outline",
}: {
  icon: LucideIcon;
  label: string;
  value: ReactNode;
  tone?: ReadinessTone;
}) {
  return (
    <div className="flex items-center justify-between gap-3 rounded-md border border-border bg-card px-3 py-2">
      <div className="flex min-w-0 items-center gap-2 text-xs text-muted-foreground">
        <Icon className="h-3.5 w-3.5 shrink-0" />
        <span className="truncate">{label}</span>
      </div>
      <Badge variant={tone} className="max-w-[64%] truncate">
        {value}
      </Badge>
    </div>
  );
}

function SetupLink({
  children,
  to,
}: {
  children: ReactNode;
  to: string;
}) {
  return (
    <Link to={to} className={cn(buttonVariants({ variant: "outline", size: "sm" }), "shrink-0")}>
      {children}
    </Link>
  );
}

function ReadinessCard({
  action,
  children,
  description,
  icon: Icon,
  status,
  title,
  tone,
}: {
  action?: ReactNode;
  children: ReactNode;
  description: string;
  icon: LucideIcon;
  status: string;
  title: string;
  tone: ReadinessTone;
}) {
  return (
    <Card className="min-h-[17rem] bg-card">
      <CardHeader className="gap-3">
        <div className="flex items-start justify-between gap-3">
          <div className="flex min-w-0 items-start gap-3">
            <span className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-md border border-border bg-card text-muted-foreground">
              <Icon className="h-4 w-4" />
            </span>
            <div className="min-w-0">
              <CardTitle>{title}</CardTitle>
              <CardDescription>{description}</CardDescription>
            </div>
          </div>
          <Badge variant={tone}>{status}</Badge>
        </div>
        {action ? <div className="flex flex-wrap items-center gap-2">{action}</div> : null}
      </CardHeader>
      <CardContent className="space-y-2">{children}</CardContent>
    </Card>
  );
}

function RunwayStep({
  description,
  icon: Icon,
  label,
  tone,
}: {
  description: string;
  icon: LucideIcon;
  label: string;
  tone: ReadinessTone;
}) {
  const StatusIcon = tone === "success" ? CheckCircle2 : tone === "warning" ? AlertTriangle : CircleAlert;
  return (
    <div className="flex items-start gap-3 rounded-md border border-border bg-card px-3 py-3">
      <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-sm border border-border bg-card">
        <Icon className="h-3.5 w-3.5 text-muted-foreground" />
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex items-center justify-between gap-2">
          <div className="truncate text-sm font-medium text-foreground">{label}</div>
          <StatusIcon
            className={cn(
              "h-4 w-4 shrink-0",
              tone === "success" && "text-success",
              tone === "warning" && "text-warning",
              tone !== "success" && tone !== "warning" && "text-muted-foreground",
            )}
          />
        </div>
        <p className="mt-1 text-xs leading-5 text-muted-foreground">{description}</p>
      </div>
    </div>
  );
}

function AgentLaneRow({ agent }: { agent: AgentHubAgent }) {
  const lane = agent.telegramLane;
  const ready = Boolean(lane?.tokenConfigured && lane?.targetConfigured && !lane?.duplicateSharedBot);
  const warn = Boolean(lane?.duplicateSharedBot || lane?.usesSharedBot);
  return (
    <div className="rounded-md border border-border bg-card px-3 py-2">
      <div className="flex items-center justify-between gap-3">
        <div className="min-w-0">
          <div className="truncate text-sm font-medium text-foreground">{agent.name}</div>
          <div className="mt-0.5 truncate text-xs text-muted-foreground">{agent.id}</div>
        </div>
        <Badge variant={badgeTone(ready, warn)}>
          {ready ? "Separate lane" : warn ? "Shared lane" : "Needs lane"}
        </Badge>
      </div>
      <div className="mt-2 flex flex-wrap gap-1.5">
        <Badge variant={lane?.tokenConfigured ? "success" : "outline"}>bot token</Badge>
        <Badge variant={lane?.targetConfigured ? "success" : "outline"}>chat target</Badge>
        {lane?.topicConfigured ? <Badge variant="success">topic</Badge> : null}
      </div>
    </div>
  );
}

function safeHarness(value: AgentHubSnapshot["harness"] | HarnessSnapshot | null | undefined): HarnessSnapshot | null {
  if (!value || !("orchestration" in value)) return null;
  return value;
}

function packTone(pack: PackOnboardingPack): ReadinessTone {
  if (!pack.unlocked) return "outline";
  if (pack.complete) return "success";
  if (pack.completedRequiredCount > 0) return "warning";
  return "outline";
}

function recordValue(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : {};
}

function providerSeed(item: PackOnboardingItem): string {
  const value = recordValue(item.value);
  return String(item.provider || value.provider || "");
}

function PackUnlockOnboarding({
  adminSetup,
  notify,
  onSaved,
  snapshot,
}: {
  adminSetup: AdminSetupSnapshot | null;
  notify: (message: string, type: "success" | "error") => void;
  onSaved: () => Promise<void>;
  snapshot: PackOnboardingSnapshot | null;
}) {
  const packs = snapshot?.packs ?? [];
  const activePacks = packs.filter((pack) => pack.unlocked);
  const defaultPackId =
    activePacks.find((pack) => pack.launchRequired)?.packId ??
    activePacks.find((pack) => pack.packId === BASIC_PACK_ID)?.packId ??
    activePacks.find((pack) => pack.packId === ADMIN_MIRROR_PACK_ID)?.packId ??
    activePacks[0]?.packId ??
    packs[0]?.packId ??
    ADMIN_MIRROR_PACK_ID;
  const [selectedPackId, setSelectedPackId] = useState(defaultPackId);
  const [step, setStep] = useState<"celebrate" | "providers" | "credentials">("celebrate");
  const [saving, setSaving] = useState(false);
  const [providerValues, setProviderValues] = useState<Record<string, string>>({});
  const [notesValues, setNotesValues] = useState<Record<string, string>>({});
  const [envValues, setEnvValues] = useState<Record<string, string>>({});
  const [savedPulse, setSavedPulse] = useState(false);

  const selectedPack = packs.find((pack) => pack.packId === selectedPackId) ?? packs[0] ?? null;
  const credentialFields = selectedPack ? PACK_CREDENTIAL_FIELDS[selectedPack.packId] ?? [] : [];
  const visibleItems = selectedPack?.items ?? [];

  useEffect(() => {
    setSelectedPackId(defaultPackId);
  }, [defaultPackId]);

  useEffect(() => {
    if (!selectedPack) return;
    const nextProviders: Record<string, string> = {};
    const nextNotes: Record<string, string> = {};
    for (const item of selectedPack.items) {
      nextProviders[item.key] = providerSeed(item);
      nextNotes[item.key] = item.notes ?? "";
    }
    setProviderValues(nextProviders);
    setNotesValues(nextNotes);
    setEnvValues({});
    setStep("celebrate");
  }, [selectedPack?.packId, selectedPack?.updatedAt]);

  if (!snapshot || !selectedPack) {
    return null;
  }

  const unlockedTitle =
    selectedPack.packId === BASIC_PACK_ID
      ? "Congratulations on installing Elevate Basic"
      : selectedPack.unlocked
        ? `Congratulations on unlocking ${selectedPack.label}`
        : `${selectedPack.label} is locked`;
  const activeLabel = PACK_ACCENT[selectedPack.packId] ?? selectedPack.label;

  async function savePack() {
    if (!selectedPack) return;
    setSaving(true);
    setSavedPulse(false);
    try {
      const itemUpdates = visibleItems.map((item) => {
        const provider = providerValues[item.key]?.trim() ?? "";
        const notes = notesValues[item.key]?.trim() ?? "";
        return {
          key: item.key,
          status: provider || notes ? "configured" as const : "missing" as const,
          provider: provider || null,
          notes: notes || null,
          value: {
            provider: provider || null,
            envKeys: item.envKeys,
            source: "desktop_setup",
          },
        };
      });
      for (const [key, value] of Object.entries(envValues)) {
        if (!value.trim()) continue;
        await api.setEnvVar(key, value.trim());
      }
      await api.updatePackOnboarding(selectedPack.packId, { items: itemUpdates });
      if (selectedPack.packId === ADMIN_MIRROR_PACK_ID) {
        await api.updateAdminSetup({ items: itemUpdates });
        await api.verifyAdminSetup().catch(() => undefined);
      }
      await onSaved();
      setSavedPulse(true);
      setTimeout(() => setSavedPulse(false), 900);
      notify(`${selectedPack.label} onboarding saved.`, "success");
    } catch (error) {
      notify(error instanceof Error ? error.message : "Pack onboarding save failed", "error");
    } finally {
      setSaving(false);
    }
  }

  return (
    <section className="pack-unlock-shell overflow-hidden rounded-md border border-border bg-card">
      <div className="grid gap-0 xl:grid-cols-[21rem_minmax(0,1fr)]">
        <div className="border-b border-border/60 p-4 xl:border-b-0 xl:border-r">
          <div className="mb-3 flex items-center justify-between gap-2">
            <div>
              <div className="text-xs font-medium text-muted-foreground">Unlocked pack onboarding</div>
              <div className="text-lg font-semibold text-foreground">
                {snapshot.completedActiveCount}/{snapshot.activeCount} ready
              </div>
            </div>
            <Sparkles className="h-4 w-4 text-primary" />
          </div>
          <div className="space-y-2">
            {packs.map((pack, index) => {
              const selected = pack.packId === selectedPack.packId;
              return (
                <button
                  key={pack.packId}
                  type="button"
                  className={cn(
                    "pack-unlock-card group w-full rounded-md border px-3 py-3 text-left transition-colors",
                    selected
                      ? "border-primary bg-muted text-foreground"
                      : "border-border bg-card text-muted-foreground hover:bg-muted hover:text-foreground",
                    !pack.unlocked && "opacity-60",
                  )}
                  style={{ animationDelay: `${index * 70}ms` }}
                  onClick={() => {
                    setSelectedPackId(pack.packId);
                    setStep("celebrate");
                  }}
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="truncate text-sm font-semibold">{pack.label}</span>
                        {!pack.unlocked ? <LockKeyhole className="h-3.5 w-3.5" /> : null}
                      </div>
                      <div className="mt-1 text-xs leading-5 text-muted-foreground">
                        {pack.unlocked ? `${pack.completedRequiredCount}/${pack.requiredCount} fields ready` : "Unlock to configure"}
                      </div>
                    </div>
                    <Badge variant={packTone(pack)}>{pack.unlocked ? `${pack.completionPct}%` : "locked"}</Badge>
                  </div>
                </button>
              );
            })}
          </div>
        </div>

        <div className="min-w-0 p-4">
          <div className="relative overflow-hidden rounded-sm border border-border bg-card p-4">
            <div className="flex flex-wrap items-start justify-between gap-4">
              <div className="min-w-0">
                <Badge variant={selectedPack.unlocked ? "success" : "outline"}>{activeLabel}</Badge>
                <h3 className="mt-3 text-2xl font-semibold tracking-normal text-foreground">{unlockedTitle}</h3>
                <p className="mt-2 max-w-3xl text-sm leading-6 text-muted-foreground">
                  {selectedPack.packId === BASIC_PACK_ID
                    ? "Connect the model, memory, messaging, browser-use, and update settings that every Elevate install needs before paid packs start."
                    : selectedPack.unlocked
                      ? "Connect the providers and credential references this pack needs. Elevate stores the workflow contract in SQLite and saves secrets or account refs into the local .env file."
                      : "This pack stays hidden from production users until their license unlocks it."}
                </p>
              </div>
              <div className={cn("pack-unlock-check flex h-12 w-12 items-center justify-center rounded-sm border", savedPulse && "is-saved")}>
                <Sparkles className="h-5 w-5 text-primary" />
              </div>
            </div>

            <div className="mt-4 flex flex-wrap items-center gap-2">
              {(["celebrate", "providers", "credentials"] as const).map((name, index) => (
                <button
                  key={name}
                  type="button"
                  className={cn(
                    "inline-flex min-h-9 items-center gap-2 rounded-sm border px-3 text-xs font-medium transition-colors",
                    step === name
                      ? "border-primary bg-muted text-foreground"
                      : "border-border bg-card text-muted-foreground hover:text-foreground",
                  )}
                  onClick={() => setStep(name)}
                  disabled={!selectedPack.unlocked}
                >
                  <span>{index + 1}</span>
                  {name === "celebrate" ? "Unlock" : name === "providers" ? "Providers" : "Credentials"}
                </button>
              ))}
            </div>

            {step === "celebrate" ? (
              <div className="pack-step-enter mt-5 grid gap-4 lg:grid-cols-[minmax(0,1fr)_18rem]">
                <div className="rounded-md border border-border bg-card p-4">
                  <div className="text-sm font-semibold text-foreground">Before this pack can run</div>
                  <div className="mt-3 grid gap-2 sm:grid-cols-2">
                    {selectedPack.items.slice(0, 6).map((item) => (
                      <div key={item.key} className="rounded-md border border-border bg-card px-3 py-2">
                        <div className="truncate text-xs font-medium text-foreground">{item.label}</div>
                        <div className="mt-1 truncate text-xs text-muted-foreground">{item.status}</div>
                      </div>
                    ))}
                  </div>
                </div>
                <div className="flex flex-col justify-between rounded-md border border-border bg-card p-4">
                  <div>
                    <div className="text-sm font-semibold text-foreground">Next form</div>
                    <p className="mt-2 text-xs leading-5 text-muted-foreground">
                      Start with provider names, then add credential refs or keys. Nothing launches until the setup gate is ready.
                    </p>
                  </div>
                  <Button
                    className="mt-4 w-full"
                    disabled={!selectedPack.unlocked}
                    onClick={() => setStep("providers")}
                  >
                    Start setup
                    <ChevronRight className="h-3.5 w-3.5" />
                  </Button>
                </div>
              </div>
            ) : null}

            {step === "providers" ? (
              <div className="pack-step-enter mt-5 space-y-3">
                <div className="grid gap-3 md:grid-cols-2">
                  {visibleItems.map((item) => (
                    <label key={item.key} className="rounded-md border border-border bg-card p-3">
                      <span className="text-xs font-medium text-muted-foreground">{item.label}</span>
                      <Input
                        className="mt-2"
                        value={providerValues[item.key] ?? ""}
                        placeholder="Provider, account, or credential ref"
                        onChange={(event) =>
                          setProviderValues((prev) => ({ ...prev, [item.key]: event.target.value }))
                        }
                      />
                      <Input
                        className="mt-2"
                        value={notesValues[item.key] ?? ""}
                        placeholder="Notes for this workflow"
                        onChange={(event) =>
                          setNotesValues((prev) => ({ ...prev, [item.key]: event.target.value }))
                        }
                      />
                    </label>
                  ))}
                </div>
                <div className="flex flex-wrap justify-end gap-2">
                  <Button variant="outline" onClick={() => setStep("celebrate")}>Back</Button>
                  <Button onClick={() => setStep("credentials")}>
                    Continue
                    <ChevronRight className="h-3.5 w-3.5" />
                  </Button>
                </div>
              </div>
            ) : null}

            {step === "credentials" ? (
              <div className="pack-step-enter mt-5 space-y-3">
                <div className="rounded-md border border-border bg-card p-3 text-xs leading-5 text-muted-foreground">
                  Values entered here are saved through the dashboard env endpoint into the local Elevate `.env`. Use API keys,
                  tokens, account IDs, or credential refs. Avoid raw passwords unless the local operator explicitly wants that.
                </div>
                <div className="grid gap-3 md:grid-cols-2">
                  {credentialFields.map((field) => (
                    <label key={field.key} className="rounded-md border border-border bg-card p-3">
                      <span className="text-xs font-medium text-muted-foreground">{field.label}</span>
                      <Input
                        className="mt-2 font-mono-ui text-xs"
                        type={field.password ? "password" : "text"}
                        value={envValues[field.key] ?? ""}
                        placeholder={field.key}
                        onChange={(event) =>
                          setEnvValues((prev) => ({ ...prev, [field.key]: event.target.value }))
                        }
                      />
                    </label>
                  ))}
                </div>
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="text-xs text-muted-foreground">
                    {adminSetup?.memory?.synced ? "Admin memory is synced." : "Memory sync will update after save."}
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <Button variant="outline" onClick={() => setStep("providers")}>Back</Button>
                    <Button disabled={saving} onClick={() => void savePack()}>
                      {saving ? "Saving..." : "Save onboarding"}
                    </Button>
                  </div>
                </div>
              </div>
            ) : null}
          </div>
        </div>
      </div>
    </section>
  );
}

export default function DesktopSetupPage() {
  const [state, setState] = useState<LoadState>(EMPTY_STATE);
  const [loading, setLoading] = useState(true);
  const [actionName, setActionName] = useState<string | null>(null);
  const [updatedAt, setUpdatedAt] = useState<Date | null>(null);
  const { toast, showToast } = useToast();
  const { setAfterTitle, setEnd } = usePageHeader();

  const load = useCallback(async () => {
    setLoading(true);
    const [statusResult, accessResult, hubResult] = await Promise.allSettled([
      api.getStatus(),
      api.getAccessStatus(),
      api.getAgentHub({ lite: true }),
    ]);

    setState((prev) => ({
      ...prev,
      access: accessResult.status === "fulfilled" ? accessResult.value : prev.access,
      hub: hubResult.status === "fulfilled" ? hubResult.value : prev.hub,
      status: statusResult.status === "fulfilled" ? statusResult.value : prev.status,
    }));
    if (statusResult.status === "rejected" && hubResult.status === "rejected") {
      const reason = statusResult.reason instanceof Error ? statusResult.reason.message : "Desktop setup failed to load";
      showToast(reason, "error");
    }
    setLoading(false);
    setUpdatedAt(new Date());

    const [
      adminSetupResult,
      packOnboardingResult,
      oauthResult,
      connectorsResult,
      composioResult,
      harnessResult,
      updateStatusResult,
    ] = await Promise.allSettled([
      api.getAdminSetup(),
      api.getPackOnboarding(),
      api.getOAuthProviders(),
      api.getSourceConnectors(),
      api.getComposioStatus(),
      api.getHarness(),
      api.getUpdateStatus(),
    ]);

    setState((prev) => ({
      ...prev,
      adminSetup: adminSetupResult.status === "fulfilled" ? adminSetupResult.value : prev.adminSetup,
      composio: composioResult.status === "fulfilled" ? composioResult.value : prev.composio,
      connectors: connectorsResult.status === "fulfilled" ? connectorsResult.value : prev.connectors,
      harness: harnessResult.status === "fulfilled" ? harnessResult.value : prev.harness,
      oauth: oauthResult.status === "fulfilled" ? oauthResult.value : prev.oauth,
      packOnboarding: packOnboardingResult.status === "fulfilled" ? packOnboardingResult.value : prev.packOnboarding,
      updateStatus: updateStatusResult.status === "fulfilled" ? updateStatusResult.value : prev.updateStatus,
    }));
    setUpdatedAt(new Date());
  }, [showToast]);

  useEffect(() => {
    void load();
  }, [load]);

  const runAction = useCallback(
    async (name: "restart" | "update" | "verify" | "complete") => {
      setActionName(name);
      try {
        if (name === "restart") {
          await api.restartGateway();
          showToast("Gateway restart queued.", "success");
        } else if (name === "update") {
          await api.updateElevate();
          showToast("Update queued. Watch Logs for progress.", "success");
        } else if (name === "verify") {
          const next = await api.verifyAdminSetup();
          setState((prev) => ({ ...prev, adminSetup: next }));
          showToast("Admin setup verified.", "success");
        } else {
          const next = await api.completeAdminSetup();
          setState((prev) => ({ ...prev, adminSetup: next }));
          showToast("Admin setup marked complete.", "success");
        }
        await load();
      } catch (error) {
        showToast(error instanceof Error ? error.message : "Action failed", "error");
      } finally {
        setActionName(null);
      }
    },
    [load, showToast],
  );

  const requiredAgents = useMemo(
    () => state.hub?.agents.filter((agent) => REQUIRED_AGENT_IDS.has(agent.id)) ?? [],
    [state.hub],
  );
  const separateLaneCount = requiredAgents.filter(
    (agent) =>
      agent.telegramLane?.tokenConfigured &&
      agent.telegramLane?.targetConfigured &&
      !agent.telegramLane?.duplicateSharedBot,
  ).length;
  const lanesReady = requiredAgents.length >= REQUIRED_AGENT_IDS.size && separateLaneCount === requiredAgents.length;

  const oauthConnected = state.oauth?.providers.filter((provider) => provider.status.logged_in).length ?? 0;
  const sourceConnected = state.connectors?.connectors.filter((connector) => connector.connected).length ?? 0;
  const composioReady = Boolean(state.composio?.configured && state.composio.valid);
  const accountReady = composioReady || oauthConnected > 0 || sourceConnected > 0;

  const setup = state.adminSetup;
  const setupReady = Boolean(setup?.canStartAdmin || setup?.complete);
  const setupWarning = Boolean(setup && !setupReady && setup.completedRequiredCount > 0);
  const packSetupReady = Boolean(state.packOnboarding?.complete);
  const packSetupWarning = Boolean(
    state.packOnboarding && !packSetupReady && state.packOnboarding.completedActiveCount > 0,
  );
  const gatewayReady = Boolean(state.status?.gateway_running && state.hub?.gateway.running);
  const worker = state.hub?.agentWorker;
  const workerReady = Boolean(worker?.enabled && worker.state !== "error" && worker.state !== "disabled");
  const runtimeReady = gatewayReady && workerReady;
  const harness = safeHarness(state.harness ?? state.hub?.harness ?? null);
  const reliabilityReady = Boolean(harness || state.hub?.cron.total || state.hub?.memory.db_exists);
  const updatesAvailable = Boolean(state.updateStatus?.available && state.updateStatus.behind);

  const readySections = [packSetupReady, setupReady, runtimeReady, lanesReady, accountReady, reliabilityReady].filter(Boolean).length;
  const totalSections = 6;
  const overallReady = readySections === totalSections;

  useLayoutEffect(() => {
    setAfterTitle(
      <Badge variant={overallReady ? "success" : readySections >= 3 ? "warning" : "outline"}>
        {readySections}/{totalSections} ready
      </Badge>,
    );
    setEnd(
      <div className="flex items-center gap-2">
        {updatedAt ? (
          <span className="hidden text-xs text-muted-foreground sm:inline">Updated {updatedAt.toLocaleTimeString()}</span>
        ) : null}
        <Button variant="outline" size="sm" onClick={load} disabled={loading}>
          <RefreshCw className={cn("h-3.5 w-3.5", loading && "animate-spin")} />
          Refresh
        </Button>
      </div>,
    );
    return () => {
      setAfterTitle(null);
      setEnd(null);
    };
  }, [load, loading, overallReady, readySections, setAfterTitle, setEnd, updatedAt]);

  const handleAuthChange = useCallback(
    (authenticated: boolean) => {
      if (authenticated) void load();
    },
    [load],
  );

  if (loading && !state.status && !state.hub) {
    return (
      <p className="px-1 py-1 text-xs text-muted-foreground/80">Loading desktop setup…</p>
    );
  }

  return (
    <div className="normal-case flex flex-col gap-5 pb-4 tracking-normal">
      <Toast toast={toast} />

      <section className="grid gap-4 xl:grid-cols-2">
        <LoginCard onAuthChange={handleAuthChange} />
      </section>

      <section className="overflow-hidden rounded-md border border-border bg-card">
        <div className="grid gap-4 p-4 lg:grid-cols-[minmax(0,1fr)_24rem]">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <Badge variant={overallReady ? "success" : "warning"}>
                {overallReady ? "Production runway ready" : "Setup runway"}
              </Badge>
              <Badge variant={gatewayReady ? "success" : "outline"}>
                {state.status?.gateway_running ? "gateway online" : "gateway offline"}
              </Badge>
              <Badge variant={workerReady ? "success" : "outline"}>worker {worker?.state ?? "unknown"}</Badge>
              <Badge variant={lanesReady ? "success" : "warning"}>{separateLaneCount}/2 Telegram lanes</Badge>
              <Badge variant={updatesAvailable ? "warning" : "outline"}>
                {updatesAvailable ? `${state.updateStatus?.behind} updates available` : "up to date"}
              </Badge>
              <Badge variant={packSetupReady ? "success" : packSetupWarning ? "warning" : "outline"}>
                {state.packOnboarding?.activeCount ?? 0} packs active
              </Badge>
            </div>
            <h2 className="mt-4 text-2xl font-semibold tracking-normal text-foreground sm:text-3xl">
              Desktop setup
            </h2>
            <p className="mt-2 max-w-3xl text-sm leading-6 text-muted-foreground">
              One place to see whether this local Elevate install is actually ready to run for a realtor: runtime,
              separate agent inboxes, connected accounts, admin setup, and the logs needed to debug handoffs.
            </p>
            <div className="mt-4 flex flex-wrap gap-2">
              <Button
                variant="outline"
                size="sm"
                disabled={Boolean(actionName)}
                onClick={() => void runAction("restart")}
              >
                <RotateCw className={cn("h-3.5 w-3.5", actionName === "restart" && "animate-spin")} />
                Restart gateway
              </Button>
              <Button
                variant="outline"
                size="sm"
                disabled={Boolean(actionName)}
                onClick={() => void runAction("update")}
              >
                <RefreshCw className={cn("h-3.5 w-3.5", actionName === "update" && "animate-spin")} />
                {updatesAvailable ? "Updates available" : "Update"}
              </Button>
              <SetupLink to="/logs">
                <FileText className="h-3.5 w-3.5" />
                Logs
              </SetupLink>
              <SetupLink to="/project">
                <FolderOpen className="h-3.5 w-3.5" />
                Local files
              </SetupLink>
            </div>
          </div>

          <div className="grid gap-2">
            <RunwayStep
              icon={Sparkles}
              label="Unlocked pack onboarding"
              tone={packSetupReady ? "success" : packSetupWarning ? "warning" : "outline"}
              description={`${state.packOnboarding?.completedActiveCount ?? 0}/${state.packOnboarding?.activeCount ?? 0} active packs ready.`}
            />
            <RunwayStep
              icon={ShieldCheck}
              label="Admin setup"
              tone={setupReady ? "success" : setupWarning ? "warning" : "outline"}
              description={
                setup
                  ? `${setup.completedRequiredCount}/${setup.requiredCount} required setup items complete.`
                  : "Admin onboarding snapshot is not available yet."
              }
            />
            <RunwayStep
              icon={Terminal}
              label="Runtime loop"
              tone={runtimeReady ? "success" : gatewayReady ? "warning" : "outline"}
              description={`Gateway ${state.status?.gateway_state ?? "unknown"}; worker ${worker?.state ?? "unknown"}.`}
            />
            <RunwayStep
              icon={MessageSquare}
              label="Agent Telegram lanes"
              tone={lanesReady ? "success" : separateLaneCount > 0 ? "warning" : "outline"}
              description="Executive Assistant and Admin need separate bot tokens and chat targets."
            />
            <RunwayStep
              icon={KeyRound}
              label="Connected accounts"
              tone={accountReady ? "success" : "outline"}
              description={`${oauthConnected} OAuth, ${sourceConnected} source connector, Composio ${
                composioReady ? "ready" : "not ready"
              }.`}
            />
          </div>
        </div>
      </section>

      <PackUnlockOnboarding
        adminSetup={state.adminSetup}
        notify={showToast}
        snapshot={state.packOnboarding}
        onSaved={load}
      />

      <section className="grid gap-4 xl:grid-cols-2">
        <ReadinessCard
          icon={ShieldCheck}
          title="Realtor profile and admin launch"
          description="The source-of-truth setup gate before Admin starts moving files."
          status={statusCopy(setupReady, "Ready", setupWarning ? "Partial" : "Needs setup")}
          tone={badgeTone(setupReady, setupWarning)}
          action={
            <>
              <Button
                variant="outline"
                size="sm"
                disabled={Boolean(actionName)}
                onClick={() => void runAction("verify")}
              >
                <CheckCircle2 className={cn("h-3.5 w-3.5", actionName === "verify" && "animate-pulse")} />
                Verify
              </Button>
              <Button
                variant="outline"
                size="sm"
                disabled={Boolean(actionName) || !setup || Boolean(setup.missingRequiredKeys.length)}
                onClick={() => void runAction("complete")}
              >
                Complete setup
              </Button>
              <SetupLink to="/admin">Open Admin</SetupLink>
            </>
          }
        >
          <DetailRow
            icon={Settings}
            label="Province"
            value={setup?.profile.province || "Not set"}
            tone={setup?.profile.province ? "success" : "outline"}
          />
          <DetailRow
            icon={Activity}
            label="Market"
            value={setup?.profile.market || "Not set"}
            tone={setup?.profile.market ? "success" : "outline"}
          />
          <DetailRow
            icon={Database}
            label="Required items"
            value={`${setup?.completedRequiredCount ?? 0}/${setup?.requiredCount ?? 0}`}
            tone={setupReady ? "success" : setupWarning ? "warning" : "outline"}
          />
          <div className="rounded-md border border-border bg-card px-3 py-2">
            <div className="text-xs font-medium text-muted-foreground">Missing launch items</div>
            <div className="mt-2 flex flex-wrap gap-1.5">
              {setup?.missingRequiredKeys.length ? (
                setup.missingRequiredKeys.slice(0, 8).map((key) => (
                  <Badge key={key} variant="warning">
                    {key.replace(/_/g, " ")}
                  </Badge>
                ))
              ) : (
                <Badge variant="success">none</Badge>
              )}
            </div>
          </div>
        </ReadinessCard>

        <ReadinessCard
          icon={Terminal}
          title="Backend mode and wake loop"
          description="The local API, gateway, and handoff worker that keep agents alive."
          status={statusCopy(runtimeReady, "Running", gatewayReady ? "Worker check" : "Offline")}
          tone={badgeTone(runtimeReady, gatewayReady)}
          action={
            <>
              <SetupLink to="/hub">Agent Hub</SetupLink>
              <SetupLink to="/cron">Automations</SetupLink>
            </>
          }
        >
          <DetailRow
            icon={Terminal}
            label="Gateway"
            value={state.status?.gateway_state || "unknown"}
            tone={gatewayReady ? "success" : "outline"}
          />
          <DetailRow
            icon={Bot}
            label="Agent worker"
            value={worker?.state || "unknown"}
            tone={workerReady ? "success" : "outline"}
          />
          <DetailRow
            icon={Clock}
            label="Heartbeat"
            value={worker?.heartbeat?.enabled ? `next ${formatTime(worker.heartbeat.nextBeatAt)}` : "off"}
            tone={worker?.heartbeat?.enabled ? "success" : "outline"}
          />
          <DetailRow
            icon={Activity}
            label="Open handoffs"
            value={state.hub?.handoffs.open ?? 0}
            tone={(state.hub?.handoffs.failed ?? 0) > 0 ? "warning" : "success"}
          />
        </ReadinessCard>

        <ReadinessCard
          icon={MessageSquare}
          title="Agent communication lanes"
          description="Separate inboxes keep Admin from replying as the Executive Assistant."
          status={statusCopy(lanesReady, "Separated", separateLaneCount > 0 ? "Partial" : "Needs lanes")}
          tone={badgeTone(lanesReady, separateLaneCount > 0)}
          action={<SetupLink to="/hub">Configure lanes</SetupLink>}
        >
          {requiredAgents.length ? (
            requiredAgents.map((agent) => <AgentLaneRow key={agent.id} agent={agent} />)
          ) : (
            <div className="rounded-md border border-border bg-card px-3 py-3 text-sm text-muted-foreground">
              Agent Hub did not return the Executive Assistant/Admin agent definitions.
            </div>
          )}
        </ReadinessCard>

        <ReadinessCard
          icon={KeyRound}
          title="Connected accounts"
          description="Composio, OAuth, and source connectors that skills use during real workflows."
          status={statusCopy(accountReady, "Connected", "Needs accounts")}
          tone={badgeTone(accountReady)}
          action={
            <>
              <SetupLink to="/config">Connections</SetupLink>
              <SetupLink to="/env">Keys</SetupLink>
            </>
          }
        >
          <DetailRow
            icon={KeyRound}
            label="Composio"
            value={composioReady ? "ready" : state.composio?.configured ? "check failed" : "not configured"}
            tone={composioReady ? "success" : state.composio?.configured ? "warning" : "outline"}
          />
          <DetailRow
            icon={ShieldCheck}
            label="OAuth providers"
            value={`${oauthConnected}/${state.oauth?.providers.length ?? 0}`}
            tone={oauthConnected > 0 ? "success" : "outline"}
          />
          <DetailRow
            icon={Database}
            label="Source connectors"
            value={`${sourceConnected}/${state.connectors?.connectors.length ?? 0}`}
            tone={sourceConnected > 0 ? "success" : "outline"}
          />
          <DetailRow
            icon={Bot}
            label="Configured platforms"
            value={state.hub?.platforms.filter((platform) => platform.configured).length ?? 0}
            tone={(state.hub?.platforms.filter((platform) => platform.configured).length ?? 0) > 0 ? "success" : "outline"}
          />
        </ReadinessCard>

        <ReadinessCard
          icon={Database}
          title="Memory, runs, and recovery"
          description="The durability layer for handoffs, callbacks, traces, and source-of-truth state."
          status={statusCopy(reliabilityReady, "Visible", "Needs checks")}
          tone={badgeTone(reliabilityReady)}
          action={
            <>
              <SetupLink to="/memory">Memory</SetupLink>
              <SetupLink to="/logs">Logs</SetupLink>
              <SetupLink to="/tasks">Tasks</SetupLink>
            </>
          }
        >
          <DetailRow
            icon={Database}
            label="Memory database"
            value={state.hub?.memory.db_exists ? "present" : "missing"}
            tone={state.hub?.memory.db_exists ? "success" : "outline"}
          />
          <DetailRow
            icon={Activity}
            label="Cron jobs"
            value={`${state.hub?.cron.enabled ?? 0}/${state.hub?.cron.total ?? 0}`}
            tone={(state.hub?.cron.enabled ?? 0) > 0 ? "success" : "outline"}
          />
          <DetailRow
            icon={ShieldCheck}
            label="Harness"
            value={harness ? `${harness.orchestration.total_agents} agents` : "not visible"}
            tone={harness ? "success" : "outline"}
          />
          <DetailRow
            icon={Clock}
            label="Last worker tick"
            value={formatTime(worker?.lastTickAt)}
            tone={worker?.lastTickAt ? "success" : "outline"}
          />
        </ReadinessCard>

        <ReadinessCard
          icon={FolderOpen}
          title="Diagnostics and support"
          description="The desktop support surface: where to inspect state before touching a live deal."
          status="Available"
          tone="success"
          action={
            <>
              <SetupLink to="/project">Project</SetupLink>
              <SetupLink to="/analytics">Analytics</SetupLink>
            </>
          }
        >
          <DetailRow
            icon={FolderOpen}
            label="Project root"
            value={state.status?.project_root ? "visible" : "unknown"}
            tone={state.status?.project_root ? "success" : "outline"}
          />
          <DetailRow
            icon={Settings}
            label="Config"
            value={state.status?.config_version ?? "unknown"}
            tone={
              state.status && state.status.config_version === state.status.latest_config_version
                ? "success"
                : "warning"
            }
          />
          <DetailRow
            icon={KeyRound}
            label="Secrets file"
            value={state.status?.env_path ? "visible" : "unknown"}
            tone={state.status?.env_path ? "success" : "outline"}
          />
          <DetailRow
            icon={FileText}
            label="Release"
            value={state.status?.version ? `v${state.status.version}` : "unknown"}
            tone="outline"
          />
        </ReadinessCard>
      </section>
    </div>
  );
}
