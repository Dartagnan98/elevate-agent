import { useCallback, useEffect, useMemo, useState } from "react";
import { Loader2, CheckCircle2, Circle, AlertTriangle, ExternalLink, Sparkles, Link as LinkIcon } from "lucide-react";
import { Link } from "react-router-dom";
import { api } from "@/lib/api";
import type {
  AdminSetupItemStatus,
  LeadsSetupItem,
  LeadsSetupItemUpdate,
  LeadsSetupSnapshot,
  OutreachConnectorRef,
} from "@/lib/api-types";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

function errorMessage(err: unknown, fallback: string): string {
  if (err instanceof Error && err.message) return err.message;
  if (typeof err === "string" && err) return err;
  return fallback;
}

type LeadsSetupDraft = {
  metaProvider: string;
  metaAuthMethod: string;
  metaMcpEndpoint: string;
  metaMcpToken: string;
  metaAdAccountId: string;
  metaPageId: string;
  metaFormIds: string;
  googleProvider: string;
  googleDeveloperToken: string;
  googleCustomerId: string;
  webhookUrl: string;
  webhookSecret: string;
  autoReplyEnabled: boolean;
  autoReplyTemplate: string;
  followUpCadenceDays: string;
};

function leadsDraftFromSnapshot(snapshot: LeadsSetupSnapshot): LeadsSetupDraft {
  const byKey = new Map(snapshot.items.map((item) => [item.key, item]));
  const metaVal = (byKey.get("meta_lead_ads")?.value ?? {}) as Record<string, unknown>;
  const googleVal = (byKey.get("google_lead_forms")?.value ?? {}) as Record<string, unknown>;
  const webhookVal = (byKey.get("website_form_webhook")?.value ?? {}) as Record<string, unknown>;
  const policyVal = (byKey.get("auto_reply_policy")?.value ?? {}) as Record<string, unknown>;
  return {
    metaProvider: String(byKey.get("meta_lead_ads")?.provider ?? "") || "",
    metaAuthMethod: String(metaVal.authMethod ?? (metaVal.mcpEndpoint ? "mcp" : "webhook")),
    metaMcpEndpoint: String(metaVal.mcpEndpoint ?? ""),
    metaMcpToken: String(metaVal.mcpToken ?? ""),
    metaAdAccountId: String(metaVal.adAccountId ?? ""),
    metaPageId: String(metaVal.pageId ?? ""),
    metaFormIds: Array.isArray(metaVal.formIds) ? (metaVal.formIds as string[]).join(", ") : String(metaVal.formIds ?? ""),
    googleProvider: String(byKey.get("google_lead_forms")?.provider ?? "") || "",
    googleDeveloperToken: String(googleVal.developerToken ?? ""),
    googleCustomerId: String(googleVal.customerId ?? ""),
    webhookUrl: String(webhookVal.url ?? ""),
    webhookSecret: String(webhookVal.secret ?? ""),
    autoReplyEnabled: Boolean(policyVal.enabled ?? false),
    autoReplyTemplate: String(policyVal.initialMessageTemplate ?? ""),
    followUpCadenceDays: String(policyVal.followUpCadenceDays ?? "2"),
  };
}

function splitList(value: string): string[] {
  return value
    .split(/[,\n]/)
    .map((s) => s.trim())
    .filter(Boolean);
}

