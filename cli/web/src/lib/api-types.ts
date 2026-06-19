import type { DashboardTheme } from "@/themes/types";

export interface LicenseStatusResponse {
  authenticated: boolean;
  email: string | null;
  tier: string | null;
  license_id: string | null;
  entitlements: string[];
  expires_at: number | null;
  expired: boolean;
  status_text: string;
  packs: AccessStatusResponse["packs"];
}

export interface LicenseActivateResponse {
  authenticated: boolean;
  email: string;
  tier: string;
  license_id: string;
  entitlements: string[];
  expires_at: number;
  packs: AccessStatusResponse["packs"];
  skill_count: number;
  skill_names: string[];
  skill_error: string | null;
}

export interface LicenseSyncSkillsResponse {
  skill_count: number;
  skill_names: string[];
  path: string | null;
  removed: string[];
  errors: string[];
  packs: AccessStatusResponse["packs"];
}

export interface LicenseLogoutResponse {
  authenticated: false;
  cleared: boolean;
  packs: AccessStatusResponse["packs"];
}

export interface AccessEntitlementState {
  status: string;
  active: boolean;
  ownedSnapshot: boolean;
  description: string;
  requiresActiveAffiliation: boolean;
  manualLock: boolean;
}

export interface AccessStatusResponse {
  profile: string;
  devOverride?: boolean;
  mode?: "development" | "entitlement" | string;
  entitlements: Record<string, AccessEntitlementState>;
  packs: {
    realEstateSales: boolean;
    realEstateMarketing: boolean;
    realEstateAdmin: boolean;
    realEstateCma: boolean;
    realEstateAny: boolean;
  };
}

export type SourceConnectorState =
  | "not_configured"
  | "connected"
  | "import_only"
  | "needs_operator"
  | "blocked"
  | "error";

export interface SourceConnectionBlueprint {
  id: string;
  source: string;
  category: "messages" | "leads" | "operations" | "admin" | "forms" | string;
  informationNeeded: string;
  connectionLayer: string;
  uiDestination: string;
  successSignal: string;
  prompt: string;
}

export interface SourceCategoryMeta {
  id: string;
  label: string;
  description: string;
}

export interface SourceConnectorStatus {
  id: string;
  label: string;
  category: string;
  description: string;
  wired: boolean;
  state: SourceConnectorState;
  sourceExists: boolean;
  sourceDir: string;
  sourcePath: string;
  statusPath: string;
  artifactsDir: string;
  connectionType: string | null;
  syncMode: string | null;
  authStatus: string | null;
  initializeBehavior: "local_messages_import" | "composio_social_setup" | "agent_setup_task" | string;
  runMode: "server_inline" | "agent_session" | "agent_setup_task" | string;
  ownerAgent: string;
  enabledUiSurfaces: string[];
  connected: boolean;
  importOnly: boolean;
  blocked: boolean;
  lastError: string | null;
  nextOperatorStep: string | null;
  recoveryKind?: "ready" | "missing_config" | "operator_blocked" | "upstream_error" | "needs_operator" | string;
  recoverySeverity?: "none" | "info" | "warning" | string;
  recoveryOwner?: string;
  recoveryAction?: string;
  recoveryError?: string;
  lastCheckedAt: string | null;
  recordCounts: Record<string, number>;
  prompt: string;
}

export interface SourceConnectorsResponse {
  toolsRoot: string;
  toolsRootSource: string;
  toolsRootIo: "local" | string;
  sourceRoot: string;
  blueprints: SourceConnectionBlueprint[];
  promptCategories: Array<{ id: string; label: string }>;
  categories: SourceCategoryMeta[];
  connectors: SourceConnectorStatus[];
}

export interface SourceRecord {
  source_id?: string;
  source_record_id?: string;
  source_url?: string | null;
  display_name?: string;
  channel?: string;
  direction?: "inbound" | "outbound" | string;
  timestamp?: string;
  day?: string;
  text?: string;
  summary?: string;
  title?: string;
  status?: string;
  confidence?: number;
  tags?: string[];
  target_ui_surfaces?: string[];
  conversation_id?: string;
  contact_id?: string | null;
  message_count?: number;
  inbound_count?: number;
  outbound_count?: number;
  total_messages?: number;
  last_text?: string;
  last_message_at?: string;
  last_seen_at?: string;
  [key: string]: unknown;
}

export interface SourceRecordsResponse {
  toolsRoot: string;
  toolsRootSource: string;
  toolsRootIo: "local" | string;
  sourceRoot: string;
  sourceId: string;
  source: SourceConnectorStatus;
  limit: number;
  records: {
    contacts: SourceRecord[];
    conversations: SourceRecord[];
    messages: SourceRecord[];
    messageDays: SourceRecord[];
    leadEvents: SourceRecord[];
    tasks: SourceRecord[];
  };
}

export interface SourceInboxThread {
  id: string;
  sourceId: string;
  sourceLabel: string;
  sourceState: SourceConnectorState | string | null;
  threadId: string;
  conversationId: string | null;
  contactId: string | null;
  personName: string;
  channel: string;
  latestText: string;
  latestAt: string;
  direction: "inbound" | "outbound" | string | null;
  messageCount: number;
  inboundCount: number;
  outboundCount: number;
  heatScore: number;
  heatLabel: "hot" | "warm" | "watch" | "normal" | string;
  status: "open" | "done" | "archived" | string;
  leadSectionIds?: string[];
  record: SourceRecord;
}

export interface SourceInboxProfileVerifier {
  kind: "phone" | "email" | string;
  value: string;
  key: string;
}

export type SourceInboxProfileStatus =
  | "new_lead"
  | "follow_up"
  | "ghosting"
  | "dead"
  | "closed_seller"
  | "closed_buyer";

export interface SourceInboxProfile {
  id: string;
  displayName: string;
  sources: string[];
  sourceIds: string[];
  channels: string[];
  contactIds: string[];
  conversationIds: string[];
  verifiers: SourceInboxProfileVerifier[];
  phones: string[];
  emails: string[];
  threadIds: string[];
  threadCount: number;
  latestText: string;
  latestAt: string;
  heatScore: number;
  heatLabel: "hot" | "warm" | "watch" | "normal" | string;
  hasCrm: boolean;
  hasConversation: boolean;
  isPotentialLead: boolean;
  crmStage: string | null;
  leadSource: string | null;
  tags: string[];
  status: SourceInboxProfileStatus | null;
  statusUpdatedAt: string | null;
  favorite?: boolean;
  favoritedAt?: string | null;
  favoritedBy?: string | null;
  leadSectionIds?: string[];
}

export interface SourceInboxDraft {
  id: string;
  sourceId: string;
  sourceLabel: string;
  taskId: string;
  threadId: string;
  contactId: string | null;
  conversationId: string | null;
  personName: string;
  channel: string;
  title: string;
  draftText: string;
  context: string;
  latestAt: string;
  status: "pending" | "approved" | "skipped" | string;
  approvalRequired: boolean;
  generated: boolean;
  fallback?: boolean;
  templateId?: string | null;
  templateName?: string | null;
  outreachLane?: OutreachLane | string | null;
  record: SourceRecord;
  skippedAt?: string | null;
  score?: number | null;
  leadLabel?: string | null;
  scoreReason?: string | null;
  leadSectionIds?: string[];
}

export type OutreachLane = "new-outreach" | "hot-leads-watcher" | "follow-ups";

export type OutreachTemplateStatus = "active" | "pending_approval" | "archived";

export interface OutreachTemplate {
  id: string;
  lane: OutreachLane;
  name: string;
  body: string;
  channel: string;
  active: boolean;
  status: OutreachTemplateStatus;
  rationale?: string | null;
  uses: number;
  replies: number;
  wins: number;
  replyRate: number;
  winRate: number;
  createdAt: string;
  updatedAt: string;
}

export interface OutreachLaneOverview {
  lane: OutreachLane;
  totalTemplates: number;
  activeTemplates: number;
  pendingTemplates: number;
  totalAttempts: number;
  totalReplies: number;
  laneReplyRate: number;
  best: OutreachTemplate | null;
  worst: OutreachTemplate | null;
  drift: {
    template: OutreachTemplate;
    recent: { uses: number; replies: number; wins: number; replyRate: number; winRate: number };
    deltaPct: number;
  }[];
  pending: OutreachTemplate[];
}

export interface OutreachOverview {
  lanes: OutreachLaneOverview[];
  pendingTotal: number;
  thresholds: { minUsesForRanking: number; driftDropPct: number; recentWindowDays: number };
}

export type AdminDealSide = "listing" | "buyer";

export type AdminDealToggleValue = string | boolean | null;

export interface AdminDealCreateRequest {
  title: string;
  side: AdminDealSide;
  // Province chooses the backend flow package. Board/market are optional deal metadata.
  province?: string;
  board?: string | null;
  market?: string | null;
  currentStage?: number;
  primaryContactId?: string | null;
  loftyContactId?: string | null;
  listingAddress?: string | null;
  fields?: Record<string, unknown>;
}

export interface AdminProfilePromotionRequest {
  profileId: string;
  side: AdminDealSide;
  displayName?: string | null;
  primaryContactId?: string | null;
  listingAddress?: string | null;
  workflow?: string | null;
  province?: string | null;
  board?: string | null;
  market?: string | null;
  currentStage?: number;
  profileContext?: Record<string, unknown>;
  verifiers?: SourceInboxProfileVerifier[];
  fields?: Record<string, unknown>;
  dispatchInitialStage?: boolean;
}

export interface AdminProfilePromotionResponse {
  action: "created" | "updated" | string;
  matchReason: string | null;
  deal: AdminDeal;
}

export interface AdminDealScorecard {
  progress: string | null;
  completedChecklist: number;
  totalChecklist: number;
  canAdvance: boolean;
  blocked: boolean;
  missingCount: number;
  stageName?: string | null;
  nextStageName?: string | null;
  activeRunCount?: number;
  runningRunCount?: number;
  waitingHumanCount?: number;
  activeRunLabel?: string | null;
  activeRunStatus?: string | null;
}

