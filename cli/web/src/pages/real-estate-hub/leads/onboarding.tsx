import { useCallback, useEffect, useMemo, useState } from "react";
import { Loader2, CheckCircle2, Circle, AlertTriangle, ExternalLink, Sparkles } from "lucide-react";
import { api } from "@/lib/api";
import type {
  AdminSetupItemStatus,
  LeadsSetupItem,
  LeadsSetupItemUpdate,
  LeadsSetupSnapshot,
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
  metaAdAccountId: string;
  metaPageId: string;
  metaFormIds: string;
  googleProvider: string;
  googleCustomerId: string;
  googleCampaignIds: string;
  webhookUrl: string;
  webhookSecret: string;
  imessageEnabled: boolean;
  imessageHandle: string;
  smsProvider: string;
  smsFromNumber: string;
  smsTwilioAccountSid: string;
  smsTwilioAuthToken: string;
  rcsProvider: string;
  rcsFromNumber: string;
  autoReplyEnabled: boolean;
  autoReplyTemplate: string;
  followUpCadenceDays: string;
};

function leadsDraftFromSnapshot(snapshot: LeadsSetupSnapshot): LeadsSetupDraft {
  const byKey = new Map(snapshot.items.map((item) => [item.key, item]));
  const metaVal = (byKey.get("meta_lead_ads")?.value ?? {}) as Record<string, unknown>;
  const googleVal = (byKey.get("google_lead_forms")?.value ?? {}) as Record<string, unknown>;
  const webhookVal = (byKey.get("website_form_webhook")?.value ?? {}) as Record<string, unknown>;
  const imessageItem = byKey.get("outreach_imessage");
  const imessageVal = (imessageItem?.value ?? {}) as Record<string, unknown>;
  const smsItem = byKey.get("outreach_sms");
  const smsVal = (smsItem?.value ?? {}) as Record<string, unknown>;
  const rcsItem = byKey.get("outreach_rcs");
  const rcsVal = (rcsItem?.value ?? {}) as Record<string, unknown>;
  const policyVal = (byKey.get("auto_reply_policy")?.value ?? {}) as Record<string, unknown>;
  return {
    metaProvider: String(byKey.get("meta_lead_ads")?.provider ?? "") || "",
    metaAdAccountId: String(metaVal.adAccountId ?? ""),
    metaPageId: String(metaVal.pageId ?? ""),
    metaFormIds: Array.isArray(metaVal.formIds) ? (metaVal.formIds as string[]).join(", ") : String(metaVal.formIds ?? ""),
    googleProvider: String(byKey.get("google_lead_forms")?.provider ?? "") || "",
    googleCustomerId: String(googleVal.customerId ?? ""),
    googleCampaignIds: Array.isArray(googleVal.campaignIds) ? (googleVal.campaignIds as string[]).join(", ") : String(googleVal.campaignIds ?? ""),
    webhookUrl: String(webhookVal.url ?? ""),
    webhookSecret: String(webhookVal.secret ?? ""),
    imessageEnabled: imessageItem ? imessageItem.status !== "missing" : Boolean(imessageVal.enabled),
    imessageHandle: String(imessageVal.handle ?? ""),
    smsProvider: String(smsItem?.provider ?? "") || "",
    smsFromNumber: String(smsVal.fromNumber ?? ""),
    smsTwilioAccountSid: String(smsVal.accountSid ?? ""),
    smsTwilioAuthToken: String(smsVal.authToken ?? ""),
    rcsProvider: String(rcsItem?.provider ?? "") || "",
    rcsFromNumber: String(rcsVal.fromNumber ?? ""),
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
  const metaReady =
    draft.metaProvider.trim() &&
    (draft.metaAdAccountId.trim() || draft.metaPageId.trim() || draft.metaFormIds.trim());
  const googleReady =
    draft.googleProvider.trim() &&
    (draft.googleCustomerId.trim() || draft.googleCampaignIds.trim());
  const webhookReady = draft.webhookUrl.trim();
  const policyReady = Boolean(draft.autoReplyTemplate.trim()) || !draft.autoReplyEnabled;
  return [
    {
      key: "meta_lead_ads",
      status: (metaReady ? "configured" : "missing") as AdminSetupItemStatus,
      provider: draft.metaProvider.trim() || null,
      value: {
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
        customerId: draft.googleCustomerId.trim(),
        campaignIds: splitList(draft.googleCampaignIds),
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
      key: "outreach_imessage",
      status: (draft.imessageEnabled ? "configured" : "missing") as AdminSetupItemStatus,
      provider: draft.imessageEnabled ? "apple_messages" : null,
      value: {
        enabled: draft.imessageEnabled,
        handle: draft.imessageHandle.trim(),
      },
    },
    {
      key: "outreach_sms",
      status: ((): AdminSetupItemStatus => {
        const provider = draft.smsProvider.trim();
        if (!provider) return "missing";
        if (provider === "twilio") {
          return draft.smsTwilioAccountSid.trim() && draft.smsTwilioAuthToken.trim() && draft.smsFromNumber.trim()
            ? "configured"
            : "missing";
        }
        return draft.smsFromNumber.trim() ? "configured" : "missing";
      })(),
      provider: draft.smsProvider.trim() || null,
      value: {
        fromNumber: draft.smsFromNumber.trim(),
        accountSid: draft.smsTwilioAccountSid.trim(),
        authToken: draft.smsTwilioAuthToken,
      },
    },
    {
      key: "outreach_rcs",
      status: ((): AdminSetupItemStatus => {
        const provider = draft.rcsProvider.trim();
        if (!provider) return "missing";
        return draft.rcsFromNumber.trim() ? "configured" : "missing";
      })(),
      provider: draft.rcsProvider.trim() || null,
      value: {
        fromNumber: draft.rcsFromNumber.trim(),
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
  const imessageItem = byKey.get("outreach_imessage");
  const smsItem = byKey.get("outreach_sms");
  const rcsItem = byKey.get("outreach_rcs");

  return (
    <div className="flex flex-col gap-4">
      <div className="rounded-md border border-border bg-card p-4">
        <div className="flex items-start justify-between gap-3">
          <div>
            <h2 className="text-[14px] font-semibold text-foreground">Leads onboarding</h2>
            <p className="mt-1 text-[12px] text-muted-foreground">
              CRM is inherited from Admin setup. Wire at least one lead source (Meta / Google / Website webhook),
              pick at least one outreach channel (iMessage / SMS / Twilio / RCS), and set your auto-reply policy.
              Once those are in, hit Mark complete to unlock the Leads workspace.
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
        title="Meta Lead Ads"
        description="Facebook / Instagram lead-form ads. Forms post directly into Elevate via the Meta webhook."
        status={metaItem?.status ?? "missing"}
      >
        <FieldRow
          label="Provider name (free text — e.g. Meta Business Manager)"
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
      </ItemCard>

      <ItemCard
        title="Google Lead Form Ads"
        description="Lead-form extensions on Google Ads search/display campaigns."
        status={googleItem?.status ?? "missing"}
      >
        <FieldRow
          label="Provider name"
          value={draft.googleProvider}
          onChange={(v) => updateField("googleProvider", v)}
          placeholder="Google Ads"
        />
        <FieldRow
          label="Customer ID"
          value={draft.googleCustomerId}
          onChange={(v) => updateField("googleCustomerId", v)}
          placeholder="123-456-7890"
        />
        <FieldRow
          label="Campaign IDs (comma separated)"
          value={draft.googleCampaignIds}
          onChange={(v) => updateField("googleCampaignIds", v)}
          placeholder="11111111, 22222222"
        />
        <a
          href="https://ads.google.com"
          target="_blank"
          rel="noreferrer noopener"
          className="inline-flex items-center gap-1 text-[11.5px] text-primary underline-offset-2 hover:underline"
        >
          Open Google Ads <ExternalLink className="h-3 w-3" />
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

      <div className="rounded-md border border-border bg-muted/20 px-3 py-2 text-[11.5px] text-muted-foreground">
        <span className="font-medium text-foreground">Outreach channels.</span> Pick how you actually message leads.
        At least one needs to be enabled.{" "}
        {outreachReady ? (
          <span className="text-success">Ready.</span>
        ) : (
          <span className="text-warning">No channel picked yet.</span>
        )}
      </div>

      <ItemCard
        title="Apple Messages (iMessage)"
        description="Send and receive via iMessage from your Mac. Best when leads are iPhone users — keeps blue-bubble UX."
        status={imessageItem?.status ?? "missing"}
      >
        <label className="flex items-center gap-2 text-[12px] text-foreground">
          <input
            type="checkbox"
            checked={draft.imessageEnabled}
            onChange={(e) => updateField("imessageEnabled", e.target.checked)}
            className="h-3.5 w-3.5 rounded border-border accent-primary"
          />
          Use iMessage for outbound replies
        </label>
        <FieldRow
          label="iMessage handle (your Apple ID email or phone number)"
          value={draft.imessageHandle}
          onChange={(v) => updateField("imessageHandle", v)}
          placeholder="you@icloud.com  or  +12505551234"
        />
        <p className="text-[10.5px] text-muted-foreground">
          Requires Messages.app signed in on this Mac. Elevate sends via AppleScript from the local runtime.
        </p>
      </ItemCard>

      <ItemCard
        title="SMS / Twilio"
        description="Plain text messaging. Use Twilio for a dedicated business line, otherwise your phone's native SMS."
        status={smsItem?.status ?? "missing"}
      >
        <label className="block text-[11.5px] text-muted-foreground">
          <span className="mb-0.5 block">Provider</span>
          <select
            value={draft.smsProvider}
            onChange={(e) => updateField("smsProvider", e.target.value)}
            className="w-full rounded-md border border-border bg-background px-2 py-1.5 text-[12.5px] text-foreground outline-none focus:border-primary focus:ring-1 focus:ring-primary/30"
          >
            <option value="">— pick one —</option>
            <option value="twilio">Twilio</option>
            <option value="native_sms">Native SMS (Mac Messages / phone modem)</option>
            <option value="google_voice">Google Voice</option>
          </select>
        </label>
        <FieldRow
          label="From number (E.164 format)"
          value={draft.smsFromNumber}
          onChange={(v) => updateField("smsFromNumber", v)}
          placeholder="+12505551234"
        />
        {draft.smsProvider === "twilio" && (
          <>
            <FieldRow
              label="Twilio Account SID"
              value={draft.smsTwilioAccountSid}
              onChange={(v) => updateField("smsTwilioAccountSid", v)}
              placeholder="ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
            />
            <FieldRow
              label="Twilio Auth Token"
              value={draft.smsTwilioAuthToken}
              onChange={(v) => updateField("smsTwilioAuthToken", v)}
              placeholder="••••••••"
              type="password"
            />
            <a
              href="https://console.twilio.com/"
              target="_blank"
              rel="noreferrer noopener"
              className="inline-flex items-center gap-1 text-[11.5px] text-primary underline-offset-2 hover:underline"
            >
              Open Twilio Console <ExternalLink className="h-3 w-3" />
            </a>
          </>
        )}
      </ItemCard>

      <ItemCard
        title="RCS"
        description="Rich messaging for Android leads (read receipts, typing indicators, media). Falls back to SMS automatically."
        status={rcsItem?.status ?? "missing"}
      >
        <label className="block text-[11.5px] text-muted-foreground">
          <span className="mb-0.5 block">Provider</span>
          <select
            value={draft.rcsProvider}
            onChange={(e) => updateField("rcsProvider", e.target.value)}
            className="w-full rounded-md border border-border bg-background px-2 py-1.5 text-[12.5px] text-foreground outline-none focus:border-primary focus:ring-1 focus:ring-primary/30"
          >
            <option value="">— pick one —</option>
            <option value="google_rcs">Google Business Messages / RCS</option>
            <option value="twilio_rcs">Twilio RCS</option>
          </select>
        </label>
        <FieldRow
          label="Sender phone number (E.164 format)"
          value={draft.rcsFromNumber}
          onChange={(v) => updateField("rcsFromNumber", v)}
          placeholder="+12505551234"
        />
      </ItemCard>

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