function buildItemUpdates(draft: LeadsSetupDraft): LeadsSetupItemUpdate[] {
  const metaReady = ((): boolean => {
    if (draft.metaAuthMethod === "mcp") {
      return Boolean(draft.metaMcpEndpoint.trim() && draft.metaMcpToken.trim());
    }
    return Boolean(
      draft.metaProvider.trim() &&
        (draft.metaAdAccountId.trim() || draft.metaPageId.trim() || draft.metaFormIds.trim()),
    );
  })();
  const googleReady = Boolean(
    draft.googleProvider.trim() && draft.googleDeveloperToken.trim() && draft.googleCustomerId.trim(),
  );
  const webhookReady = draft.webhookUrl.trim();
  const policyReady = Boolean(draft.autoReplyTemplate.trim()) || !draft.autoReplyEnabled;
  return [
    {
      key: "meta_lead_ads",
      status: (metaReady ? "configured" : "missing") as AdminSetupItemStatus,
      provider:
        draft.metaAuthMethod === "mcp"
          ? "meta_ads_mcp"
          : draft.metaProvider.trim() || null,
      value: {
        authMethod: draft.metaAuthMethod,
        mcpEndpoint: draft.metaMcpEndpoint.trim(),
        mcpToken: draft.metaMcpToken,
        adAccountId: draft.metaAdAccountId.trim(),
        pageId: draft.metaPageId.trim(),
        formIds: splitList(draft.metaFormIds),
      },
    },
    {
      key: "google_lead_forms",
      status: (googleReady ? "configured" : "missing") as AdminSetupItemStatus,
      provider: draft.googleProvider.trim() || null,
      value: {
        developerToken: draft.googleDeveloperToken,
        customerId: draft.googleCustomerId.trim(),
      },
    },
    {
      key: "website_form_webhook",
      status: (webhookReady ? "configured" : "missing") as AdminSetupItemStatus,
      provider: webhookReady ? "webhook" : null,
      value: {
        url: draft.webhookUrl.trim(),
        secret: draft.webhookSecret,
      },
    },
    {
      key: "auto_reply_policy",
      status: (policyReady ? "configured" : "missing") as AdminSetupItemStatus,
      provider: draft.autoReplyEnabled ? "elevate" : "off",
      value: {
        enabled: draft.autoReplyEnabled,
        initialMessageTemplate: draft.autoReplyTemplate.trim(),
        followUpCadenceDays: Number(draft.followUpCadenceDays) || 2,
      },
    },
  ];
}