export interface AdminDeal {
  id: string;
  title: string;
  side: AdminDealSide;
  currentStage: number;
  status: "active" | "closed" | "archived" | string;
  province: string | null;
  board?: string | null;
  market?: string | null;
  sourceKey?: string | null;
  sourceRowId?: string | null;
  sourceLabel?: string | null;
  sourceSyncedAt?: string | null;
  primaryContactId: string | null;
  loftyContactId: string | null;
  listingAddress: string | null;
  extraToggles: Record<string, unknown>;
  createdAt: string;
  updatedAt: string;
  stageEnteredAt: string;
  closedAt: string | null;
  signingAuthority: string | null;
  fintracFormType: string | null;
  listingTrack: string | null;
  propertySubtype: string | null;
  estateStatus: string | null;
  transactionType: string | null;
  listingType: string | null;
  pep: boolean | null;
  tenanted: boolean | null;
  poaSigning: boolean | null;
  corporate: boolean | null;
  hasSuite: boolean | null;
  multipleOffers: boolean | null;
  familyMember: boolean | null;
  dualRep: boolean | null;
  unrepresentedOtherSide: boolean | null;
  lockbox: boolean | null;
  delayedOffer: boolean | null;
  saleOfBuyersProperty: boolean | null;
  listingDate?: string | null;
  offerDate?: string | null;
  subjectRemovalDate?: string | null;
  depositDueDate?: string | null;
  completionDate?: string | null;
  possessionDate?: string | null;
  anniversaryDate?: string | null;
  listPrice?: number | null;
  offerPrice?: number | null;
  depositAmount?: number | null;
  commissionPct?: number | null;
  homePrice?: number | null;
  gci?: number | null;
  teamRevenue?: number | null;
  agentRevenue?: number | null;
  expectedCloseDate?: string | null;
  crmTransactionStatus?: string | null;
  crmTransactionType?: string | null;
  mlsNumber?: string | null;
  legalDescription?: string | null;
  lotSizeSqft?: number | null;
  yearBuilt?: number | null;
  depositInTrustAt?: string | null;
  listingPublishedAt?: string | null;
  offerAcceptedAt?: string | null;
  subjectsRemovedAt?: string | null;
  completedAt?: string | null;
  // Server-computed card scorecard (checklist progress + gate state). Added by
  // GET /api/admin/deals so the board shows progress without opening the modal.
  progress?: string | null;
  scorecard?: AdminDealScorecard | null;
}

export interface DealContactCreateRequest {
  role: string;
  contactId: string;
  notes?: string | null;
}

export interface DealContact {
  id: string;
  dealId: string;
  role: string;
  contactId: string;
  notes: string | null;
  createdAt: string;
  updatedAt: string;
  contact?: AdminContact | null;
}

export interface DealAttachmentCreateRequest {
  kind: string;
  filePath: string;
  summary?: string | null;
  sourceRunId?: string | null;
  sourceSnapshotId?: string | null;
}

export interface DealAttachment {
  id: string;
  dealId: string;
  kind: string;
  filePath: string;
  summary: string | null;
  sourceRunId: string | null;
  sourceSnapshotId: string | null;
  createdAt: string;
}

export interface AdminAction {
  id: string;
  name: string;
  side: AdminDealSide | null;
  fromStage: number | null;
  toStage: number | null;
  trigger: string;
  fieldKey: string | null;
  condition: Record<string, unknown> | null;
  skill: string;
  skillArgs: Record<string, unknown>;
  provinceFilter: string[] | null;
  enabled: boolean;
  priority: number;
  approvalRequired: boolean;
  version: number;
  createdAt: string;
  updatedAt: string;
}

export interface AdminActionRun {
  id: string;
  registryId: string;
  dealId: string;
  dealEventId: string | null;
  cronJobId: string | null;
  harnessRunId?: string | null;
  status: string;
  outputPath: string | null;
  errorMessage: string | null;
  payload: Record<string, unknown> | null;
  humanPrompt?: Record<string, unknown> | null;
  result?: Record<string, unknown> | null;
  resultIdempotencyKey?: string | null;
  createdAt: string;
  startedAt?: string | null;
  updatedAt: string;
  completedAt: string | null;
  skill?: string | null;
  registryName?: string | null;
}

export interface AdminDealTask {
  id: string;
  type: "action_run" | "ai_action" | "checklist" | "field" | "document" | string;
  source: string;
  title: string;
  description: string | null;
  status: string;
  dealId: string;
  dealTitle: string;
  side: AdminDealSide;
  currentStage: number;
  stageName: string;
  packageKey: string;
  skill: string | null;
  canRunWithAi: boolean;
  runId: string | null;
  handoffId?: string | null;
  field: string | null;
  kind: string | null;
  createdAt: string | null;
  updatedAt: string | null;
}

export interface AdminDealTasksResponse {
  items: AdminDealTask[];
  count: number;
}

export interface AdminDealTaskRunRequest {
  dealId: string;
  skill: string;
  title?: string | null;
  sourceTaskId?: string | null;
  runNow?: boolean;
}

export interface DealRunResultArtifact {
  kind: string;
  filePath?: string | null;
  file_path?: string | null;
  summary?: string | null;
  sourceSnapshotId?: string | null;
  source_snapshot_id?: string | null;
}

export interface DealRunResultRequest {
  status: string;
  idempotency_key?: string | null;
  idempotencyKey?: string | null;
  artifacts?: DealRunResultArtifact[];
  next_tasks?: Array<Record<string, unknown>>;
  nextTasks?: Array<Record<string, unknown>>;
  checklist_updates?: Array<Record<string, unknown>>;
  checklistUpdates?: Array<Record<string, unknown>>;
  human_prompt?: Record<string, unknown> | null;
  humanPrompt?: Record<string, unknown> | null;
  error?: string | null;
}

export interface DealFlowChecklistItem {
  id: string;
  label: string;
  required?: boolean;
}

export interface DealFlowFieldRequirement {
  field: string;
  label: string;
}

export interface DealFlowDocRequirement {
  kind: string;
  label: string;
}

export interface DealFlowRunBlocker {
  id: string;
  label: string;
  status: string;
  updatedAt?: string | null;
}

export interface DealPhaseGate {
  stage: number;
  stageName: string;
  nextStage: number | null;
  nextStageName: string | null;
  canAdvance: boolean;
  completedChecklist: number;
  totalChecklist: number;
  missingChecklist: DealFlowChecklistItem[];
  missingFields: DealFlowFieldRequirement[];
  missingDocs: DealFlowDocRequirement[];
  blockingRuns: DealFlowRunBlocker[];
}

export interface DealFlowResolution {
  packageKey: string;
  side: AdminDealSide;
  stage: number;
  stageName: string;
  stageSubtitle: string;
  nextStage: number | null;
  nextStageName: string | null;
  checklistItems: DealFlowChecklistItem[];
  requiredFields: DealFlowFieldRequirement[];
  requiredDocs: DealFlowDocRequirement[];
  requiredForms: Array<{ code: string; name: string }>;
  automationTriggers: Array<{ id: string; label: string; skill: string }>;
  backgroundAutomations: Array<{
    id: string;
    name: string;
    skill: string;
    kind: string;
    affectsStages?: number[];
    description?: string;
  }>;
  localOverrides: Record<string, unknown>;
  gate: DealPhaseGate;
}

export interface DealContext {
  deal: AdminDeal;
  primaryContact: AdminContact | null;
  coContacts: DealContact[];
  conditions: Record<string, AdminDealToggleValue>;
  conditionalDocs?: ProvinceConditionalDoc[];
  checklist: Record<string, unknown>;
  attachments: DealAttachment[];
  priorRuns: AdminActionRun[];
  dealFlow?: DealFlowResolution;
  provinceGuide?: AdminProvinceGuide;
  agentGuideMemory?: Record<string, unknown>;
  stageDocuments?: ProvinceStageDocuments;
  events: Array<Record<string, unknown>>;
}

export interface ProvinceStageDocumentItem {
  code: string;
  name: string;
  source: "form" | "conditional";
  side?: string | null;
  category?: string | null;
  sourcePath?: string | null;
  condition?: { field: string; value: string } | null;
}

export interface ProvinceStageDocuments {
  province: string;
  side: string;
  stages: Record<string, ProvinceStageDocumentItem[]>;
  unmapped: Array<{ code: string; name: string; category?: string | null }>;
  otherSide: Array<{ code: string; name: string; category?: string | null; side?: string | null }>;
  coverage: {
    forms: number;
    mapped: number;
    conditional: number;
    otherSide: number;
    unmapped: number;
  };
}

export interface ProvinceConditionalDoc {
  id: string;
  province: string;
  side?: string | null;
  stage?: number | null;
  fieldKey: string;
  fieldValue: string;
  docCode: string;
  docName: string;
  notes?: string | null;
}

export interface AdminProvinceGuidePage {
  province: string;
  slug: string;
  pageType?: string;
  title: string;
  sourceUrl?: string | null;
  sourcePath?: string | null;
}

export interface AdminProvinceGuideForm {
  province: string;
  code: string;
  name: string;
  category?: string | null;
  pageCount?: number | null;
  annotationCount?: number | null;
  localImagePaths?: string[];
}

export interface AdminProvinceGuide {
  province: string;
  provinceLabel: string;
  coverage: {
    referencePages: number;
    checklists: number;
    forms: number;
    pageTypes?: Record<string, number>;
    hasTransactionGuide: boolean;
  };
  pages: AdminProvinceGuidePage[];
  checklists: AdminProvinceGuidePage[];
  forms: AdminProvinceGuideForm[];
}

