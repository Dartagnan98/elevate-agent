import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";
import type {
  LeadsSetupItem,
  LeadsSetupSnapshot,
  OutreachTemplate,
  SourceConnectorStatus,
} from "@/lib/api-types";
import { playOnboardingChime } from "@/lib/onboarding-sounds";
import {
  buildItemUpdates,
  DEFAULT_AUTO_REPLY_TEMPLATE,
  errorMessage,
  isBrandNewLeadsSetup,
  leadsDraftFromSnapshot,
  OUTREACH_CONNECTOR_IDS,
  type LeadsSetupDraft,
} from "./onboarding-data";
import { LeadsSetupForm } from "./onboarding-form";
import { LeadsOnboardingGate, LeadsOnboardingWelcome } from "./onboarding-shell";
import { LeadsOnboardingWizard } from "./onboarding-wizard";

export { preloadLeadsSetup } from "./onboarding-data";
export { useLeadsSetup } from "./onboarding-state";

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
  const [phase, setPhase] = useState<"gate" | "welcome" | "wizard" | "form">(() =>
    forceOnboarding ? "welcome" : isBrandNewLeadsSetup(setup) ? "gate" : "form",
  );
  const [outreachSourceConnectors, setOutreachSourceConnectors] = useState<SourceConnectorStatus[]>([]);
  const [sourceConnectorsLoading, setSourceConnectorsLoading] = useState(true);
  const [firstTouchTemplates, setFirstTouchTemplates] = useState<OutreachTemplate[]>([]);

  const refreshSourceConnectors = useCallback(async () => {
    setSourceConnectorsLoading(true);
    try {
      const resp = await api.getSourceConnectors();
      const ids = new Set<string>(OUTREACH_CONNECTOR_IDS);
      setOutreachSourceConnectors(resp.connectors.filter((c) => ids.has(c.id)));
    } catch {
      // best-effort — leave previous list in place
    } finally {
      setSourceConnectorsLoading(false);
    }
  }, []);

  useEffect(() => {
    void refreshSourceConnectors();
  }, [refreshSourceConnectors]);

  const refreshTemplates = useCallback(async () => {
    try {
      const resp = await api.getOutreachTemplates();
      setFirstTouchTemplates(resp.templates.filter((t) => t.active));
    } catch {
      // best-effort
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const resp = await api.getOutreachTemplates();
        if (cancelled) return;
        const actives = resp.templates.filter((t) => t.active);
        setFirstTouchTemplates(actives);
        const policyVal = (setup.items.find((i) => i.key === "auto_reply_policy")?.value ?? {}) as Record<string, unknown>;
        const stored = String(policyVal.initialMessageTemplate ?? "").trim();
        const currentMatchesDefault = draft.autoReplyTemplate.trim() === DEFAULT_AUTO_REPLY_TEMPLATE.trim();
        const firstTouchDefault = actives.find((t) => t.lane === "new-outreach");
        if (firstTouchDefault && !stored && currentMatchesDefault) {
          setDraft((prev) => ({ ...prev, autoReplyTemplate: firstTouchDefault.body }));
        }
      } catch {
        // best-effort — empty list falls back to default opener
      }
    })();
    return () => {
      cancelled = true;
    };
    // intentional one-shot on mount — refetch is via refreshTemplates
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (forceOnboarding && phase === "form") {
      onForceOnboardingDone?.();
    }
  }, [forceOnboarding, phase, onForceOnboardingDone]);

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

  const crmStatus = crmItem?.status ?? "missing";
  const crmProvider = (crmItem?.provider || "").trim();
  const leadSourcesReady = setup.leadSourcesReady;
  const outreachReady = setup.outreachReady;
  const outreachConnectors = setup.outreachConnectors ?? [];

  const handleWizardFinish = useCallback(async () => {
    setError(null);
    setSavedMessage(null);
    try {
      await api.updateLeadsSetup(buildItemUpdates(draft));
    } catch (err) {
      setError(errorMessage(err, "Save failed"));
      return;
    }
    playOnboardingChime();
    setPhase("form");
  }, [draft]);

  if (phase === "gate") {
    return (
      <LeadsOnboardingGate
        onStart={() => setPhase("welcome")}
        onSkip={() => setPhase("form")}
      />
    );
  }

  if (phase === "welcome") {
    return <LeadsOnboardingWelcome onContinue={() => setPhase("wizard")} />;
  }

  if (phase === "wizard") {
    return (
      <LeadsOnboardingWizard
        draft={draft}
        updateField={updateField}
        onAdvanceSave={save}
        onFinish={handleWizardFinish}
        saving={saving}
        completing={completing}
        error={error}
        savedMessage={savedMessage}
        outreachSourceConnectors={outreachSourceConnectors}
        refreshSourceConnectors={refreshSourceConnectors}
        sourceConnectorsLoading={sourceConnectorsLoading}
        firstTouchTemplates={firstTouchTemplates}
        refreshTemplates={refreshTemplates}
      />
    );
  }

  return (
    <LeadsSetupForm
      setup={setup}
      draft={draft}
      updateField={updateField}
      onRunGuided={() => setPhase("welcome")}
      onSave={save}
      onMarkComplete={markComplete}
      saving={saving}
      completing={completing}
      error={error}
      savedMessage={savedMessage}
      forceOnboarding={forceOnboarding}
      crmStatus={crmStatus}
      crmProvider={crmProvider}
      metaStatus={metaItem?.status ?? "missing"}
      googleStatus={googleItem?.status ?? "missing"}
      webhookStatus={webhookItem?.status ?? "missing"}
      policyStatus={policyItem?.status ?? "missing"}
      leadSourcesReady={leadSourcesReady}
      outreachReady={outreachReady}
      outreachConnectors={outreachConnectors}
    />
  );
}
