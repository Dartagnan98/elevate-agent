import { AlertTriangle, ExternalLink, Loader2, Sparkles } from "lucide-react";

import { Button } from "@/components/ui/button";
import type {
  AdminSetupItemStatus,
  LeadsSetupSnapshot,
  OutreachConnectorRef,
} from "@/lib/api-types";
import { cn } from "@/lib/utils";

import type { LeadsSetupDraft } from "./onboarding-data";
import {
  FieldRow,
  ItemCard,
  OutreachConnectorsCard,
} from "./onboarding-form-parts";

export function LeadsSetupForm({
  setup,
  draft,
  updateField,
  onRunGuided,
  onSave,
  onMarkComplete,
  saving,
  completing,
  error,
  savedMessage,
  forceOnboarding,
  crmStatus,
  crmProvider,
  metaStatus,
  googleStatus,
  webhookStatus,
  policyStatus,
  leadSourcesReady,
  outreachReady,
  outreachConnectors,
}: {
  setup: LeadsSetupSnapshot;
  draft: LeadsSetupDraft;
  updateField: <K extends keyof LeadsSetupDraft>(key: K, value: LeadsSetupDraft[K]) => void;
  onRunGuided: () => void;
  onSave: () => Promise<void>;
  onMarkComplete: () => Promise<void>;
  saving: boolean;
  completing: boolean;
  error: string | null;
  savedMessage: string | null;
  forceOnboarding: boolean;
  crmStatus: AdminSetupItemStatus;
  crmProvider: string;
  metaStatus: AdminSetupItemStatus;
  googleStatus: AdminSetupItemStatus;
  webhookStatus: AdminSetupItemStatus;
  policyStatus: AdminSetupItemStatus;
  leadSourcesReady: boolean;
  outreachReady: boolean;
  outreachConnectors: OutreachConnectorRef[];
}) {
  const pct = setup.completionPct ?? 0;

  return (
    <div className="flex flex-col gap-4">
      <div className="rounded-md border border-border bg-card p-4">
        <div className="flex items-start justify-between gap-3">
          <div>
            <h2 className="text-[14px] font-semibold text-foreground">Leads onboarding</h2>
            <p className="mt-1 text-[12px] text-muted-foreground">
              CRM is inherited from Admin setup and already counts as an outreach lane. Wire at least one
              lead source (Meta / Google / Website webhook) and set your auto-reply policy. Texting channels
              (iMessage / SMS / RCS) are managed in Source Connectors below — Elevation auto-routes by lead device.
            </p>
          </div>
          <div className="flex flex-col items-end gap-2">
            <Button
              size="sm"
              variant="outline"
              onClick={onRunGuided}
              className="h-7 gap-1 px-2 text-[11px]"
            >
              <Sparkles className="h-3 w-3" />
              Run guided onboarding
            </Button>
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
            ? "Reading from admin_setup_profile.crm_provider. Manage in Admin → Connectors."
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
        description="Skip if you don't run Facebook / Instagram lead-form ads. One Pipeboard token — ad accounts, pages, and lead forms are auto-discovered."
        status={metaStatus}
      >
        <FieldRow
          label="MCP endpoint URL"
          value={draft.metaMcpEndpoint}
          onChange={(v) => updateField("metaMcpEndpoint", v)}
          placeholder="https://mcp.pipeboard.co/meta-ads-mcp"
        />
        <FieldRow
          label="Pipeboard API token"
          value={draft.metaMcpToken}
          onChange={(v) => updateField("metaMcpToken", v)}
          placeholder="••••••••"
          type="password"
        />
        <div className="flex flex-wrap items-center gap-3 text-[11.5px]">
          <a
            href="https://pipeboard.co/api-tokens"
            target="_blank"
            rel="noreferrer noopener"
            className="inline-flex items-center gap-1 text-primary underline-offset-2 hover:underline"
          >
            Get Pipeboard token (OAuth Facebook) <ExternalLink className="h-3 w-3" />
          </a>
          <a
            href="https://github.com/pipeboard-co/meta-ads-mcp"
            target="_blank"
            rel="noreferrer noopener"
            className="inline-flex items-center gap-1 text-muted-foreground underline-offset-2 hover:underline hover:text-foreground"
          >
            Install guide <ExternalLink className="h-3 w-3" />
          </a>
        </div>
      </ItemCard>

      <ItemCard
        title="Google Lead Form Ads (optional)"
        description="Skip if you don't run Google Ads. One developer token — Elevation's CLI auto-discovers your customer ID and campaigns."
        status={googleStatus}
      >
        <FieldRow
          label="Developer token"
          value={draft.googleDeveloperToken}
          onChange={(v) => updateField("googleDeveloperToken", v)}
          placeholder="abcDEF123-xyz"
          type="password"
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
        status={webhookStatus}
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
        status={policyStatus}
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
            ? "Lead source ready (CRM and/or ads connector)."
            : "Need at least one lead source connected — CRM, Meta, Google, or website webhook."}
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" onClick={() => void onSave()} disabled={saving || completing}>
            {saving ? <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" /> : null}
            Save
          </Button>
          <Button
            size="sm"
            onClick={() => void onMarkComplete()}
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