export interface AdminProvinceGuideCoverage {
  province: string;
  provinceLabel: string;
  referencePages: number;
  listingsSalesPages: number;
  checklists: number;
  forms: number;
  hasTransactionGuide: boolean;
}

export interface AdminProvinceGuidesResponse {
  items: AdminProvinceGuideCoverage[];
}

export interface AdminProvinceGuideImportResult {
  ok: boolean;
  root: string;
  error?: string;
  pages: number;
  checklists: number;
  forms: number;
  conditionalDocs: number;
  provinces: string[];
}

export interface AdminJurisdiction {
  country: string;
  province: string;
  market: string;
  packageKey: string;
}

export interface AdminJurisdictionUpdateRequest {
  country?: string;
  province?: string;
  market?: string;
  packageKey?: string;
}

export type AdminSetupItemStatus = "missing" | "configured" | "connected" | "manual" | "skipped";

export interface AdminSetupProfile {
  id: string;
  realtorLegalName?: string | null;
  licenseName?: string | null;
  brokerageName?: string | null;
  teamName?: string | null;
  country: string;
  province: string;
  market?: string | null;
  boardMemberships: string[];
  emailProvider?: string | null;
  calendarProvider?: string | null;
  driveProvider?: string | null;
  crmProvider?: string | null;
  mlsProvider?: string | null;
  formsProvider?: string | null;
  signingProvider?: string | null;
  complianceProvider?: string | null;
  showingProvider?: string | null;
  fintracProvider?: string | null;
  approvalChannel?: string | null;
  managingBrokerEmail?: string | null;
  defaultFolderPattern?: string | null;
  commissionNotes?: string | null;
  servicesSchedule?: string | null;
  regionalMemory: Record<string, unknown>;
  approvalPolicy: Record<string, unknown>;
  completedAt?: string | null;
  createdAt: string;
  updatedAt: string;
}

export interface AdminSetupItem {
  key: string;
  category: string;
  label: string;
  description?: string | null;
  required: boolean;
  status: AdminSetupItemStatus;
  provider?: string | null;
  value?: unknown;
  notes?: string | null;
  sortOrder: number;
  updatedAt: string;
}

export interface AdminSetupReadinessItem {
  key: string;
  label: string;
  category?: string | null;
  status: AdminSetupItemStatus;
  provider?: string | null;
  ready: boolean;
  state: string;
  detail: string;
  action: string;
  hasValue: boolean;
  updatedAt?: string | null;
}

export interface AdminSetupSnapshot {
  profile: AdminSetupProfile;
  items: AdminSetupItem[];
  readiness?: AdminSetupReadinessItem[];
  complete: boolean;
  launchRequired: boolean;
  canStartAdmin: boolean;
  requiredCount: number;
  completedRequiredCount: number;
  missingRequiredKeys: string[];
  completionPct: number;
  memory?: {
    path?: string;
    synced?: boolean;
    bytes?: number;
  };
  playbook?: {
    path?: string;
    bytes?: number;
    province?: string | null;
    hasProvinceGuide?: boolean;
  };
  verificationWarnings?: string[];
}

export interface AdminSetupUpdateRequest {
  profile?: Partial<AdminSetupProfile>;
  items?: Array<{
    key: string;
    status: AdminSetupItemStatus;
    provider?: string | null;
    value?: unknown;
    notes?: string | null;
  }>;
}

export interface PackOnboardingItem {
  packId: string;
  key: string;
  category: string;
  label: string;
  description?: string | null;
  required: boolean;
  status: AdminSetupItemStatus;
  provider?: string | null;
  envKeys: string[];
  value?: unknown;
  notes?: string | null;
  sortOrder: number;
  updatedAt?: string | null;
  source?: string;
}

export interface PackOnboardingPack {
  packId: string;
  label: string;
  entitlement: string;
  description: string;
  unlocked: boolean;
  status: AdminSetupItemStatus;
  complete: boolean;
  launchRequired: boolean;
  requiredCount: number;
  completedRequiredCount: number;
  missingRequiredKeys: string[];
  completionPct: number;
  completedAt?: string | null;
  updatedAt?: string | null;
  items: PackOnboardingItem[];
}

export interface PackOnboardingSnapshot {
  packs: PackOnboardingPack[];
  activeCount: number;
  completedActiveCount: number;
  launchRequiredPacks: string[];
  complete: boolean;
  memory?: {
    path?: string;
    synced?: boolean;
    bytes?: number;
  };
}

export interface PackOnboardingUpdateRequest {
  items?: Array<{
    key: string;
    status: AdminSetupItemStatus;
    provider?: string | null;
    value?: unknown;
    notes?: string | null;
  }>;
}

export interface LeadsSetupItem {
  key: string;
  category: string;
  label: string;
  description: string | null;
  required: boolean;
  status: AdminSetupItemStatus;
  provider: string | null;
  value: unknown;
  notes: string | null;
  sortOrder: number;
  updatedAt: string | null;
}

export interface OutreachConnectorRef {
  id: "apple-messages" | "sms-provider" | "android-device" | "rcs";
  label: string;
  state: "connected" | "import_only" | "blocked" | "needs_operator" | "not_configured";
  connected: boolean;
  importOnly: boolean;
  blocked: boolean;
  nextOperatorStep: string | null;
  lastError: string | null;
  ownerAgent: string;
  totalRecords: number;
}

export interface LeadsSetupSnapshot {
  items: LeadsSetupItem[];
  requiredCount: number;
  completedRequiredCount: number;
  missingRequiredKeys: string[];
  completionPct: number;
  complete: boolean;
  completedAt: string | null;
  launchRequired: boolean;
  leadSourcesReady: boolean;
  outreachReady: boolean;
  outreachConnectors: OutreachConnectorRef[];
}

export interface LeadsSetupItemUpdate {
  key: string;
  status: AdminSetupItemStatus;
  provider?: string | null;
  value?: unknown;
  notes?: string | null;
}

export interface AgentSetupItem {
  key: string;
  category: string;
  label: string;
  description: string | null;
  required: boolean;
  status: AdminSetupItemStatus;
  provider: string | null;
  value: unknown;
  notes: string | null;
  sortOrder: number;
  updatedAt: string | null;
}

export interface AgentSetupSnapshot {
  items: AgentSetupItem[];
  requiredCount: number;
  completedRequiredCount: number;
  missingRequiredKeys: string[];
  completionPct: number;
  complete: boolean;
  completedAt: string | null;
  launchRequired: boolean;
}

export interface AgentSetupItemUpdate {
  key: string;
  status: AdminSetupItemStatus;
  provider?: string | null;
  value?: unknown;
  notes?: string | null;
}

export interface AdminDealsResponse {
  items: AdminDeal[];
  count: number;
  jurisdiction?: AdminJurisdiction;
}

export interface AdminUpcomingEvent {
  id: string;
  source: "gcal" | "deal_date" | string;
  sourceEventId: string;
  dealId: string | null;
  title: string;
  location: string | null;
  address: string;
  startAt: string | null;
  endAt: string | null;
  kind: string;
  syncedAt: string | null;
}

export interface AdminUpcomingEventsResponse {
  items: AdminUpcomingEvent[];
  count: number;
  days: number;
  generatedAt: string;
}

export interface AdminContact {
  id: string;
  displayName: string | null;
  primaryEmail: string | null;
  primaryPhone: string | null;
  type: string | null;
  stage: string | null;
  lastActivityAt: string | null;
  ownerNotes?: string | null;
  parkedReason?: string | null;
  hasOpenConflict?: boolean;
  classifiedAt?: string | null;
  sourceKey?: string | null;
  ingestRunId?: string | null;
  createdAt?: string | null;
  updatedAt?: string | null;
}

export interface AdminContactsResponse {
  items: AdminContact[];
  count: number;
  tab: string | null;
  limit: number;
  offset: number;
}

export interface ComposioStatus {
  configured: boolean;
  hasKey: boolean;
  valid: boolean;
  baseUrl?: string;
  error?: string;
  status?: number;
}

export interface AyrshareStatus {
  configured: boolean;
  hasKey: boolean;
  valid: boolean;
  baseUrl?: string;
  error?: string;
  status?: number;
  active_social_accounts?: string[];
  display_names?: Array<{
    platform?: string;
    displayName?: string;
    userImage?: string;
    [key: string]: unknown;
  }>;
  monthly_post_count?: number;
  monthly_post_quota?: number;
}

export interface SocialDerived {
  reach?: number | null;
  impressions?: number | null;
  plays?: number | null;
  likes?: number | null;
  comments?: number | null;
  saves?: number | null;
  shares?: number | null;
  video_views?: number | null;
  engagement_total?: number | null;
  engagement_rate?: number | null;
  save_rate?: number | null;
  hook_rate?: number | null;
  hold_rate?: number | null;
  avg_watch_time_sec?: number | null;
  duration_sec?: number | null;
  [key: string]: unknown;
}

export interface SocialPostSummary {
  platform?: string;
  post_id: string;
  permalink?: string | null;
  caption?: string | null;
  media_type?: string;
  posted_at?: string | null;
  derived: SocialDerived;
}

export interface SocialPlatformBlock {
  post_count: number;
  totals: { reach: number; impressions: number; engagement_total: number };
  averages: {
    engagement_rate: number | null;
    hook_rate: number | null;
    hold_rate: number | null;
    save_rate: number | null;
  };
  top_posts: SocialPostSummary[];
  bottom_posts: SocialPostSummary[];
  account_metrics: Record<string, unknown>;
}

export interface SocialSnapshot {
  exists?: boolean;
  generated_at?: string;
  lookback_days?: number;
  window_start?: string;
  platforms?: Record<string, SocialPlatformBlock>;
  totals?: { post_count: number; reach: number; impressions: number; engagement_total: number };
  top_posts?: SocialPostSummary[];
  bottom_posts?: SocialPostSummary[];
  format_breakdown?: Record<string, Record<string, number>>;
  wow_delta?: {
    post_count_delta: number;
    engagement_rate_delta: number | null;
    hook_rate_delta: number | null;
    hold_rate_delta: number | null;
  };
  account_metrics?: Record<string, Record<string, unknown>>;
  message?: string;
  snapshot_path?: string;
}

