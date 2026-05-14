import type { AdminSetupItemStatus, AdminSetupSnapshot } from "@/lib/api";

export type AdminSetupDraft = {
  realtorLegalName: string;
  licenseName: string;
  brokerageName: string;
  teamName: string;
  province: string;
  market: string;
  boardMemberships: string;
  managingBrokerEmail: string;
  approvalChannel: string;
  emailProvider: string;
  calendarProvider: string;
  driveProvider: string;
  crmProvider: string;
  mlsProvider: string;
  formsProvider: string;
  signingProvider: string;
  complianceProvider: string;
  showingProvider: string;
  photoProcessingProvider: string;
  mlsLoginUrl: string;
  mlsLoginEmail: string;
  mlsLoginPassword: string;
  complianceLoginUrl: string;
  complianceLoginEmail: string;
  complianceLoginPassword: string;
  showingLoginUrl: string;
  showingLoginEmail: string;
  showingLoginPassword: string;
  browserWorkflowNotes: string;
  fintracProvider: string;
  defaultFolderPattern: string;
  commissionNotes: string;
  servicesSchedule: string;
  regionalMemory: string;
  approvalPolicy: string;
};

export const ADMIN_SETUP_PROVIDER_ITEMS: Array<{
  key: string;
  field: keyof AdminSetupDraft;
  status: AdminSetupItemStatus;
}> = [
  { key: "approval_channel", field: "approvalChannel", status: "connected" },
  { key: "email", field: "emailProvider", status: "connected" },
  { key: "calendar", field: "calendarProvider", status: "connected" },
  { key: "drive", field: "driveProvider", status: "connected" },
  { key: "crm", field: "crmProvider", status: "connected" },
  { key: "mls", field: "mlsProvider", status: "connected" },
  { key: "forms_provider", field: "formsProvider", status: "configured" },
  { key: "signing_provider", field: "signingProvider", status: "configured" },
  { key: "compliance_platform", field: "complianceProvider", status: "configured" },
  { key: "showing_platform", field: "showingProvider", status: "configured" },
  { key: "photo_processing", field: "photoProcessingProvider", status: "configured" },
  { key: "fintrac_workflow", field: "fintracProvider", status: "manual" },
];

export function setupRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

export function setupString(value: unknown): string {
  return typeof value === "string" ? value : "";
}

export function adminSetupDraftFromSnapshot(setup: AdminSetupSnapshot): AdminSetupDraft {
  const profile = setup.profile;
  const itemsByKey = new Map(setup.items.map((item) => [item.key, item]));
  const photoValue = setupRecord(itemsByKey.get("photo_processing")?.value);
  const browserValue = setupRecord(itemsByKey.get("browser_workflows")?.value);
  const playbooks = setupRecord(browserValue.playbooks);
  const mlsPlaybook = setupRecord(playbooks.mls);
  const compliancePlaybook = setupRecord(playbooks.compliance);
  const showingPlaybook = setupRecord(playbooks.showing);
  const regionalMemory = profile.regionalMemory && typeof profile.regionalMemory.notes === "string"
    ? profile.regionalMemory.notes
    : "";
  const approvalPolicy = profile.approvalPolicy && typeof profile.approvalPolicy.notes === "string"
    ? profile.approvalPolicy.notes
    : "";
  return {
    realtorLegalName: profile.realtorLegalName ?? "",
    licenseName: profile.licenseName ?? "",
    brokerageName: profile.brokerageName ?? "",
    teamName: profile.teamName ?? "",
    province: profile.province ?? "",
    market: profile.market ?? "",
    boardMemberships: (profile.boardMemberships ?? []).join(", "),
    managingBrokerEmail: profile.managingBrokerEmail ?? "",
    approvalChannel: profile.approvalChannel ?? "",
    emailProvider: profile.emailProvider ?? "",
    calendarProvider: profile.calendarProvider ?? "",
    driveProvider: profile.driveProvider ?? "",
    crmProvider: profile.crmProvider ?? "",
    mlsProvider: profile.mlsProvider ?? "",
    formsProvider: profile.formsProvider ?? "",
    signingProvider: profile.signingProvider ?? "",
    complianceProvider: profile.complianceProvider ?? "",
    showingProvider: profile.showingProvider ?? "",
    photoProcessingProvider: setupString(photoValue.provider),
    mlsLoginUrl: setupString(mlsPlaybook.loginUrl),
    mlsLoginEmail: setupString(mlsPlaybook.loginEmail),
    mlsLoginPassword: setupString(mlsPlaybook.loginPassword),
    complianceLoginUrl: setupString(compliancePlaybook.loginUrl),
    complianceLoginEmail: setupString(compliancePlaybook.loginEmail),
    complianceLoginPassword: setupString(compliancePlaybook.loginPassword),
    showingLoginUrl: setupString(showingPlaybook.loginUrl),
    showingLoginEmail: setupString(showingPlaybook.loginEmail),
    showingLoginPassword: setupString(showingPlaybook.loginPassword),
    browserWorkflowNotes: setupString(browserValue.notes),
    fintracProvider: profile.fintracProvider ?? "",
    defaultFolderPattern: profile.defaultFolderPattern ?? "Address - Client - Deal Type",
    commissionNotes: profile.commissionNotes ?? "",
    servicesSchedule: profile.servicesSchedule ?? "",
    regionalMemory,
    approvalPolicy,
  };
}