function StatusBadge({ status }: { status: AdminSetupItemStatus }) {
  if (status === "connected" || status === "configured") {
    return (
      <span className="inline-flex items-center gap-1 rounded-md bg-success/15 px-1.5 py-0.5 text-[10.5px] font-medium text-success">
        <CheckCircle2 className="h-3 w-3" /> Connected
      </span>
    );
  }
  if (status === "manual") {
    return (
      <span className="inline-flex items-center gap-1 rounded-md bg-muted px-1.5 py-0.5 text-[10.5px] font-medium text-muted-foreground">
        <CheckCircle2 className="h-3 w-3" /> Manual
      </span>
    );
  }
  if (status === "skipped") {
    return (
      <span className="inline-flex items-center gap-1 rounded-md bg-muted px-1.5 py-0.5 text-[10.5px] font-medium text-muted-foreground">
        Skipped
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 rounded-md border border-warning/40 bg-warning/10 px-1.5 py-0.5 text-[10.5px] font-medium text-warning">
      <Circle className="h-3 w-3" /> Missing
    </span>
  );
}

function ItemCard({
  title,
  description,
  status,
  children,
}: {
  title: string;
  description: string;
  status: AdminSetupItemStatus;
  children?: React.ReactNode;
}) {
  return (
    <section className="rounded-md border border-border bg-card p-4">
      <header className="mb-2 flex items-start justify-between gap-3">
        <div>
          <h3 className="text-[13px] font-semibold text-foreground">{title}</h3>
          <p className="mt-0.5 text-[11.5px] text-muted-foreground">{description}</p>
        </div>
        <StatusBadge status={status} />
      </header>
      {children && <div className="mt-3 space-y-2">{children}</div>}
    </section>
  );
}

function FieldRow({
  label,
  value,
  onChange,
  placeholder,
  type = "text",
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  type?: string;
}) {
  return (
    <label className="block text-[11.5px] text-muted-foreground">
      <span className="mb-0.5 block">{label}</span>
      <input
        type={type}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className="w-full rounded-md border border-border bg-background px-2 py-1.5 text-[12.5px] text-foreground outline-none focus:border-primary focus:ring-1 focus:ring-primary/30"
      />
    </label>
  );
}

const OUTREACH_HINTS: Record<
  OutreachConnectorRef["id"],
  { tagline: string; routes: string }
> = {
  "apple-messages": {
    tagline: "iMessage from your Mac. Auto-picks blue-bubble route for iPhone leads.",
    routes: "Pairs with Messages.app via the existing local bridge — already syncing 237k+ records on this Mac.",
  },
  "sms-provider": {
    tagline: "Business SMS line (Twilio, Sinch, MessageBird, etc.) for non-iPhone leads.",
    routes: "Two-way SMS over a webhook/API. Use for green-bubble Android leads.",
  },
  "android-device": {
    tagline: "Personal Android device SMS via export or helper.",
    routes: "Backup/export route — does not claim live sync unless a helper is wired.",
  },
  "rcs": {
    tagline: "Rich messaging (read receipts, media, typing) for Android leads.",
    routes: "Business RCS provider or Twilio RCS. Personal-device RCS is import-only.",
  },
};

function ConnectorStatusBadge({ connector }: { connector: OutreachConnectorRef }) {
  if (connector.connected) {
    return (
      <span className="inline-flex items-center gap-1 rounded-md bg-success/15 px-1.5 py-0.5 text-[10.5px] font-medium text-success">
        <CheckCircle2 className="h-3 w-3" /> Connected
      </span>
    );
  }
  if (connector.importOnly) {
    return (
      <span className="inline-flex items-center gap-1 rounded-md bg-muted px-1.5 py-0.5 text-[10.5px] font-medium text-muted-foreground">
        <CheckCircle2 className="h-3 w-3" /> Import only
      </span>
    );
  }
  if (connector.blocked) {
    return (
      <span className="inline-flex items-center gap-1 rounded-md border border-destructive/40 bg-destructive/10 px-1.5 py-0.5 text-[10.5px] font-medium text-destructive">
        <AlertTriangle className="h-3 w-3" /> Blocked
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 rounded-md border border-warning/40 bg-warning/10 px-1.5 py-0.5 text-[10.5px] font-medium text-warning">
      <Circle className="h-3 w-3" /> Not configured
    </span>
  );
}

function OutreachConnectorsCard({
  connectors,
  outreachReady,
  crmStatus,
  crmProvider,
}: {
  connectors: OutreachConnectorRef[];
  outreachReady: boolean;
  crmStatus: AdminSetupItemStatus;
  crmProvider: string;
}) {
  return (
    <section className="rounded-md border border-border bg-card p-4">
      <header className="mb-3 flex items-start justify-between gap-3">
        <div>
          <h3 className="text-[13px] font-semibold text-foreground">Outreach channels</h3>
          <p className="mt-0.5 text-[11.5px] text-muted-foreground">
            iMessage, SMS, and RCS aren't configured here — they live as Source Connectors so the same wiring
            powers ingestion (read-only message index) and outbound. Elevate auto-routes: iPhone leads get
            iMessage, Android leads fall through to SMS / RCS.
          </p>
        </div>
        {outreachReady ? (
          <span className="inline-flex shrink-0 items-center gap-1 rounded-md bg-success/15 px-1.5 py-0.5 text-[10.5px] font-medium text-success">
            <CheckCircle2 className="h-3 w-3" /> Ready
            {crmStatus === "connected" && crmProvider ? ` (via ${crmProvider})` : ""}
          </span>
        ) : (
          <span className="inline-flex shrink-0 items-center gap-1 rounded-md border border-warning/40 bg-warning/10 px-1.5 py-0.5 text-[10.5px] font-medium text-warning">
            <Circle className="h-3 w-3" /> None active
          </span>
        )}
      </header>

      <div className="mb-3 flex flex-wrap items-center gap-2">
        <Link
          to="/config#connectors"
          className="inline-flex items-center gap-1 rounded-md border border-border bg-background px-2 py-1 text-[11.5px] font-medium text-foreground hover:bg-muted"
        >
          <LinkIcon className="h-3 w-3" />
          Open Source Connectors
        </Link>
        <span className="text-[10.5px] text-muted-foreground">
          Config → Source connectors. Each row below opens its setup task.
        </span>
      </div>

      <div className="space-y-1.5">
        {connectors.length === 0 ? (
          <p className="text-[11.5px] text-muted-foreground">
            Loading connector state…
          </p>
        ) : (
          connectors.map((connector) => {
            const hint = OUTREACH_HINTS[connector.id];
            return (
              <div
                key={connector.id}
                className="flex items-start justify-between gap-3 rounded-md border border-border/60 bg-muted/15 px-3 py-2"
              >
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className="text-[12.5px] font-medium text-foreground">{connector.label}</span>
                    <ConnectorStatusBadge connector={connector} />
                    {connector.totalRecords > 0 && (
                      <span className="text-[10.5px] text-muted-foreground">
                        {connector.totalRecords.toLocaleString()} records
                      </span>
                    )}
                  </div>
                  <p className="mt-0.5 truncate text-[11px] text-muted-foreground">{hint?.tagline}</p>
                  {connector.nextOperatorStep && !connector.connected && (
                    <p className="mt-1 text-[10.5px] text-muted-foreground/80">
                      Next: {connector.nextOperatorStep}
                    </p>
                  )}
                  {connector.lastError && (
                    <p className="mt-1 text-[10.5px] text-destructive/80">{connector.lastError}</p>
                  )}
                </div>
                <Link
                  to="/config#connectors"
                  className="inline-flex shrink-0 items-center gap-1 text-[11px] text-primary underline-offset-2 hover:underline"
                >
                  Configure <ExternalLink className="h-3 w-3" />
                </Link>
              </div>
            );
          })
        )}
      </div>
    </section>
  );
}

export function LeadsSetupLaunch({
  setup,
  onSetupUpdated,
  forceOnboarding = false,
  onForceOnboardingDone,
}: {
  setup: LeadsSetupSnapshot;
  onSetupUpdated: (next: LeadsSetupSnapshot) => void;
  forceOnboarding?: boolean;
  onForceOnboardingDone?: () => void;
}) {
  const [draft, setDraft] = useState<LeadsSetupDraft>(() => leadsDraftFromSnapshot(setup));
  const [saving, setSaving] = useState(false);
  const [completing, setCompleting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [savedMessage, setSavedMessage] = useState<string | null>(null);

  useEffect(() => {
    setDraft(leadsDraftFromSnapshot(setup));
  }, [setup]);

  const byKey = useMemo(() => new Map(setup.items.map((item: LeadsSetupItem) => [item.key, item])), [setup.items]);
  const crmItem = byKey.get("crm");
  const metaItem = byKey.get("meta_lead_ads");
  const googleItem = byKey.get("google_lead_forms");
  const webhookItem = byKey.get("website_form_webhook");
  const policyItem = byKey.get("auto_reply_policy");

  const save = useCallback(async () => {
    setSaving(true);
    setError(null);
    setSavedMessage(null);
    try {
      const updated = await api.updateLeadsSetup(buildItemUpdates(draft));
      onSetupUpdated(updated);
      setSavedMessage(
        updated.complete
          ? "Saved. Everything required is in — hit 'Mark complete' to lift the gate."
          : `Saved. ${updated.missingRequiredKeys.length} item(s) still required.`,
      );
    } catch (err) {
      setError(errorMessage(err, "Save failed"));
    } finally {
      setSaving(false);
    }
  }, [draft, onSetupUpdated]);

  const markComplete = useCallback(async () => {
    setCompleting(true);
    setError(null);
    setSavedMessage(null);
    try {
      await api.updateLeadsSetup(buildItemUpdates(draft));
      const completed = await api.completeLeadsSetup();
      onSetupUpdated(completed);
      onForceOnboardingDone?.();
    } catch (err) {
      setError(errorMessage(err, "Could not complete setup"));
    } finally {
      setCompleting(false);
    }
  }, [draft, onSetupUpdated, onForceOnboardingDone]);

  const updateField = useCallback(<K extends keyof LeadsSetupDraft>(key: K, value: LeadsSetupDraft[K]) => {
    setDraft((prev) => ({ ...prev, [key]: value }));
  }, []);

  const pct = setup.completionPct ?? 0;
  const crmStatus = crmItem?.status ?? "missing";
  const crmProvider = (crmItem?.provider || "").trim();
  const leadSourcesReady = setup.leadSourcesReady;
  const outreachReady = setup.outreachReady;
  const outreachConnectors = setup.outreachConnectors ?? [];

  return (
    <div className="flex flex-col gap-4">
      <div className="rounded-md border border-border bg-card p-4">
        <div className="flex items-start justify-between gap-3">
          <div>
            <h2 className="text-[14px] font-semibold text-foreground">Leads onboarding</h2>
            <p className="mt-1 text-[12px] text-muted-foreground">
              CRM is inherited from Admin setup and already counts as an outreach lane. Wire at least one
              lead source (Meta / Google / Website webhook) and set your auto-reply policy. Texting channels
              (iMessage / SMS / RCS) are managed in Source Connectors below — Elevate auto-routes by lead device.
            </p>
          </div>
          <div className="flex flex-col items-end gap-1">
            <span className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
              {setup.completedRequiredCount}/{setup.requiredCount} required
            </span>
            <div className="h-1.5 w-32 overflow-hidden rounded-full bg-muted">
              <div className="h-full bg-primary transition-all" style={{ width: `${pct}%` }} />
            </div>
            <span className="text-[10.5px] text-muted-foreground">{pct}%</span>
          </div>
        </div>
        {forceOnboarding && (
          <div className="mt-3 inline-flex items-center gap-1 rounded-md bg-muted px-2 py-0.5 text-[10.5px] text-muted-foreground">
            <Sparkles className="h-3 w-3" /> Re-running onboarding — existing state preserved
          </div>
        )}
      </div>

      {error && (
        <div className="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-[12px] text-destructive">
          <AlertTriangle className="mr-1 inline h-3.5 w-3.5" />
          {error}
        </div>
      )}
      {savedMessage && (
        <div className="rounded-md border border-border bg-muted/30 px-3 py-2 text-[12px] text-muted-foreground">
          {savedMessage}
        </div>
      )}

      <ItemCard
        title="CRM (inherited from Admin)"
        description={
          crmProvider
            ? `Reading from admin_setup_profile.crm_provider. Manage in Admin → Connectors.`
            : "No CRM set in Admin yet. Finish Admin onboarding first — Leads can't store contacts without a CRM."
        }
        status={crmStatus}
      >
        <div className="text-[12px] text-foreground">
          {crmProvider ? `Connected to ${crmProvider}.` : "Not configured."}
        </div>
      </ItemCard>

      <ItemCard
        title="Meta Lead Ads (optional)"
        description="Skip if you don't run Facebook / Instagram lead-form ads. Auth via the official Meta Ads MCP (recommended — one token, no webhook plumbing) or the legacy page-token webhook."
        status={metaItem?.status ?? "missing"}
      >
        <label className="block text-[11.5px] text-muted-foreground">
          <span className="mb-0.5 block">Auth method</span>
          <select
            value={draft.metaAuthMethod}
            onChange={(e) => updateField("metaAuthMethod", e.target.value)}
            className="w-full rounded-md border border-border bg-background px-2 py-1.5 text-[12.5px] text-foreground outline-none focus:border-primary focus:ring-1 focus:ring-primary/30"
          >
            <option value="mcp">Meta Ads MCP (recommended)</option>
            <option value="webhook">Page-token webhook (legacy)</option>
          </select>
        </label>
        {draft.metaAuthMethod === "mcp" ? (
          <>
            <FieldRow
              label="MCP endpoint URL"
              value={draft.metaMcpEndpoint}
              onChange={(v) => updateField("metaMcpEndpoint", v)}
              placeholder="https://mcp.meta.com/ads  (or self-hosted)"
            />
            <FieldRow
              label="MCP access token"
              value={draft.metaMcpToken}
              onChange={(v) => updateField("metaMcpToken", v)}
              placeholder="••••••••"
              type="password"
            />
            <a
              href="https://github.com/pipeboard-co/meta-ads-mcp"
              target="_blank"
              rel="noreferrer noopener"
              className="inline-flex items-center gap-1 text-[11.5px] text-primary underline-offset-2 hover:underline"
            >
              Meta Ads MCP install guide <ExternalLink className="h-3 w-3" />
            </a>
          </>
        ) : (
          <>
            <FieldRow
              label="Provider name (free text)"
              value={draft.metaProvider}
              onChange={(v) => updateField("metaProvider", v)}
              placeholder="Meta Business Manager"
            />
            <FieldRow
              label="Ad account ID"
              value={draft.metaAdAccountId}
              onChange={(v) => updateField("metaAdAccountId", v)}
              placeholder="act_1234567890"
            />
            <FieldRow
              label="Page ID"
              value={draft.metaPageId}
              onChange={(v) => updateField("metaPageId", v)}
              placeholder="987654321"
            />
            <FieldRow
              label="Lead form IDs (comma separated)"
              value={draft.metaFormIds}
              onChange={(v) => updateField("metaFormIds", v)}
              placeholder="form_001, form_002"
            />
            <a
              href="https://business.facebook.com/leadgen_central"
              target="_blank"
              rel="noreferrer noopener"
              className="inline-flex items-center gap-1 text-[11.5px] text-primary underline-offset-2 hover:underline"
            >
              Open Meta Lead Ads Manager <ExternalLink className="h-3 w-3" />
            </a>
          </>
        )}
      </ItemCard>

      <ItemCard
        title="Google Lead Form Ads (optional)"
        description="Skip if you don't run Google Ads. Developer token + customer ID is enough — Elevate auto-discovers your campaigns."
        status={googleItem?.status ?? "missing"}
      >
        <FieldRow
          label="Provider name"
          value={draft.googleProvider}
          onChange={(v) => updateField("googleProvider", v)}
          placeholder="Google Ads"
        />
        <FieldRow
          label="Developer token"
          value={draft.googleDeveloperToken}
          onChange={(v) => updateField("googleDeveloperToken", v)}
          placeholder="abcDEF123-xyz"
          type="password"
        />
        <FieldRow
          label="Customer ID"
          value={draft.googleCustomerId}
          onChange={(v) => updateField("googleCustomerId", v)}
          placeholder="123-456-7890"
        />
        <a
          href="https://developers.google.com/google-ads/api/docs/get-started/dev-token"
          target="_blank"
          rel="noreferrer noopener"
          className="inline-flex items-center gap-1 text-[11.5px] text-primary underline-offset-2 hover:underline"
        >
          How to get a Google Ads developer token <ExternalLink className="h-3 w-3" />
        </a>
      </ItemCard>

      <ItemCard
        title="Website form webhook"
        description="Catch-all webhook URL for landing-page and contact-us form submissions."
        status={webhookItem?.status ?? "missing"}
      >
        <FieldRow
          label="Webhook URL (POST endpoint for your form provider)"
          value={draft.webhookUrl}
          onChange={(v) => updateField("webhookUrl", v)}
          placeholder="https://elevate.yourdomain.com/api/leads/inbound"
        />
        <FieldRow
          label="Shared secret (optional — for HMAC verification)"
          value={draft.webhookSecret}
          onChange={(v) => updateField("webhookSecret", v)}
          placeholder="optional"
          type="password"
        />
      </ItemCard>

      <OutreachConnectorsCard
        connectors={outreachConnectors}
        outreachReady={outreachReady}
        crmStatus={crmStatus}
        crmProvider={crmProvider}
      />

      <ItemCard
        title="Auto-reply policy"
        description="Initial-touch behaviour and follow-up cadence default."
        status={policyItem?.status ?? "missing"}
      >
        <label className="flex items-center gap-2 text-[12px] text-foreground">
          <input
            type="checkbox"
            checked={draft.autoReplyEnabled}
            onChange={(e) => updateField("autoReplyEnabled", e.target.checked)}
            className="h-3.5 w-3.5 rounded border-border accent-primary"
          />
          Send an automated first reply when a lead lands
        </label>
        <label className="block text-[11.5px] text-muted-foreground">
          <span className="mb-0.5 block">Initial reply template</span>
          <textarea
            value={draft.autoReplyTemplate}
            onChange={(e) => updateField("autoReplyTemplate", e.target.value)}
            rows={3}
            placeholder="Hey {{firstName}} — thanks for reaching out. What's the property address or area you're looking at?"
            className="w-full resize-y rounded-md border border-border bg-background px-2 py-1.5 text-[12.5px] leading-5 text-foreground outline-none focus:border-primary focus:ring-1 focus:ring-primary/30"
          />
        </label>
        <FieldRow
          label="Follow-up cadence (days between nudges)"
          value={draft.followUpCadenceDays}
          onChange={(v) => updateField("followUpCadenceDays", v)}
          placeholder="2"
          type="number"
        />
      </ItemCard>

      <div className="sticky bottom-2 z-10 flex flex-wrap items-center justify-between gap-2 rounded-md border border-border bg-card/95 px-3 py-2 backdrop-blur">
        <div className="text-[11.5px] text-muted-foreground">
          {leadSourcesReady
            ? "At least one lead source is ready."
            : "Need at least one lead source connected before the gate lifts."}
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" onClick={() => void save()} disabled={saving || completing}>
            {saving ? <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" /> : null}
            Save
          </Button>
          <Button
            size="sm"
            onClick={() => void markComplete()}
            disabled={completing || saving || setup.requiredCount === 0}
            className={cn(setup.complete ? "" : "opacity-95")}
          >
            {completing ? <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" /> : null}
            Mark complete
          </Button>
        </div>
      </div>
    </div>
  );
}

export function useLeadsSetup(): {
  loading: boolean;
  setup: LeadsSetupSnapshot | null;
  error: string | null;
  setSetup: (next: LeadsSetupSnapshot) => void;
  refresh: () => Promise<void>;
} {
  const [setup, setSetup] = useState<LeadsSetupSnapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const snap = await api.getLeadsSetup();
      setSetup(snap);
    } catch (err) {
      setError(errorMessage(err, "Could not load leads setup"));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  return { loading, setup, error, setSetup, refresh };
}