export interface SocialIdea {
  source_record_id: string;
  source_id?: string;
  title?: string;
  status?: string;
  task_type?: string;
  approval_required?: boolean;
  timestamp?: string;
  platform: string;
  format: string;
  hook: string;
  concept: string;
  outline?: string[];
  best_post_time?: string | null;
  target_audience?: string | null;
  grounded_in?: { metric?: string; trend?: string; signal?: string };
  reasoning?: string | null;
  suggested_assets?: string[];
  draft_text?: string;
  notes?: Array<{ ts: string; text: string }>;
  last_action_at?: string;
}

export interface SocialMetricRow {
  platform: string;
  post_id: string;
  fetched_at: string;
  posted_at?: string | null;
  media_type?: string;
  permalink?: string | null;
  caption?: string | null;
  metrics: Record<string, unknown>;
  raw?: Record<string, unknown> | null;
}

export interface ComposioApiResult<T> {
  ok: boolean;
  data?: T;
  status?: number;
  error?: string;
  raw?: unknown;
}

export interface ComposioToolkitMeta {
  logo?: string;
  description?: string;
  app_url?: string;
  tools_count?: number;
  triggers_count?: number;
  categories?: { id?: string; name?: string }[];
  [key: string]: unknown;
}

export interface ComposioConnectedAccount {
  id?: string;
  status?: string;
  toolkit?: { slug?: string; name?: string; logo?: string; meta?: ComposioToolkitMeta };
  user_id?: string;
  created_at?: string;
  updated_at?: string;
  [key: string]: unknown;
}

export interface ComposioToolkit {
  slug?: string;
  name?: string;
  description?: string;
  logo?: string;
  meta?: ComposioToolkitMeta;
  categories?: { slug?: string; id?: string; name?: string }[];
  [key: string]: unknown;
}

export interface ComposioConnectInitResponse {
  redirect_url?: string;
  redirect_uri?: string;
  connected_account_id?: string;
  [key: string]: unknown;
}

export interface ComposioAuthField {
  name: string;
  displayName?: string;
  type?: string;
  description?: string;
  required?: boolean;
  default?: string;
}

export interface ComposioAuthScheme {
  name: string;
  mode: string;
  fields?: {
    auth_config_creation?: {
      required?: ComposioAuthField[];
      optional?: ComposioAuthField[];
    };
    connected_account_initiation?: {
      required?: ComposioAuthField[];
      optional?: ComposioAuthField[];
    };
  };
  auth_hint_url?: string | null;
}

export interface ComposioToolkitDetails {
  name?: string;
  slug?: string;
  composio_managed_auth_schemes?: string[];
  auth_config_details?: ComposioAuthScheme[];
  auth_guide_url?: string | null;
  meta?: ComposioToolkitMeta;
  [key: string]: unknown;
}

export interface ThreadContextMessage {
  id: string;
  direction: "inbound" | "outbound" | string;
  sender: string | null;
  text: string;
  timestamp: string | null;
}

export interface ThreadContextSend {
  id: string;
  channel: string | null;
  status: string | null;
  attempts: number;
  providerMessageId: string | null;
  payload: { text?: string; body?: string; [key: string]: unknown } | null;
  createdAt: string | null;
  updatedAt: string | null;
}

export interface ThreadContextMeta {
  score: number;
  label: string;
  reason: string | null;
  scoredBy: string | null;
  scoredAt: string | null;
  updatedAt: string | null;
}

export interface ThreadContextLead {
  leadId: string | null;
  displayName: string | null;
  stage: string | null;
  leadSource: string | null;
  assignedUser: string | null;
  score: number | null;
  tags: string[];
  summary: string | null;
  emails: string[];
  phones: string[];
  channel: string | null;
  timestamp: string | null;
  lastSeenAt: string | null;
}

export interface ThreadContextActivity {
  id: string;
  type: string;
  subtype?: string | null;
  title: string | null;
  summary: string | null;
  address?: string | null;
  timestamp: string | null;
}

export interface ThreadContextNote {
  id: string;
  title: string;
  summary: string;
  author?: string | null;
  timestamp: string | null;
}

export interface ThreadContextTask {
  id: string;
  title: string;
  summary: string;
  status: string;
  dueAt?: string | null;
  timestamp: string | null;
}

export interface ThreadContextResponse {
  sourceId: string;
  threadId: string;
  source: {
    id?: string;
    label?: string;
    category?: string;
    ownerAgent?: string;
    connected?: boolean;
  };
  personName: string;
  messageCount: number;
  messages: ThreadContextMessage[];
  lastInboundAt?: string | null;
  lastOutboundAt?: string | null;
  pendingDraft: SourceInboxDraft | null;
  sends: ThreadContextSend[];
  meta: ThreadContextMeta | null;
  lead: ThreadContextLead | null;
  notes: ThreadContextNote[];
  tasks: ThreadContextTask[];
  activity: ThreadContextActivity[];
}

export interface BuyerWatchlistEntry {
  id: string;
  contactId?: string | null;
  name: string;
  email?: string;
  phone?: string;
  score?: number | null;
  tier?: string | null;
  days?: number | null;
  lastActivity?: string | null;
  dateEntered?: string | null;
  searches?: string[];
  matchingListings?: string[];
  profileUrl?: string | null;
  source?: string;
  sourceLabel?: string;
  tags?: string[];
  scrapedAt?: string | null;
  leadSectionIds?: string[];
}

export interface LeadSectionSummary {
  id: string;
  label: string;
  source: string;
  count: number;
  contactIds: string[];
  threadIds: string[];
  profileIds: string[];
  draftIds: string[];
  buyerIds: string[];
}

export interface SourceInboxResponse {
  toolsRoot: string;
  toolsRootSource: string;
  toolsRootIo: "local" | string;
  sourceRoot: string;
  limit: number;
  recordCounts: Record<string, number>;
  hiddenCounts: Record<string, number>;
  sources: SourceConnectorStatus[];
  profiles: SourceInboxProfile[];
  threads: SourceInboxThread[];
  drafts: SourceInboxDraft[];
  skippedDrafts?: SourceInboxDraft[];
  privateSearchBuyers?: BuyerWatchlistEntry[];
  leadSections?: Record<string, LeadSectionSummary>;
  appleMessages?: AppleMessagesDirections;
  debug?: {
    readPath: "db" | "jsonl" | string;
    fallback: boolean;
    fallbackError?: string;
    fallbackErrorCode?: string;
    counts: {
      sources: number;
      profiles: number;
      threads: number;
      drafts: number;
      skippedDrafts: number;
      privateSearchBuyers: number;
      recordCounts: Record<string, number>;
      hiddenCounts: Record<string, number>;
    };
  };
}

export interface AppleMessagesDirections {
  // inbound = read chat.db as a lead source (needs Full Disk Access)
  inbound: boolean;
  // outbound = send approved texts through Messages (no FDA needed)
  outbound: boolean;
  // true only when inbound is enabled AND chat.db read is blocked
  blocked?: boolean;
  note?: string;
}

export interface TodayHourBucket {
  hour: number;
  label: string;
  leadsIn: number;
  repliesOut: number;
}

export interface TodayDayBucket {
  iso: string;
  label: string;
  leadsIn: number;
  repliesOut: number;
  dealsAdvanced: number;
}

export interface TodayPulseStat {
  label: string;
  value: string;
  rawValue: number;
  delta: number | null;
  deltaLabel: string | null;
  spark: number[];
  tone: "neutral" | "good" | "warn" | "danger";
}

export interface TodayUrgentItem {
  id: string;
  kind: "draft" | "hot-lead" | "deal-task" | "action-run";
  title: string;
  meta: string;
  waitedMinutes: number | null;
  tone: "neutral" | "warn" | "danger";
  to: string;
  sourceId?: string;
  threadId?: string;
  taskId?: string;
  runId?: string;
}

export interface TodayIntelligenceItem {
  id: string;
  kind: "approvals" | "pcs" | "admin" | "identity" | "memory" | "source" | string;
  title: string;
  value: number;
  meta: string;
  tone: "neutral" | "good" | "warn" | "danger";
  to: string;
  updatedAt: string | null;
}

export interface TodayDashboardResponse {
  generatedAt: string;
  activityUpdatedAt: string | null;
  todayWindow: {
    start: string;
    end: string;
    timezone: string | null;
  };
  pulse: TodayPulseStat[];
  hourBuckets: TodayHourBucket[];
  dayBuckets: TodayDayBucket[];
  priority: TodayUrgentItem[];
  scheduled: CronJob[];
  live: SessionInfo[];
  running: AdminActionRun[];
  intelligence: TodayIntelligenceItem[];
}

export interface SourceInboxSentItem {
  id: string;
  idempotencyKey: string;
  sourceId: string;
  threadId: string;
  taskId: string;
  channel: string;
  status: "queued" | "sending" | "sent" | "retrying" | "failed" | string;
  attempts: number;
  nextRetryAt?: string | null;
  lastError?: string | null;
  providerMessageId?: string | null;
  attemptId?: string | null;
  createdAt: string;
  updatedAt: string;
  payload: {
    draft_text?: string;
    recipient?: {
      person_name?: string | null;
      contact_id?: string | null;
      conversation_id?: string | null;
      phone?: string | null;
      email?: string | null;
      social_handle?: string | null;
    };
    channel_meta?: {
      toolkit?: string | null;
      account_id?: string | null;
      [k: string]: unknown;
    };
    source_id?: string;
    thread_id?: string;
    task_id?: string;
    [k: string]: unknown;
  };
}

export interface SourceInboxSentResponse {
  items: SourceInboxSentItem[];
  limit: number;
  includePending: boolean;
}