export function splitAdminSetupList(value: string): string[] {
  return value
    .split(/[,\n]/)
    .map((item) => item.trim())
    .filter(Boolean);
}

export function adminSetupPayloadFromDraft(draft: AdminSetupDraft) {
  const browserPlaybooks = {
    mls: {
      provider: draft.mlsProvider.trim(),
      loginUrl: draft.mlsLoginUrl.trim(),
      loginEmail: draft.mlsLoginEmail.trim(),
      loginPassword: draft.mlsLoginPassword,
      notes: draft.browserWorkflowNotes.trim(),
    },
    compliance: {
      provider: draft.complianceProvider.trim(),
      loginUrl: draft.complianceLoginUrl.trim(),
      loginEmail: draft.complianceLoginEmail.trim(),
      loginPassword: draft.complianceLoginPassword,
      notes: draft.browserWorkflowNotes.trim(),
    },
    showing: {
      provider: draft.showingProvider.trim(),
      loginUrl: draft.showingLoginUrl.trim(),
      loginEmail: draft.showingLoginEmail.trim(),
      loginPassword: draft.showingLoginPassword,
      notes: draft.browserWorkflowNotes.trim(),
    },
  };
  const browserWorkflowReady = Object.values(browserPlaybooks).every(
    (playbook) => playbook.provider && (playbook.loginUrl || playbook.loginEmail || playbook.loginPassword || playbook.notes),
  );
  const items = [
    {
      key: "identity_profile",
      status: draft.realtorLegalName.trim() && draft.brokerageName.trim() ? "configured" : "missing",
      provider: draft.brokerageName.trim() || null,
      value: {
        realtorLegalName: draft.realtorLegalName.trim(),
        licenseName: draft.licenseName.trim(),
        brokerageName: draft.brokerageName.trim(),
        teamName: draft.teamName.trim(),
        managingBrokerEmail: draft.managingBrokerEmail.trim(),
      },
    },
    {
      key: "jurisdiction",
      status: draft.province.trim() ? "configured" : "missing",
      provider: draft.province.trim().toUpperCase() || null,
      value: {
        country: "CA",
        province: draft.province.trim().toUpperCase(),
        market: draft.market.trim(),
        boards: splitAdminSetupList(draft.boardMemberships),
      },
    },
    {
      key: "regional_memory",
      status: draft.regionalMemory.trim() ? "configured" : "missing",
      provider: draft.province.trim().toUpperCase() || null,
      value: {
        notes: draft.regionalMemory.trim(),
        market: draft.market.trim(),
        boards: splitAdminSetupList(draft.boardMemberships),
      },
    },
    {
      key: "browser_workflows",
      status: browserWorkflowReady ? "configured" : "missing",
      provider: "browser-use",
      value: {
        mode: "browser-use",
        notes: draft.browserWorkflowNotes.trim(),
        playbooks: browserPlaybooks,
      },
    },
    ...ADMIN_SETUP_PROVIDER_ITEMS.map((item) => {
      const value = String(draft[item.field] ?? "").trim();
      return {
        key: item.key,
        status: value ? item.status : "missing",
        provider: value || null,
        value: value ? { provider: value } : null,
      };
    }),
  ] satisfies Array<{
    key: string;
    status: AdminSetupItemStatus;
    provider?: string | null;
    value?: unknown;
  }>;
  return {
    profile: {
      realtorLegalName: draft.realtorLegalName,
      licenseName: draft.licenseName,
      brokerageName: draft.brokerageName,
      teamName: draft.teamName,
      country: "CA",
      province: draft.province,
      market: draft.market,
      boardMemberships: splitAdminSetupList(draft.boardMemberships),
      managingBrokerEmail: draft.managingBrokerEmail,
      approvalChannel: draft.approvalChannel,
      emailProvider: draft.emailProvider,
      calendarProvider: draft.calendarProvider,
      driveProvider: draft.driveProvider,
      crmProvider: draft.crmProvider,
      mlsProvider: draft.mlsProvider,
      formsProvider: draft.formsProvider,
      signingProvider: draft.signingProvider,
      complianceProvider: draft.complianceProvider,
      showingProvider: draft.showingProvider,
      fintracProvider: draft.fintracProvider,
      defaultFolderPattern: draft.defaultFolderPattern,
      commissionNotes: draft.commissionNotes,
      servicesSchedule: draft.servicesSchedule,
      regionalMemory: { notes: draft.regionalMemory },
      approvalPolicy: { notes: draft.approvalPolicy },
    },
    items,
  };
}