export interface CrmIntegrationForm {
  provider: string;
  label: string;
  apiKeyEnv: string;
  apiKey?: string;
  hasApiKey: boolean;
  apiKeyPreview: string | null;
  baseUrl: string;
  authType: "header" | "query" | string;
  authHeader: string;
  authPrefix: string;
  authQueryParam: string;
  dbColumns: {
    leadId: string;
    stage: string;
    tags: string;
  };
  endpoints: {
    leads: string;
    lead: string;
    notes: string;
  };
}

export interface IntegrationSettingsResponse {
  configPath: string;
  secretsPath: string;
  sourceRoot: string;
  crm: CrmIntegrationForm;
}

export interface IntegrationTestResponse {
  success: boolean;
  status?: number;
  message?: string;
  error?: string;
}

export interface ActionResponse {
  name: string;
  ok: boolean;
  pid: number;
}

export interface ActionStatusResponse {
  exit_code: number | null;
  lines: string[];
  name: string;
  pid: number | null;
  running: boolean;
}

export interface UpdateStatusResponse {
  ahead: number;
  available: boolean;
  behind: number | null;
  branch: string | null;
  checked_at: number;
  command: string;
  error: string | null;
  local: string | null;
  origin_url: string | null;
  repo_dir: string | null;
  upstream: string | null;
}

export interface WorkspaceGitStatus {
  ok: boolean;
  error: string | null;
  path: string | null;
  repo_path: string | null;
  working_directory: string | null;
  display_name: string | null;
  repo_name: string | null;
  branch: string | null;
  upstream: string | null;
  ahead: number;
  behind: number;
  changed_files: number;
  insertions: number;
  deletions: number;
  untracked: number;
  dirty: boolean;
  repo_changed_files: number;
  repo_insertions: number;
  repo_deletions: number;
  repo_untracked: number;
  repo_dirty: boolean;
  diff_scope: "repo" | "session";
  baseline_created: boolean;
  baseline_at: number | null;
  short_sha: string | null;
  origin_url: string | null;
  repo_url: string | null;
  pr_url: string | null;
  checked_at: number;
}

export interface WorkspaceOpenResponse {
  ok: boolean;
  path: string;
}

export interface PlatformStatus {
  error_code?: string;
  error_message?: string;
  state: string;
  updated_at: string;
}

export interface StatusResponse {
  active_sessions: number;
  config_path: string;
  config_version: number;
  env_path: string;
  gateway_exit_reason: string | null;
  gateway_health_url: string | null;
  gateway_pid: number | null;
  gateway_platforms: Record<string, PlatformStatus>;
  gateway_running: boolean;
  gateway_state: string | null;
  gateway_updated_at: string | null;
  project_root: string;
  elevate_home: string;
  latest_config_version: number;
  release_date: string;
  version: string;
}

export type AgentHandoffStatus =
  | "queued"
  | "running"
  | "waiting_human"
  | "completed"
  | "failed"
  | "cancelled";

export interface AgentHandoffMessage {
  id: string;
  handoffId: string;
  fromAgentId: string;
  toAgentId: string | null;
  kind: "request" | "note" | "status" | "result" | "human_prompt" | "error" | string;
  content: string;
  payload: Record<string, unknown> | null;
  createdAt: string;
}

export interface AgentHandoff {
  id: string;
  fromAgentId: string;
  toAgentId: string;
  title: string;
  task: string;
  status: AgentHandoffStatus | string;
  priority: "low" | "normal" | "high" | "urgent" | string;
  dealId: string | null;
  profileId: string | null;
  contactId: string | null;
  conversationId: string | null;
  sourceRunId: string | null;
  parentHandoffId: string | null;
  cronJobId: string | null;
  idempotencyKey: string | null;
  resultIdempotencyKey: string | null;
  payload: Record<string, unknown> | null;
  result: Record<string, unknown> | null;
  errorMessage: string | null;
  createdAt: string;
  claimedAt: string | null;
  updatedAt: string;
  completedAt: string | null;
  messages?: AgentHandoffMessage[] | null;
}

export interface AgentHandoffCreateRequest {
  fromAgentId: string;
  toAgentId: string;
  task: string;
  title?: string | null;
  priority?: "low" | "normal" | "high" | "urgent";
  dealId?: string | null;
  profileId?: string | null;
  contactId?: string | null;
  conversationId?: string | null;
  sourceRunId?: string | null;
  parentHandoffId?: string | null;
  payload?: Record<string, unknown> | null;
  idempotencyKey?: string | null;
  runNow?: boolean;
}

export interface AgentHandoffMessageCreateRequest {
  fromAgentId: string;
  toAgentId?: string | null;
  kind?: "request" | "note" | "status" | "result" | "human_prompt" | "error" | string;
  content: string;
  payload?: Record<string, unknown> | null;
}

export interface AgentHandoffResultRequest {
  status?: Exclude<AgentHandoffStatus, "queued">;
  result?: Record<string, unknown> | null;
  errorMessage?: string | null;
  humanPrompt?: Record<string, unknown> | null;
  idempotencyKey?: string | null;
  actor?: string;
}

export interface AgentHandoffApproveRequest {
  approved?: boolean;
  runNow?: boolean;
  actor?: string;
}

export interface AgentCommsMessage {
  id: string;
  source: "handoff" | "handoff_message" | string;
  handoffId: string;
  messageId?: string | null;
  pair: string;
  from: string;
  to: string;
  priority: "low" | "normal" | "high" | "urgent" | string;
  timestamp: string;
  createdAt?: string;
  text: string;
  replyTo?: string | null;
  reply_to?: string | null;
  kind: string;
  title?: string | null;
  handoffStatus?: string;
  archived?: boolean;
  payload?: Record<string, unknown> | null;
}

export interface AgentCommsChannel {
  pair: string;
  agents: [string, string] | string[];
  message_count: number;
  messageCount?: number;
  last_message: {
    id?: string;
    from: string;
    to?: string;
    text: string;
    timestamp: string;
    kind?: string;
    priority?: string;
  } | null;
  lastMessage?: AgentCommsChannel["last_message"];
  last_activity: string | null;
  lastActivity?: string | null;
  archived: boolean;
}

export interface AgentCommsChannelResponse {
  pair: string;
  agents: [string, string] | string[];
  messages: AgentCommsMessage[];
  count: number;
}

export interface AgentCommsMessageCreateRequest {
  fromAgentId?: string;
  toAgentId?: string;
  agent?: string;
  text: string;
  priority?: "low" | "normal" | "high" | "urgent";
  replyTo?: string | null;
  runNow?: boolean;
}

export interface AgentHandoffSummary {
  total: number;
  queued: number;
  running: number;
  waitingHuman: number;
  completed: number;
  failed: number;
  cancelled: number;
  open: number;
  byAgent: Array<{
    agentId: string;
    total: number;
    queued: number;
    running: number;
    waitingHuman: number;
    completed: number;
    failed: number;
  }>;
  recent: AgentHandoff[];
  error: string;
}

export interface AgentWorkerSnapshot {
  enabled: boolean;
  agentId?: string | null;
  mode?: string;
  state: "idle" | "ok" | "disabled" | "locked" | "error" | string;
  lastReason?: string;
  lastTickAt: string | null;
  lastSuccessAt: string | null;
  lastError: string;
  drained: {
    handoffs: number;
    adminRuns: number;
  };
  recovered?: {
    staleHandoffs: number;
    staleAdminRuns?: number;
  };
  limits: {
    handoffs: number;
    adminRuns: number;
    staleRunningMinutes?: number;
  };
  heartbeat?: {
    enabled: boolean;
    intervalSeconds: number;
    lastBeatAt: string | null;
    nextBeatAt: string | null;
  };
  wake?: {
    enabled: boolean;
    pending: boolean;
    lastWakeAt: string | null;
    lastReason: string;
    agentId?: string | null;
    count: number;
  };
  loop?: {
    running: boolean;
    startedAt: string | null;
  };
}

export interface AgentRuntimeConfig {
  model?: string;
  provider?: string;
  base_url?: string;
  workdir?: string;
  timezone?: string;
  context_warning_threshold?: number | null;
  context_handoff_threshold?: number | null;
  runtime_type?: string;
  codex_context_cap?: number | null;
}

export interface AgentRoutingConfig {
  owns: string[];
  handoff_targets: string[];
  escalation_target?: string;
  default_priority?: string;
}

export interface AgentSafetyConfig {
  approval_mode?: string;
  always_ask: string[];
  never_ask: string[];
  dangerously_skip_permissions?: boolean;
}

export interface AgentIdentityConfig {
  emoji?: string;
  vibe?: string;
  work_style?: string;
}

export interface AgentSoulConfig {
  autonomy_rules?: string;
  communication_style?: string;
  day_mode?: string;
  night_mode?: string;
  day_mode_start?: string;
  day_mode_end?: string;
  core_truths?: string;
}

export interface AgentLifecycleConfig {
  startup_delay?: number | null;
  max_session_seconds?: number | null;
  max_crashes_per_day?: number | null;
  crash_window_seconds?: number | null;
  crash_window_max?: number | null;
  telegram_polling?: boolean | null;
}

export interface AgentEcosystemConfig {
  local_version_control?: boolean;
  upstream_sync?: boolean;
  catalog_browse?: boolean;
  community_publish?: boolean;
}

export interface AgentMemoryConfig {
  mode?: string;
  scopes: string[];
  sources: string[];
  recall_policy?: string;
  write_policy?: string;
  handoff_policy?: string;
}

export interface AgentQueueSummary {
  total: number;
  queued: number;
  running: number;
  waitingHuman: number;
  completed: number;
  failed: number;
  staleRecovered: number;
  lastWorkerTickAt: string | null;
}

export interface AgentAutomationSummary {
  total: number;
  enabled: number;
  paused: number;
  failures: number;
  nextRunAt: string | null;
  lastRunAt: string | null;
}

export interface AgentContextPressureSummary {
  lastEventAt: string | null;
  kind: string;
  percent: number | null;
  tokens: number | null;
  contextLimit: number | null;
  status: string;
  detail: string;
  thresholds: Record<string, unknown>;
}

export interface AgentLifecycleSummary {
  agentId?: string;
  startupDelay?: number | null;
  maxSessionSeconds?: number | null;
  maxCrashesPerDay?: number | null;
  crashWindowSeconds?: number | null;
  crashWindowMax?: number | null;
  dailyFailures?: number;
  windowFailures?: number;
  suspended?: boolean;
  reason?: string;
}

export interface AgentMemorySummary {
  mode?: string;
  scopes: string[];
  sources: string[];
  recallPolicy?: string;
  writePolicy?: string;
  handoffPolicy?: string;
  nativeFacts?: number;
  nativeFactsCapped?: boolean;
  lastMemoryAt?: string | null;
  recentFacts?: Array<{
    id?: string;
    fact?: string;
    source?: string;
    ts?: string;
  }>;
  handoffResults?: number;
  handoffFailures?: number;
}

export interface AgentObservabilitySummary {
  lastWakeAt: string | null;
  lastScopedTickAt: string | null;
  lastCronResultAt: string | null;
  retryOrCrashCount: number;
  approvalBlockers: number;
  staleRecovered: number;
}

export interface AgentCompatConfig {
  cortext?: {
    runtime?: string;
    runtime_type?: string;
    model?: string;
    provider?: string;
    base_url?: string;
    working_directory?: string;
    timezone?: string;
    ctx_warning_threshold?: number | null;
    ctx_handoff_threshold?: number | null;
    codex_context_cap?: number | null;
    dangerously_skip_permissions?: boolean;
    approval_rules?: { always_ask?: string[]; never_ask?: string[] };
    communication_style?: string;
    day_mode_start?: string;
    day_mode_end?: string;
    startup_delay?: number | null;
    max_session_seconds?: number | null;
    max_crashes_per_day?: number | null;
    crash_window?: { seconds?: number | null; max_crashes?: number | null };
    telegram_polling?: boolean | null;
  };
  notes?: string[];
}

export interface AgentHubAgent {
  id: string;
  name: string;
  role: string;
  description: string;
  enabled: boolean;
  platforms: string[];
  session_sources: string[];
  skills: string[];
  sharedSkills?: string[];
  artifactSkills?: string[];
  toolsets: string[];
  runtime: AgentRuntimeConfig;
  routing: AgentRoutingConfig;
  safety: AgentSafetyConfig;
  identity: AgentIdentityConfig;
  soul: AgentSoulConfig;
  lifecycle: AgentLifecycleConfig;
  ecosystem: AgentEcosystemConfig;
  memory: AgentMemoryConfig;
  metadata?: Record<string, unknown>;
  compat?: AgentCompatConfig;
  canDelete: boolean;
  builtin?: boolean;
  queueSummary: AgentQueueSummary;
  automationSummary: AgentAutomationSummary;
  lifecycleSummary?: AgentLifecycleSummary;
  contextPressure?: AgentContextPressureSummary;
  memorySummary?: AgentMemorySummary;
  observability?: AgentObservabilitySummary;
  status: "online" | "ready" | "offline" | "disabled" | "needs_model" | "needs_telegram" | string;
  session_count: number;
  active_session_count: number;
  has_prompt: boolean;
  telegramLane?: {
    configured: boolean;
    tokenConfigured: boolean;
    targetConfigured: boolean;
    tokenEnv: string;
    targetEnv: string;
    chatConfigured: boolean;
    topicConfigured: boolean;
    usesSharedBot: boolean;
    duplicateSharedBot?: boolean;
    error?: string;
  } | null;
}

export interface AgentHubPlatform {
  name: string;
  enabled: boolean;
  configured: boolean;
  token_configured: boolean;
  api_key_configured: boolean;
  home_channel: { platform: string; chat_id: string; name: string } | null;
  reply_to_mode: string;
  runtime?: PlatformStatus;
  approved_users: number;
  pending_pairings: Array<{
    code: string;
    user_id: string;
    user_name: string;
    age_minutes: number;
  }>;
  error?: string;
}

export interface AgentHubMemoryNode {
  id: string;
  label: string;
  type: "entity" | "fact" | string;
  weight: number;
  category?: string;
}

export interface AgentHubMemoryEdge {
  source: string;
  target: string;
  type: string;
}

export interface AgentHubSessionSummary {
  total: number;
  active: number;
  recent: Array<{
    id: string;
    title: string;
    source: string;
    started_at: number;
    last_active: number;
    is_active: boolean;
    message_count: number;
    tool_call_count: number;
    model: string;
  }>;
  by_source: Record<string, number>;
  by_day: Record<string, number>;
  error: string;
}

export interface InstallableDefault {
  id: string;
  name: string;
  role: string;
  description: string;
  native: boolean;
}

export interface AgentHubSnapshot {
  generated_at: number;
  config_path: string;
  elevate_home: string;
  gateway: {
    running: boolean;
    pid: number | null;
    state: string | null;
    updated_at: string | null;
    active_agents: number;
    exit_reason: string | null;
  };
  model: {
    model: string;
    provider: string;
    base_url_configured: boolean;
    api_key_configured: boolean;
    configured: boolean;
  };
  access: {
    profile: string;
    label: string;
    affiliation: Record<string, unknown>;
    entitlements: Record<string, { status?: string; owned_snapshot?: boolean }>;
  };
  agents: AgentHubAgent[];
  installableDefaults?: InstallableDefault[];
  orchestration?: {
    agents: unknown[];
    runs: unknown[];
    active_runs: number;
    error?: string;
  };
  handoffs: AgentHandoffSummary;
  agentWorker: AgentWorkerSnapshot;
  platforms: AgentHubPlatform[];
  sessions: AgentHubSessionSummary;
  memory: {
    provider: string;
    db_path: string;
    db_exists: boolean;
    facts: number;
    entities: number;
    embeddings: number;
    indexed_facts: number;
    documents: number;
    chunks: number;
    indexed_chunks: number;
    community_reports: number;
    relations: number;
    modal_assets: number;
    journal: {
      total: number;
      pending: number;
      processed: number;
      failed: number;
      active_session_count: number;
      session_segment_count: number;
      sessions: Array<{
        session_id: string;
        session_day: string;
        total: number;
        pending: number;
        processed: number;
        failed: number;
        latest_created_at: string | null;
      }>;
    };
    embedding: {
      enabled: boolean;
      provider: string;
      model: string;
      api_key_env: string;
    };
    graph: { nodes: AgentHubMemoryNode[]; edges: AgentHubMemoryEdge[] };
    error: string;
  };
  cron: {
    total: number;
    enabled: number;
    paused: number;
    recent: Array<{
      id: string;
      name: string;
      schedule: unknown;
      enabled: boolean;
      deliver: string;
    }>;
    error: string;
  };
  skills: {
    total: number;
    enabled: number;
    disabled: number;
    categories: Record<string, number>;
    available?: Array<{ name: string; category: string; description: string }>;
    error: string;
  };
  toolsets: {
    total: number;
    enabled: string[];
    known: Array<{
      name: string;
      label: string;
      description: string;
      enabled: boolean;
    }>;
    error: string;
  };
  harness?: HarnessSnapshot | { error?: string; available?: boolean };
}

export interface HarnessProfile {
  name: string;
  toolsets: string[];
  loaded_tools: number;
  requested_tools: number;
  system_prompt_tokens: number;
  tool_schema_tokens: number;
  request_tokens: number;
  savings_pct: number | null;
  issues: number;
}

export interface HarnessSnapshot {
  generated_at: string;
  elevate_home: string;
  server: {
    pattern: string;
    gateway_running: boolean;
    gateway_pid: number | null;
    clients: Array<{ id: string; label: string; connected: boolean }>;
  };
  orchestration: {
    visible: boolean;
    coordinator: string;
    agent_states: string[];
    total_agents: number;
    active_runs: number;
    recent_runs: number;
    route_labeled_runs: number;
    recent_events: number;
    event_tail: Array<{
      run_id?: string | null;
      type?: string | null;
      message?: string | null;
      timestamp?: string | null;
    }>;
    plan_graph: {
      ready_runs: number;
      blocked_runs: number;
      active_runs: number;
      completed_runs: number;
      cycle_runs: number;
      unresolved_dependencies: number;
      next_ready_run_ids: string[];
    };
    lifecycle_states: string[];
  };
  skills: {
    mode: string;
    index_visible: boolean;
    enabled: number;
    total: number;
    details_loaded_on_demand: boolean;
    tool_index_visible: boolean;
    enabled_toolsets: string[];
  };
  memory: {
    mode: string;
    provider: string;
    embeddings_enabled: boolean;
    embedding_provider: string;
    embedding_model: string;
    pending_turns: number;
    processed_turns: number;
    session_segments: number;
    graph_nodes: number;
    graph_edges: number;
    pipeline: {
      derived_from_journal: boolean;
      state: string;
      search: string;
      verify: string;
      inject: string;
      maintain: string;
      active: boolean;
      backlog: number;
      failure_count: number;
      indexed_facts: number;
      facts: number;
      last_step?: string;
      updated_at?: string;
      recent_events?: Array<{
        kind?: string;
        message?: string;
        timestamp?: string;
        state?: string;
        step?: string;
        status?: string;
        data?: Record<string, unknown>;
      }>;
    };
  };
  safety: {
    dangerous_command_mode: string;
    external_actions_policy: string;
    human_communication_requires_review: boolean;
    send_message_available: boolean;
    approval_surfaces: string[];
  };
  performance: {
    available: boolean;
    error: string;
    model?: string;
    baseline_request_tokens?: number;
    best_profile?: HarnessProfile | null;
    worst_profile?: HarnessProfile | null;
    profiles: HarnessProfile[];
  };
  recommendations: string[];
}

export interface SessionInfo {
  id: string;
  source: string | null;
  model: string | null;
  title: string | null;
  started_at: number;
  ended_at: number | null;
  last_active: number;
  is_active: boolean;
  message_count: number;
  tool_call_count: number;
  input_tokens: number;
  output_tokens: number;
  preview: string | null;
}

export interface PaginatedSessions {
  sessions: SessionInfo[];
  total: number;
  limit: number;
  offset: number;
}

export interface EnvVarInfo {
  is_set: boolean;
  redacted_value: string | null;
  description: string;
  url: string | null;
  category: string;
  is_password: boolean;
  tools: string[];
  advanced: boolean;
}

export interface SessionMessage {
  role: "user" | "assistant" | "system" | "tool";
  content: string | null;
  /** Stable per-message id (client_message_id), decorated by the REST reader
   *  in web_server.get_session_messages. Used for transcriptStore dedup. */
  message_id?: string | null;
  tool_calls?: Array<{
    id: string;
    function: { name: string; arguments: string };
  }>;
  tool_name?: string;
  tool_call_id?: string;
  timestamp?: number;
  /** Per-turn output tokens, persisted on the assistant message (may be null). */
  token_count?: number | null;
  /** Persisted model reasoning, so replay can rebuild the thinking trace. */
  reasoning?: string | null;
  reasoning_content?: string | null;
}

/** One turn's usage — joined to a displayed assistant turn for the footer. */
export interface TurnUsageEntry {
  message_id?: string | null;
  model?: string | null;
  input_tokens?: number | null;
  output_tokens?: number | null;
  cache_read_tokens?: number | null;
  cache_write_tokens?: number | null;
  reasoning_tokens?: number | null;
  total_tokens?: number | null;
  estimated_cost_usd?: number | null;
  latency_ms?: number | null;
  timestamp?: number | null;
}

export interface SessionTurnUsageResponse {
  session_id: string;
  requested_session_id: string;
  turn_usage: TurnUsageEntry[];
}

export interface SessionMessagesResponse {
  session_id: string;
  requested_session_id?: string | null;
  lineage_root_id?: string | null;
  active_session_id?: string | null;
  session_kind?: string | null;
  is_compression_tip?: boolean | null;
  messages: SessionMessage[];
}

export type TodoStatus = "pending" | "in_progress" | "completed" | "cancelled";

export interface TodoItem {
  id: string;
  content: string;
  status: TodoStatus;
}

export interface SessionTodosResponse {
  session_id: string;
  requested_session_id?: string | null;
  lineage_root_id?: string | null;
  active_session_id?: string | null;
  session_kind?: string | null;
  is_compression_tip?: boolean | null;
  todos: TodoItem[];
  updated_at?: number | string | null;
  summary: {
    total: number;
    pending: number;
    in_progress: number;
    completed: number;
    cancelled: number;
  };
}

export interface SessionPlanResponse {
  session_id: string;
  requested_session_id?: string | null;
  lineage_root_id?: string | null;
  active_session_id?: string | null;
  session_kind?: string | null;
  is_compression_tip?: boolean | null;
  plan: string;
  title: string;
  updated_at?: number | string | null;
}

export interface SessionFileItem {
  path: string;
  name: string;
}

export interface SessionFilesResponse {
  session_id: string;
  requested_session_id?: string | null;
  lineage_root_id?: string | null;
  active_session_id?: string | null;
  session_kind?: string | null;
  is_compression_tip?: boolean | null;
  files: SessionFileItem[];
}

export interface SessionArtifactItem {
  id: string;
  path: string;
  name: string;
  kind: "image" | "video" | "pdf" | "document" | "file" | string;
  mime_type?: string | null;
  size?: number | null;
  modified_at?: number | string | null;
}

export interface SessionArtifactsResponse {
  session_id: string;
  requested_session_id?: string | null;
  lineage_root_id?: string | null;
  active_session_id?: string | null;
  session_kind?: string | null;
  is_compression_tip?: boolean | null;
  artifacts: SessionArtifactItem[];
}

export interface SessionChildItem {
  id: string;
  source?: string | null;
  parent_session_id?: string | null;
  started_at?: number | string | null;
  ended_at?: number | string | null;
  end_reason?: string | null;
  message_count?: number | null;
  tool_call_count?: number | null;
  input_tokens?: number | null;
  output_tokens?: number | null;
  title?: string | null;
  model?: string | null;
  session_kind?: string | null;
  lineage_root_id?: string | null;
  active_session_id?: string | null;
  is_active_session?: boolean | null;
}

export interface SessionChildrenResponse {
  session_id: string;
  requested_session_id?: string | null;
  lineage_root_id?: string | null;
  active_session_id?: string | null;
  session_kind?: string | null;
  is_compression_tip?: boolean | null;
  children: SessionChildItem[];
}

export interface LogsResponse {
  file: string;
  lines: string[];
}

export interface AnalyticsDailyEntry {
  day: string;
  input_tokens: number;
  output_tokens: number;
  cache_read_tokens: number;
  reasoning_tokens: number;
  estimated_cost: number;
  actual_cost: number;
  sessions: number;
  api_calls: number;
}

export interface AnalyticsModelEntry {
  model: string;
  input_tokens: number;
  output_tokens: number;
  estimated_cost: number;
  sessions: number;
  api_calls: number;
}

export interface AnalyticsSkillEntry {
  skill: string;
  view_count: number;
  manage_count: number;
  total_count: number;
  percentage: number;
  last_used_at: number | null;
}

export interface AnalyticsSkillsSummary {
  total_skill_loads: number;
  total_skill_edits: number;
  total_skill_actions: number;
  distinct_skills_used: number;
}

export interface AnalyticsResponse {
  daily: AnalyticsDailyEntry[];
  by_model: AnalyticsModelEntry[];
  period_days?: number;
  source?: "postgres" | "sqlite";
  totals: {
    total_input: number;
    total_output: number;
    total_cache_read: number;
    total_reasoning: number;
    total_estimated_cost: number;
    total_actual_cost: number;
    total_sessions: number;
    total_api_calls: number;
  };
  skills: {
    summary: AnalyticsSkillsSummary;
    top_skills: AnalyticsSkillEntry[];
  };
}

export interface CronJob {
  id: string;
  name?: string;
  prompt: string;
  schedule: { kind: string; expr?: string; display?: string; run_at?: string; minutes?: number };
  schedule_display: string;
  skill?: string | null;
  skills?: string[];
  workdir?: string | null;
  tier?: string | null;
  agent?: string | null;
  enabled: boolean;
  state: string;
  deliver?: string;
  paused_at?: string | null;
  paused_reason?: string | null;
  alignment_status?: "aligned" | "blocked" | "optional" | "legacy" | string | null;
  alignment_reason?: string | null;
  last_run_at?: string | null;
  next_run_at?: string | null;
  last_error?: string | null;
  last_status?: string | null;
  last_summary?: string | null;
  last_session_id?: string | null;
  stall_count?: number | null;
  backoff_until?: string | null;
  backoff_minutes?: number | null;
  metadata?: Record<string, unknown>;
  origin?: { type?: string; source?: string; [k: string]: unknown } | null;
}

export interface CronAttention {
  pending_drafts: number;
  errored_jobs: Array<{
    id: string;
    name?: string;
    last_error?: string;
    last_run_at?: string;
  }>;
  stale_jobs: Array<{
    id: string;
    name?: string;
    last_run_at?: string;
    hours_since?: number;
  }>;
  total: number;
}

export interface CronJobCreateRequest {
  prompt: string;
  schedule: string;
  name?: string;
  deliver?: string;
  skill?: string | null;
  skills?: string[];
  agent?: string | null;
  tier?: string | null;
  model?: string | null;
  provider?: string | null;
  base_url?: string | null;
  enabled_toolsets?: string[];
  workdir?: string | null;
  expected_readiness_version?: string | null;
  backfill_pending?: boolean;
  metadata?: Record<string, unknown>;
  origin?: { type?: string; source?: string; [k: string]: unknown } | null;
}

export interface SkillInfo {
  name: string;
  description: string;
  category: string;
  enabled: boolean;
}

export interface SkillTreeNode {
  name: string;
  type: "file" | "dir";
  path: string;
  children?: SkillTreeNode[];
}

export interface SkillTreeResponse {
  name: string;
  root?: string;
  tree: SkillTreeNode[];
  error?: string;
}

export interface SkillFileResponse {
  name: string;
  path: string;
  size?: number;
  content?: string;
  binary?: boolean;
  error?: string;
}

export interface BlobResponse {
  blob: Blob;
  contentType: string;
  fileName: string;
  size?: number;
}

export interface ToolsetInfo {
  name: string;
  label: string;
  description: string;
  enabled: boolean;
  configured: boolean;
  tools: string[];
}

export interface SessionSearchResult {
  session_id: string;
  snippet: string;
  role: string | null;
  source: string | null;
  model: string | null;
  session_started: number | null;
}

export interface SessionSearchResponse {
  results: SessionSearchResult[];
}

// ── Model info types ──────────────────────────────────────────────────

export interface ModelInfoResponse {
  model: string;
  provider: string;
  auto_context_length: number;
  config_context_length: number;
  effective_context_length: number;
  capabilities: {
    supports_tools?: boolean;
    supports_vision?: boolean;
    supports_reasoning?: boolean;
    context_window?: number;
    max_output_tokens?: number;
    model_family?: string;
  };
}

// ── OAuth provider types ────────────────────────────────────────────────

export interface OAuthProviderStatus {
  logged_in: boolean;
  source?: string | null;
  source_label?: string | null;
  token_preview?: string | null;
  expires_at?: string | null;
  has_refresh_token?: boolean;
  last_refresh?: string | null;
  error?: string;
}

export interface OAuthProvider {
  id: string;
  name: string;
  /** "pkce" (browser redirect + paste code), "device_code" (show code + URL),
   *  or "external" (delegated to a separate CLI like Claude Code or Qwen). */
  flow: "pkce" | "device_code" | "external";
  cli_command: string;
  docs_url: string;
  status: OAuthProviderStatus;
}

export interface OAuthProvidersResponse {
  providers: OAuthProvider[];
}

/** Discriminated union — the shape of /start depends on the flow. */
export type OAuthStartResponse =
  | {
      session_id: string;
      flow: "pkce";
      auth_url: string;
      expires_in: number;
    }
  | {
      session_id: string;
      flow: "device_code";
      user_code: string;
      verification_url: string;
      expires_in: number;
      poll_interval: number;
    };

export interface OAuthSubmitResponse {
  ok: boolean;
  status: "approved" | "error";
  message?: string;
}

export interface OAuthPollResponse {
  session_id: string;
  status: "pending" | "approved" | "denied" | "expired" | "error";
  error_message?: string | null;
  expires_at?: number | null;
}

// ── Telegram pairing types ─────────────────────────────────────────────

export interface TelegramPairStartResponse {
  ok: boolean;
  action: string;
  pid: number;
}

export interface TelegramPendingEntry {
  platform: string;
  code: string;
  user_id: string;
  user_name: string;
  /** Which agent's bot minted this code (per-agent pairing). "" = legacy/global. */
  agent_id?: string;
  age_minutes: number;
}

export interface TelegramApprovedEntry {
  platform: string;
  user_id: string;
  user_name: string;
  approved_at: number;
}

export interface TelegramPairListResponse {
  pending: TelegramPendingEntry[];
  approved: TelegramApprovedEntry[];
}

export interface TelegramPairApproveResponse {
  ok: boolean;
  user_id: string;
  user_name: string;
}

// ── Dashboard theme types ──────────────────────────────────────────────

export interface DashboardThemeSummary {
  description: string;
  label: string;
  name: string;
  /** Full theme definition for user themes; undefined for built-ins
   *  (which the frontend already has locally). */
  definition?: DashboardTheme;
}

export interface DashboardThemesResponse {
  active: string;
  themes: DashboardThemeSummary[];
}

// ── Dashboard plugin types ─────────────────────────────────────────────

export interface PluginManifestResponse {
  name: string;
  label: string;
  description: string;
  icon: string;
  version: string;
  tab: {
    path: string;
    position?: string;
    override?: string;
    hidden?: boolean;
  };
  entry: string;
  css?: string | null;
  has_api: boolean;
  source: string;
}

/* ------------------------------------------------------------------ */
/*  Surface heartbeats (per-account work+experiment loop per surface)  */
/* ------------------------------------------------------------------ */

export interface HeartbeatSurfaceExperimentConfig {
  every_n_runs?: number;
  metric?: string;
  metric_type?: string;
  direction?: string;
  window?: string;
  measurement?: string;
  approval_required?: boolean;
}

export interface HeartbeatSurfaceConfig {
  surface?: string;
  goal?: string;
  cadence?: string;
  enabled?: boolean;
  agent?: string;
  deliver?: string;
  model?: string;
  timezone?: string;
  day_mode_start?: string;
  day_mode_end?: string;
  communication_style?: string;
  approval_rules?: {
    always_ask?: string[];
    never_ask?: string[];
  };
  max_session_seconds?: number;
  heartbeat_report_mode?: "quiet" | "notify" | string;
  experiment?: HeartbeatSurfaceExperimentConfig;
  created_by?: string;
  created_at?: string;
}

/** One work-loop run (history/<ts>.json). */
export interface HeartbeatSurfaceRun {
  ran_at?: string;
  checked?: string;
  did?: string;
  found?: string;
  summary?: string;
  [key: string]: unknown;
}

/** A completed experiment (experiments/history/<id>.json). */
export interface HeartbeatSurfaceExperiment {
  id?: string;
  hypothesis?: string;
  baseline?: unknown;
  result?: unknown;
  decision?: "keep" | "discard" | string | null;
  learning?: string | null;
  ts?: string;
  [key: string]: unknown;
}

/** The currently running experiment (experiments/active.json). */
export interface HeartbeatSurfaceActiveExperiment {
  id?: string;
  hypothesis?: string;
  surface_change?: string;
  baseline?: unknown;
  started_at?: string;
  window?: string;
  [key: string]: unknown;
}

export interface HeartbeatSurfaceExperimentStats {
  total: number;
  kept: number;
  discarded: number;
  keepRate: number;
}

/** A per-surface automation cron job (origin.type === "surface-automation"). */
export interface HeartbeatSurfaceAutomation {
  id: string;
  name: string;
  schedule: string;
  enabled: boolean;
  last_run_at: string | null;
}

/** One FOCUSED heartbeat — a surface is split into several, each its own small
 *  context-first cron on its own cadence (e.g. Leads → New-Lead Response,
 *  Follow-up Sweep, Hot-Lead Watch, Re-engagement). */
export interface HeartbeatSurfaceHeartbeat {
  id: string;
  name: string;
  focus: string;
  schedule: string;
  enabled: boolean;
  experiment_owner: boolean;
  last_run_at: string | null;
}

export interface HeartbeatSurface {
  surface: string;
  config: HeartbeatSurfaceConfig | null;
  runCount: number;
  lastRun: HeartbeatSurfaceRun | null;
  learnings: string;
  heartbeats: HeartbeatSurfaceHeartbeat[];
  automations: HeartbeatSurfaceAutomation[];
  experiments: {
    active: HeartbeatSurfaceActiveExperiment | null;
    history: HeartbeatSurfaceExperiment[];
    stats: HeartbeatSurfaceExperimentStats;
  };
}

export interface HeartbeatSurfacesResponse {
  surfaces: HeartbeatSurface[];
}

/* ------------------------------------------------------------------ */
/*  Experiments page (GET /api/heartbeats/experiments)                 */
/*  Autoresearch view: each surface runs research cycles + experiments */
/*  that compound into its playbook. Read-only.                        */
/* ------------------------------------------------------------------ */

/** A research cycle definition — the loop that proposes experiments. */
export interface HeartbeatExperimentCycle {
  name: string;
  surface: string;
  agent?: string;
  metric: string;
  metric_type: string;
  direction: "higher" | "lower" | string;
  window: string;
  measurement: string;
  every_n_runs: number;
  loop_interval: string;
  approval_required: boolean;
  enabled: boolean;
}

/** A single experiment across its lifecycle. */
export interface HeartbeatExperiment {
  id: string;
  surface: string;
  agent?: string;
  status: "running" | "completed" | "proposed" | string;
  decision: "keep" | "discard" | null;
  hypothesis: string;
  changes_description: string;
  baseline: unknown;
  result: unknown;
  learning: string | null;
  metric: string;
  direction: "higher" | "lower" | string;
  window: string;
  created_at: string;
  completed_at: string | null;
}

export interface HeartbeatExperimentStats {
  total: number;
  running: number;
  proposed: number;
  completed: number;
  kept: number;
  discarded: number;
  keepRate: number;
}

export interface HeartbeatExperimentSurface {
  surface: string;
  agent?: string;
  cycles: HeartbeatExperimentCycle[];
  experiments: HeartbeatExperiment[];
  learnings: string;
  stats: HeartbeatExperimentStats;
}

export interface HeartbeatExperimentSummary {
  surfaces: number;
  cycles: number;
  total: number;
  running: number;
  completed: number;
  kept: number;
  discarded: number;
  keepRate: number;
}

export interface HeartbeatExperimentsResponse {
  surfaces: HeartbeatExperimentSurface[];
  summary: HeartbeatExperimentSummary;
}

export interface SurfaceTask {
  id: string;
  title: string;
  description?: string | null;
  type?: string | null;
  status: "pending" | "in_progress" | "blocked" | "completed" | "cancelled";
  priority: "urgent" | "high" | "normal" | "low";
  assignee?: string | null;
  assigned_to?: string | null;
  project?: string | null;
  needsApproval: boolean;
  needs_approval?: boolean;
  createdBy?: string | null;
  created_by?: string | null;
  org?: string | null;
  kpiKey?: string | null;
  kpi_key?: string | null;
  createdAt?: string | null;
  created_at?: string | null;
  updatedAt?: string | null;
  updated_at?: string | null;
  completedAt?: string | null;
  completed_at?: string | null;
  dueDate?: string | null;
  due_date?: string | null;
  archived?: boolean;
  result?: string | null;
  claimedAt?: string | null;
  claimed_at?: string | null;
  claimOwner?: string | null;
  claim_owner?: string | null;
  notes?: string | null;
  outputs?: unknown[];
  blockedBy?: string[];
  blocked_by?: string[];
  blocks?: string[];
  unresolvedDependencyIds?: string[];
  unresolvedDependencies?: Array<{
    id: string;
    title?: string | null;
    status?: string | null;
  }>;
}

export interface SurfaceTaskAuditEvent {
  id: string;
  taskId: string;
  event: string;
  actor?: string | null;
  from?: string | null;
  to?: string | null;
  note?: string | null;
  payload?: Record<string, unknown>;
  createdAt?: string | null;
  ts?: string | null;
}

export interface SurfaceTaskStaleReport {
  stale_in_progress: SurfaceTask[];
  stale_pending: SurfaceTask[];
  stale_human: SurfaceTask[];
  overdue: SurfaceTask[];
  counts?: Record<string, number>;
  total?: number;
}

export interface SurfaceApproval {
  id: string;
  title: string;
  category: "external-comms" | "financial" | "deployment" | "data-deletion" | "cost" | "access" | "other";
  description?: string | null;
  status: "pending" | "approved" | "rejected";
  surface?: string | null;
  createdAt?: string | null;
  resolvedAt?: string | null;
  resolvedBy?: string | null;
  resolutionNote?: string | null;
}
