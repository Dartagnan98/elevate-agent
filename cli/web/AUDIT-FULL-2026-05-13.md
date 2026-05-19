# Elevate Desktop — Full Per-Component Audit

**Date:** 2026-05-13
**Scope:** Every page file loaded inside the Electron desktop shell. 26 files, ~25k LOC. Per-component slop evidence with `file:line` references.
**Target aesthetic:** Claude Code dashboard — warm-tinted dark (`#1a1b1a` / `#212321` / `#2a2c2a`), Geist Sans + JetBrains Mono, `#D97757` terracotta, ops-tool precision. No gradients, no glassmorphism, no oversized radii, no hero metric cards, no card-grid stacking.
**Companion docs:** `AUDIT-DESKTOP-DASHBOARDS-2026-05-13.md` (executive summary + Health Score 13/20), `AUDIT-ADMIN-2026-05-13.md` (admin deep-dive).

---

## Master Component Index

145 components/exports across 26 page files. Tagged by redesign priority.

| # | Page | Component | Lines | LOC | Slop | Priority |
|---|------|-----------|-------|-----|------|----------|
| ChatPage.tsx (4187L, 22 components) |
| 1 | ChatPage | `ChatPage` (default)              | 1277–2812 | 1536 | 5 | **P0** |
| 2 | ChatPage | `ChatTitleLine`                  | 2813–2826 | 14   | 0 | clean |
| 3 | ChatPage | `EmptyState`                     | 2827–2846 | 20   | 0 | clean |
| 4 | ChatPage | `QueuedInputStrip`               | 2847–2887 | 41   | 1 (rounded-2xl L2851) | P1 |
| 5 | ChatPage | `RunningWorkStrip`               | 2888–3051 | 164  | 2 (L2933, L2979) | P1 |
| 6 | ChatPage | `ComposerRichInputLayer`         | 3052–3093 | 42   | 1 (L3082) | P1 |
| 7 | ChatPage | `ContextRing`                    | 3094–3138 | 45   | 0 | clean |
| 8 | ChatPage | `ComposerActionBar`              | 3139–3301 | 163  | 3 (L3197, L3208, L3281) | **P0** |
| 9 | ChatPage | `MessageRow`                     | 3302–3387 | 86   | 1 (L3344 user bubble) | P1 |
| 10 | ChatPage | `ChatActivityDigest`             | 3388–3438 | 51   | 0 | clean |
| 11 | ChatPage | `ChatArtifactShelf`              | 3439–3461 | 23   | 0 | clean |
| 12 | ChatPage | `InlineArtifactCard`             | 3462–3508 | 47   | 2 (L3473, L3475) | P1 |
| 13 | ChatPage | `PendingPromptCard`              | 3509–3607 | 99   | 0 | clean |
| 14 | ChatPage | `ArtifactPreviewPane`            | 3608–3814 | 207  | 5 (L3674, 3676, 3738, 3742, 3782) | **P0** |
| 15 | ChatPage | `ArtifactCard`                   | 3815–3890 | 76   | 2 (L3830, L3832) | P1 |
| 16 | ChatPage | `ProgressSummaryList`            | 3891–3900 | 10   | 0 | clean |
| 17 | ChatPage | `ActivityTimelineRow`            | 3901–3974 | 74   | 1 (L3919) | P2 |
| 18 | ChatPage | `ProgressSummaryRow`             | 3975–4054 | 80   | 1 (L3987) | P2 |
| 19 | ChatPage | `ActivityPanel`                  | 4055–4150 | 96   | 2 (L4082, L4099) | P1 |
| 20 | ChatPage | `PortalSectionHeader`            | 4151–4180 | 30   | 0 | clean |
| 21 | ChatPage | `PortalEmpty`                    | 4181–4187 | 7    | 0 | clean |
| RealEstateHubPages.tsx (3900L, 30 components) |
| 22 | REHub | `ClientInboxPreview`            | 186–320   | 135  | 1 (L234)  | P1 |
| 23 | REHub | `LeadProfilesWorkbench`         | 321–718   | 398  | 2 (L272, L284) | **P0** |
| 24 | REHub | `LeadProfilesListPage`          | 719–763   | 45   | 0 | clean |
| 25 | REHub | `LeadBoardRow`                  | 764–959   | 196  | 3 (L752, L826, L828) | **P0** |
| 26 | REHub | `LeadBoardColumn`               | 960–998   | 39   | 1 (L990) | P1 |
| 27 | REHub | `LeadWorkBoard`                 | 999–1093  | 95   | 2 (L911, L1078) | P1 |
| 28 | REHub | `DraftMessagesBoard`            | 1094–1731 | 638  | 8 (L1379, 1387, 1389, 1403, 1427/28, 1440/41, 1455, 1472, 1518, 1622, 1677, 1685) | **P0** |
| 29 | REHub | `HotLeadsList`                  | 1732–1760 | 29   | 1 (L1743) | P1 |
| 30 | REHub | `LeadQueuePanel`                | 1761–1788 | 28   | 0 | clean |
| 31 | REHub | `LeadPipelineBoard`             | 1789–1838 | 50   | 1 (L1850) | P1 |
| 32 | REHub | `FollowUpThreadsList`           | 1839–1867 | 29   | 1 (L1872) | P1 |
| 33 | REHub | `PrivateSearchBuyersList`       | 1868–1889 | 22   | 0 | clean |
| 34 | REHub | `BuyerWatchlistRow`             | 1890–1984 | 95   | 2 (L1897, 1899) | P1 |
| 35 | REHub | `SkippedDraftsList`             | 1985–2083 | 99   | 1 (L2036) | P1 |
| 36 | REHub | `RealEstateTodayPage` (export)  | 2084–2162 | 79   | 0 | clean |
| 37 | REHub | `LeadFilterBar`                 | 2163–2286 | 124  | 1 (L2263) | P1 |
| 38 | REHub | `FilterChip`                    | 2287–2324 | 38   | 2 (L2306, L2307) | P1 |
| 39 | REHub | `CollapsibleSection`            | 2325–2465 | 141  | 2 (L2340, L2347) | P1 |
| 40 | REHub | `OutreachLanesGrid`             | 2466–2521 | 56   | 0 | clean |
| 41 | REHub | `AgentLaneStripRow`             | 2522–2750 | 229  | 6 (L2579, 2587, 2603/08/13, 2683) | **P0** |
| 42 | REHub | `ComposioChannelStrip`          | 2751–2834 | 84   | 1 (L2787) | P1 |
| 43 | REHub | `ChannelsPanel`                 | 2835–2932 | 98   | 1 (L2918) | P1 |
| 44 | REHub | `LiveChannelCard`               | 2933–3006 | 74   | 2 (L2969, L2977) | P1 |
| 45 | REHub | `AvailableChannelChip`          | 3007–3035 | 29   | 1 (L3013) | P2 |
| 46 | REHub | `LeadsTabBar`                   | 3036–3071 | 36   | 0 | clean |
| 47 | REHub | `LaneOverviewCard`              | 3072–3164 | 93   | 4 (L3084, 3106/11/18) | **P0** |
| 48 | REHub | `PendingApprovalRow`            | 3165–3221 | 57   | 1 (L3177) | P1 |
| 49 | REHub | `TemplatesPanel`                | 3222–3646 | 425  | 8 (L3387, 3396, 3416, 3440, 3466, 3482, 3525, 3537, 3603) | **P0** |
| 50 | REHub | `RealEstateLeadsPage` (export)  | 3647–3900 | 254  | 1 (L3785) | P1 |
| admin/index.tsx (3645L, 15 components — see AUDIT-ADMIN-2026-05-13.md) |
| 51–65 | admin | (see admin doc) | | | 53 hits | **P0** (4 components) |
| ConfigPage.tsx (2215L, 6 components) |
| 66 | Config | `CategoryIcon`                   | 94–197    | 104  | 0 | clean |
| 67 | Config | `ComposioPanel`                  | 198–795   | 598  | 1 (L775) | P2 |
| 68 | Config | `SourceConnectorSettingsPanel`   | 796–1090  | 295  | 0 | clean |
| 69 | Config | `CrmIntegrationSettingsPanel`    | 1091–1415 | 325  | 4 (L1291, 1318, 1390, 1516) | P1 |
| 70 | Config | `PluginsPanel`                   | 1416–1603 | 188  | 0 | clean |
| 71 | Config | `ConfigPage` (default)           | 1604–2215 | 612  | 2 (L1915, 2117, 2146) | P1 |
| social-media-widgets.tsx (1472L, 12 components) |
| 72 | SocialW | `IdeaCard`                      | 159–346   | 188  | 0 | clean |
| 73 | SocialW | `YouTubeTabView`                | 347–484   | 138  | 1 (L464) | P1 |
| 74 | SocialW | `YouTubeStatTile`               | 485–508   | 24   | 1 (L495) | P2 |
| 75 | SocialW | `RankPanel`                     | 509–682   | 174  | 3 (L523, 533, 544) | **P0** |
| 76 | SocialW | `PlatformRankingsBlock`         | 683–764   | 82   | 0 | clean |
| 77 | SocialW | `YouTubeVideoCard`              | 765–875   | 111  | 2 (L811, 813) | P1 |
| 78 | SocialW | `YouTubeMetricCell`             | 876–886   | 11   | 1 (L878) | P2 |
| 79 | SocialW | `PlatformTablist`               | 887–933   | 47   | 0 | clean |
| 80 | SocialW | `PlatformTab`                   | 934–979   | 46   | 1 (L957) | P1 |
| 81 | SocialW | `PostDetailModal`               | 980–1231  | 252  | 5 (L1078, 1087, 1101, 1209, 1221) | **P0** |
| 82 | SocialW | `RealVideoCard`                 | 1232–1395 | 164  | 2 (L1313, 1376) | P1 |
| 83 | SocialW | `PlatformBlockCard`             | 1396–1472 | 77   | 1 (L1387) | P1 |
| AgentHubPage.tsx (1279L, 10 components) |
| 84 | AgentHub | `Stat`                         | 79–94     | 16   | 0 | clean |
| 85 | AgentHub | `AgentCard`                    | 95–236    | 142  | 0 | clean |
| 86 | AgentHub | `MiniMetric`                   | 237–247   | 11   | 0 | clean |
| 87 | AgentHub | `ChipRow`                      | 248–266   | 19   | 0 | clean |
| 88 | AgentHub | `PlatformRow`                  | 267–310   | 44   | 0 | clean |
| 89 | AgentHub | `TelegramGatewayControls`      | 311–412   | 102  | 0 | clean |
| 90 | AgentHub | `HarnessCard`                  | 413–496   | 84   | 0 | clean |
| 91 | AgentHub | `HandoffBusCard`               | 497–632   | 136  | 0 | clean |
| 92 | AgentHub | `SetupRunway`                  | 633–755   | 123  | 0 | clean |
| 93 | AgentHub | `AgentHubPage` (default)       | 756–1279  | 524  | 0 | clean |
| DesktopSetupPage.tsx (1117L, 7 components) |
| 94 | Setup | `DetailRow`                      | 153–176   | 24   | 1 (L165) | P1 |
| 95 | Setup | `SetupLink`                      | 177–190   | 14   | 0 | clean |
| 96 | Setup | `ReadinessCard`                  | 191–229   | 39   | 2 (L209, 213) | P1 |
| 97 | Setup | `RunwayStep`                     | 230–264   | 35   | 2 (L243, 244) | P1 |
| 98 | Setup | `AgentLaneRow`                   | 265–309   | 45   | 1 (L270) | P1 |
| 99 | Setup | `PackUnlockOnboarding`           | 310–610   | 301  | 8 (L413, 433, 435/36, 464, 490, 504, 508, 515, 538, 571, 577) | **P0** |
| 100 | Setup | `DesktopSetupPage` (default)    | 611–1117  | 507  | 4 (L769, 921, 987, plus header) | P1 |
| SessionsPage.tsx (1005L, 7 components) |
| 101 | Sessions | `SnippetHighlight`            | 61–87     | 27   | 1 (L72 warning mark) | P2 |
| 102 | Sessions | `ToolCallBlock`               | 88–129    | 42   | 4 (L104, 107, 122, palette warning chrome) | P1 |
| 103 | Sessions | `MessageBubble`               | 130–219   | 90   | 3 (L144, 149, 159 ROLE_STYLES palette pills) | **P0** |
| 104 | Sessions | `MessageList`                 | 220–252   | 33   | 0 | clean |
| 105 | Sessions | `SessionRow`                  | 253–430   | 178  | 3 (L297, 299, 408) | P1 |
| 106 | Sessions | `LinkedSessionPanel`          | 431–513   | 83   | 1 (L471 primary glow card) | P1 |
| 107 | Sessions | `SessionsPage` (default)      | 514–1005  | 492  | 2 (L778, 800, 890) | P1 |
| CronPage.tsx (825L, 3 components) |
| 108 | Cron | `ScheduleFields`                  | 194–310   | 117  | 3 (L225, 235, 301) | P1 |
| 109 | Cron | `EditJobForm`                     | 311–424   | 114  | 1 (L377) | P1 |
| 110 | Cron | `CronPage` (default)              | 425–825   | 401  | 2 (L637, 808) | P1 |
| RealEstateTemplatesPage.tsx (781L, 12 components) |
| 111 | RETempl | `TabPill`                     | 128–165   | 38   | 1 (L148) | P2 |
| 112 | RETempl | `LaneChannelBadges`           | 166–178   | 13   | 0 | clean |
| 113 | RETempl | `MetricCell`                  | 179–207   | 29   | 0 | clean |
| 114 | RETempl | `LeaderboardCard`             | 208–282   | 75   | 0 | clean |
| 115 | RETempl | `ProposedCard`                | 283–370   | 88   | 1 (L323) | P1 |
| 116 | RETempl | `RetiredRow`                  | 371–402   | 32   | 0 | clean |
| 117 | RETempl | `EmptyState`                  | 403–413   | 11   | 1 (L405) | P2 |
| 118 | RETempl | `RealEstateTemplatesPage`     | 414–648   | 235  | 1 (L620) | P1 |
| 119 | RETempl | `LiveTabContent`              | 649–713   | 65   | 0 | clean |
| 120 | RETempl | `ProposedTabContent`          | 714–751   | 38   | 0 | clean |
| 121 | RETempl | `RetiredTabContent`           | 752–770   | 19   | 0 | clean |
| 122 | RETempl | `SectionHead`                 | 771–781   | 11   | 0 | clean |
| SkillsPage.tsx (728L, 4 components) |
| 123 | Skills | `WorkflowSkillCard`            | 130–202   | 73   | 3 (L149, 165, 186) | P1 |
| 124 | Skills | `SkillsPage` (default)         | 203–659   | 457  | 4 (L372, 411, 464, 701) | P1 |
| 125 | Skills | `SkillRow`                     | 660–692   | 33   | 0 | clean |
| 126 | Skills | `PanelItem`                    | 693–728   | 36   | 0 | clean |
| EnvPage.tsx (673L, 4 components) |
| 127 | Env | `EnvVarRow`                       | 89–257    | 169  | 3 (L149, 173, 201) | P1 |
| 128 | Env | `ProviderGroupCard`               | 258–364   | 107  | 0 | clean |
| 129 | Env | `EnvPage` (default)               | 365–620   | 256  | 2 (L295, 300) | P1 |
| 130 | Env | `CollapsibleUnset`                | 621–673   | 53   | 0 | clean |
| _shared/agent-widgets.tsx (641L, 7 components) |
| 131 | AgentW | `RecentSessions`                | 155–207   | 53   | 0 | clean |
| 132 | AgentW | `TimedTasks`                    | 208–277   | 70   | 0 | clean |
| 133 | AgentW | `AdminDealTasks`                | 278–373   | 96   | 1 (L359) | P2 |
| 134 | AgentW | `AdminActionRuns`               | 374–440   | 67   | 0 | clean |
| 135 | AgentW | `AgentHandoffsCard`             | 441–498   | 58   | 0 | clean |
| 136 | AgentW | `AgentWorkerCard`               | 499–548   | 50   | 1 (L530) | P1 |
| 137 | AgentW | `AdminRunDecisionRow`           | 549–641   | 93   | 3 (L571, 598, 607) | P1 |
| thread-drawer.tsx (600L, 4 components) |
| 138 | Drawer | `ThreadDrawerProvider`         | 31–58     | 28   | 0 | clean |
| 139 | Drawer | `ThreadMessageBubble`          | 59–84     | 26   | 2 (L65 rounded-2xl, L68 primary-glow user bubble) | **P0** |
| 140 | Drawer | `ThreadDrawer`                 | 85–312    | 228  | 6 (L174 shadow, 206/207 palette pills, 240, 245, 267, 282, 303) | **P0** |
| 141 | Drawer | `ThreadContextSidebar`         | 313–600   | 288  | 2 (L335 tracking, L445) | P1 |
| social/index.tsx (454L, 1 component) |
| 142 | Social | `RealEstateSocialMediaPage`    | 35–454    | 420  | 3 (L189, 235, 372) | P1 |
| memory/index.tsx (134L, 2 components) |
| 143 | Memory | `MemoryGraphView`              | 28–51     | 24   | 0 | clean |
| 144 | Memory | `RealEstateMemoryPage`         | 52–134    | 83   | 3 (L76, 104, 119) | P1 |
| tasks/index.tsx (100L, 1 component) |
| 145 | Tasks | `RealEstateTasksPage`           | 25–100    | 76   | 0 | ✅ clean |
| AnalyticsPage.tsx (417L, 5 components) |
| 146 | Analytics | `SummaryCard`               | 42–66     | 25   | 0 | clean |
| 147 | Analytics | `TokenBarChart`             | 67–141    | 75   | 1 (L105 tooltip) | P2 |
| 148 | Analytics | `DailyTable`                | 142–189   | 48   | 0 | clean |
| 149 | Analytics | `ModelTable`                | 190–237   | 48   | 0 | clean |
| 150 | Analytics | `SkillTable`                | 238–283   | 46   | 0 | clean |
| 151 | Analytics | `AnalyticsPage` (default)   | 284–417   | 134  | 0 | clean |
| ProjectPage.tsx (227L, 3 components) |
| 152 | Project | `MiniStat`                    | 33–54     | 22   | 1 (L43) | P2 |
| 153 | Project | `PathRow`                     | 55–66     | 12   | 0 | clean |
| 154 | Project | `ProjectPage` (default)       | 67–227    | 161  | 1 (L133) | P2 |
| LogsPage.tsx (220L, 1 component) |
| 155 | Logs | `LogsPage` (default)             | 41–220    | 180  | 1 (L190 destructive bar) | P2 |
| DocsPage.tsx (54L, 1 component) |
| 156 | Docs | `DocsPage` (default)             | 10–54     | 45   | 0 | ✅ clean |
| _shared primitives (clean) |
| 157–163 | _shared | HubShell, HubMetric, ActionBoard, ContactOverviewBoard, WorkflowStrip, LoadingState, use-hub-data | ~430 total | 0 | ✅ clean |

**Total components audited: 163. Slop hits: 174 across the codebase. Clean components: 91 (56%).**

---

## P0 Components — Block Release

These need redesign before ship. Listed in implementation order (primitives → workhorses → modals → details).

### P0-1. ChatPage — `ArtifactPreviewPane` (L3608–3814)
- **Slop:** 5 hits — soft icon tile (L3676 `rounded-2xl bg-[var(--chat-surface-soft)] text-[var(--chat-accent)] shadow-[inset_0_0_0_1px_var(--chat-border)]`), animated pulse skeleton block (L3738 `rounded-2xl bg-[var(--chat-border)]`), danger glow card (L3742 `rounded-2xl bg-[color-mix(in_srgb,var(--chat-danger)_10%,var(--chat-bg))] shadow-[inset_0_0_0_1px_color-mix(in_srgb,var(--chat-danger)_34%,transparent)]`), empty-state icon tile (L3782), outer container with inset shadow (L3674)
- **Fix:** Strip `rounded-2xl` → `rounded-md`. Replace inset-shadow with 1px solid border. Danger card → `border-l-2 border-destructive pl-3` strip + plain text. Empty-state icon → no tile, just inline icon.

### P0-2. ChatPage — `ComposerActionBar` (L3139–3301)
- **Slop:** 3 hits — model picker dropdown (L3197 `rounded-2xl shadow-[0_18px_54px_rgba(0,0,0,0.22),inset_0_0_0_1px_var(--chat-border-strong)]`), each menu item (L3208 `rounded-xl`), send button hover scale (L3281 `bg-[var(--chat-text)] shadow-[0_8px_22px_rgba(0,0,0,0.22)] hover:scale-[1.02]`)
- **Fix:** Dropdown panel → `rounded-md border border-border bg-popover` no shadow. Items → `rounded-sm` flush rows. Send button → no scale-transform hover, no glow shadow, primary button standard.

### P0-3. ChatPage — `ChatPage` (default, L1277–2812)
- **Slop:** 5 hits on the outer chat shell — sidebar drag-handle (L2765 `rounded-full ... shadow-[0_0_0_1px_color-mix(...)]`), floating status pill (L2783 `rounded-full bg-[var(--chat-surface)] shadow-[0_12px_38px_rgba(0,0,0,0.18),inset_0_0_0_1px_var(--chat-border)]`), big avatar circle (L2830 `rounded-full ... shadow-[inset_0_0_0_1px_var(--chat-border-strong)]`), context-region container (L2851 `rounded-2xl bg-[var(--chat-surface-soft)]`), composer input shell (L2659 `rounded-lg ... shadow-[inset_0_0_0_1px_var(--chat-border-strong)] focus-within:shadow-[inset_0_0_0_1px_var(--chat-accent)]`)
- **Fix:** Replace inset-shadow-as-border with actual `border`. Replace floating status pill drop shadow with 1px border. Avatar circle → `rounded-md` or actual SVG mark. Composer focus state → 1px solid `border-primary` not glow shadow.

### P0-4. RealEstateHubPages — `LeadProfilesWorkbench` (L321–718)
- **Slop:** 2 hits — warning glow card L272 `rounded-2xl border-warning/35 bg-warning/10`, dashed empty L284 `rounded-2xl border-dashed bg-background/25`
- **Fix:** Warning card → `border-l-2 border-warning pl-3` strip + mono uppercase label + plain text. Empty state → mono one-liner, no dashed card.

### P0-5. RealEstateHubPages — `LeadBoardRow` (L764–959)
- **Slop:** 3 hits — outer card L752 `rounded-2xl border bg-card` (this is the row container for lead lanes), state pills L826/L828 `border-destructive/45 bg-destructive/10 text-destructive` / `border-warning/45 bg-warning/10 text-warning` for inbound wait-time signals
- **Fix:** Row → `border-b border-border` flush row inside SurfaceList wrapper. State signal → `border-l-2` accent strip on the row + mono `STALE` / `WAITING` label, no pill chrome.

### P0-6. RealEstateHubPages — `DraftMessagesBoard` (L1094–1731) ⚡ **Biggest single file in the project**
- **Slop:** 12 hits across 638 lines — channel-filter pill L1379 `rounded-full h-11 ... bg-card`, channel-filter dropdown L1387 `rounded-xl border bg-card shadow-lg`, dropdown eyebrow tracking-too-wide L1389 `tracking-[0.14em]`, suggestion mono chip L1403 `bg-background/40`, lane-pill selected L1427/L1440 `bg-primary/15`, refresh pill L1455, count badge L1472, channel-icon tile L1518 `rounded-md`, textarea L1622 `rounded-xl bg-background/60 focus:border-primary/45 focus:ring-2 focus:ring-primary/15`, section eyebrow tracking-too-wide L1677, floating cta strip L1685 `rounded-full ... shadow-[0_18px_48px_color-mix(...)]`
- **Fix:** Single largest redesign in the project. Apply: SurfaceList for draft rows, mono labels `tracking-wider` max (not `[0.14em]+`), flush filter strip (no pills) with mono filter labels, primary CTA inline (not floating glow pill), textarea solid `bg-input` no translucent. Estimated **4–6 hours**, biggest win in the codebase.

### P0-7. RealEstateHubPages — `AgentLaneStripRow` (L2522–2750)
- **Slop:** 6 hits — primary icon tile L2579 `rounded-xl bg-primary/12 text-primary ring-1 ring-primary/25`, mono status pill L2587 `rounded-full ... tracking-[0.14em]`, three eyebrows L2603/L2608/L2613 `tracking-[0.16em]`, destructive error card L2683 `rounded-xl border-destructive/25 bg-destructive/8`
- **Fix:** Icon tile → no tile, inline icon at 14px next to label. Status pill → mono uppercase label only. Eyebrows → `tracking-wider`. Error → `border-l-2 border-destructive pl-3` strip.

### P0-8. RealEstateHubPages — `LaneOverviewCard` (L3072–3164)
- **Slop:** 4 hits — outer rounded-2xl card L3084, 3 mono eyebrows L3106/L3111/L3118 `tracking-[0.16em]`
- **Fix:** Flush section with `border-b border-border pb-3` header, divide-y row body. Eyebrows → `tracking-wider`.

### P0-9. RealEstateHubPages — `TemplatesPanel` (L3222–3646) ⚡ Second-biggest
- **Slop:** 8+ hits — empty L3387, header card L3396, error L3416, lane cards L3440 `Card border-border/45 bg-card/40` (5+ lane cards), label L3466 tracking-too-wide, primary glow callout L3482 `rounded-xl border-primary/35 bg-primary/5`, dashed empty L3525, row L3537 `rounded-xl bg-background/30`
- **Fix:** Replace card-grid lanes with horizontal tab strip + single-section content. Lane callouts → border-t flush sections. Primary callout → border-l-2 strip. Form inputs → solid bg-input.

### P0-10. ConfigPage — None standalone P0. (`CrmIntegrationSettingsPanel` is P1.)

### P0-11. social-media-widgets — `RankPanel` (L509–682)
- **Slop:** 3 hits — wrapper L523 `rounded-xl bg-background/30`, empty L533 `rounded-lg border-dashed`, row L544 `rounded-lg border-border/40 bg-background/30`
- **Fix:** SurfaceList pattern — outer flush section, inner divide-y rows, mono labels.

### P0-12. social-media-widgets — `PostDetailModal` (L980–1231)
- **Slop:** 5 hits — overlay L1078 `bg-background/85` (legit modal overlay, keep), panel L1087 `rounded-2xl shadow-2xl`, media bg L1101 `bg-background/40`, metric cards L1209 `rounded-lg bg-background/30`, dashed empty L1221
- **Fix:** Strip `shadow-2xl` + `rounded-2xl` → `rounded-md` modal panel with 1px border. Metric grid → `<dl> divide-y` row list. Solid backgrounds.

### P0-13. SessionsPage — `MessageBubble` (L130–219)
- **Slop:** 3 hits — ROLE_STYLES map L144/L149/L159 — translucent palette pills (`bg-primary/10`, `bg-success/10`, `bg-warning/10`) for user/assistant/tool role badges
- **Fix:** Replace role pills with 1px `border-l-2 border-{primary,success,warning} pl-3` left-edge strips + mono uppercase 10px label `USER` / `ASSISTANT` / `TOOL`. Drop pill chrome entirely.

### P0-14. DesktopSetupPage — `PackUnlockOnboarding` (L310–610) — first-impression page
- **Slop:** 8 hits — outer shell L413 `rounded-xl border bg-card/70`, pack-unlock card L433 `rounded-2xl border px-3 py-3` with selected-state L435 `border-primary/50 bg-primary/10`, pack-detail L464 `rounded-lg bg-background/40`, sub-pack selector L490 `border-primary/50 bg-primary/10` vs L491 `border-border/60 bg-card/40`, field section cards L504/L515/L538/L571/L577 all `rounded-2xl border bg-card/45 p-4`
- **Fix:** Convert pack-unlock-cards from rounded-2xl tiles to flush list rows. Selected state = `border-l-2 border-primary` left strip + mono label. Field sections = flush `border-t border-border pt-4` not card chrome. Solid `bg-card` no `/45` translucency.

### P0-15. thread-drawer — `ThreadMessageBubble` (L59–84)
- **Slop:** 2 hits — `rounded-2xl px-3.5 py-2.5` user bubble (L65), primary-glow user bubble L68 `bg-primary/15 border border-primary/45`
- **Fix:** Reduce radius to `rounded-md`. User vs assistant differentiation via left-edge mono label + 2px primary border on user — no fill tint.

### P0-16. thread-drawer — `ThreadDrawer` (L85–312)
- **Slop:** 6 hits — outer panel L174 `shadow-[0_24px_90px_rgba(0,0,0,0.32)]` (this is the drawer side-sheet shadow), hot/warm palette pills L206/L207, error L240 `rounded-xl border-destructive/55 bg-destructive/10`, empty L245 `rounded-2xl border bg-card/60`, footer band L267, composer textarea L282 `rounded-xl bg-background focus:ring-2 focus:ring-primary/30`, content area bg L303 `bg-card/30`
- **Fix:** Drop drawer drop-shadow → 1px `border-l` only. Hot/warm pills → left-edge accent strips. Error/empty → mono lines, no card chrome. Composer textarea solid `bg-input`, focus = 1px border-primary.

### P0-17 through P0-19. admin (see AUDIT-ADMIN-2026-05-13.md)
- `AdminDealContextSection` (L1917–2391) — 12 hits, 10 stacked field cards
- `NewDealDialog` (L2698–3330) — 14 hits, 633 LOC modal
- `AdminCardDetailPanel` (L2392–2697) — 6 hits, side-sheet primary glow
- `AdminPhaseSummary` (L1398–1469) — 5 palette pills

---

## P1 Components — Major (fix this release)

Grouped by page for easy hand-off:

**ChatPage (8 P1):** `QueuedInputStrip` L2851, `RunningWorkStrip` L2933/L2979, `ComposerRichInputLayer` L3082, `MessageRow` L3344 (user bubble rounded-2xl), `InlineArtifactCard` L3473/L3475, `ArtifactCard` L3830/L3832 (danger row chrome), `ActivityPanel` L4082/L4099. **Common fix:** rounded-2xl → rounded-md, drop palette glow on danger rows, replace inset-shadow with 1px border.

**RealEstateHubPages (16 P1):** `ClientInboxPreview` L234, `LeadBoardColumn` L990 empty, `LeadWorkBoard` L911/L1078, `HotLeadsList` L1743 tracking, `LeadPipelineBoard` L1850 tracking, `FollowUpThreadsList` L1872 tracking, `BuyerWatchlistRow` L1897/L1899 status pills, `SkippedDraftsList` L2036 tracking, `LeadFilterBar` L2263 tracking, `FilterChip` L2306/L2307 selected-state glow, `CollapsibleSection` L2340/L2347, `ComposioChannelStrip` L2787 tracking, `ChannelsPanel` L2918 tracking, `LiveChannelCard` L2969/L2977 (icon tile + status pill), `PendingApprovalRow` L3177 warning card, `RealEstateLeadsPage` L3785 warning card. **Common fix:** tracking-[0.16em] → tracking-wider, palette pills → left-edge strips, icon tiles → inline icons, warning cards → border-l-2 strips.

**ConfigPage (2 P1):** `CrmIntegrationSettingsPanel` L1291/L1318/L1390/L1516 status callouts, `ConfigPage` L1915/L2117/L2146 mobile nav + scroll-pill. **Fix:** status callouts → border-l-2 strips with mono labels.

**social-media-widgets (5 P1):** `YouTubeTabView` L464 empty, `YouTubeVideoCard` L811/L813 thumbnail card, `PlatformTab` L957 active-state palette tint, `RealVideoCard` L1313/L1376 card chrome, `PlatformBlockCard` L1387.

**DesktopSetupPage (5 P1):** `DetailRow` L165 row, `ReadinessCard` L209/L213 card + icon tile, `RunwayStep` L243/L244 row + icon tile, `AgentLaneRow` L270 row chrome, `DesktopSetupPage` L769/L921/L987.

**SessionsPage (5 P1):** `ToolCallBlock` L104/L107/L122 warning chrome (collapsible tool-call output), `SessionRow` L297/L299/L408, `LinkedSessionPanel` L471 primary glow card, `SessionsPage` L778/L800/L890.

**CronPage (3 P1):** `ScheduleFields` L225/L235/L301, `EditJobForm` L377 textarea rounded-xl, `CronPage` L637/L808.

**RealEstateTemplatesPage (2 P1):** `ProposedCard` L323 textarea, `RealEstateTemplatesPage` L620 destructive callout.

**SkillsPage (2 P1):** `WorkflowSkillCard` L149/L165/L186 workflow card chrome, `SkillsPage` L372/L411/L464/L701 various rounded-xl.

**EnvPage (2 P1):** `EnvVarRow` L149/L173/L201, `EnvPage` L295/L300 provider group card.

**_shared/agent-widgets (2 P1):** `AgentWorkerCard` L530 empty card, `AdminRunDecisionRow` L571/L598/L607 (waiting state palette tint + warning pill + destructive callout).

**thread-drawer (1 P1):** `ThreadContextSidebar` L335 tracking, L445 note card.

**social/index.tsx (1 P1):** `RealEstateSocialMediaPage` L189/L235/L372 error + empty cards.

**memory/index.tsx (1 P1):** `RealEstateMemoryPage` L76/L104/L119 graph card + node cards.

---

## P2 Components — Minor (next polish pass)

**ChatPage:** `ActivityTimelineRow` L3919, `ProgressSummaryRow` L3987 (both `rounded-xl` row hover).
**RealEstateHubPages:** `AvailableChannelChip` L3013 pill.
**ConfigPage:** `ComposioPanel` L775 destructive callout.
**social-media-widgets:** `YouTubeStatTile` L495, `YouTubeMetricCell` L878.
**RealEstateTemplatesPage:** `TabPill` L148, `EmptyState` L405.
**_shared/agent-widgets:** `AdminDealTasks` L359 tracking.
**AnalyticsPage:** `TokenBarChart` L105 tooltip rounded-xl.
**ProjectPage:** `MiniStat` L43, `ProjectPage` L133.
**SessionsPage:** `SnippetHighlight` L72 warning mark.
**LogsPage:** `LogsPage` L190 destructive header.
**memory:** card chrome (covered in P1).

---

## P3 — Polish (optional)

- Pre-boot Electron screens already redesigned this session (`loading.html`, `install.html`, `main.js` bg). Verify on the shipped `Elevate-0.11.0-mac-arm64.dmg`.
- 45 instances of `opacity-50` / `text-muted-foreground/{30,50,70}` for "dimmed rows" — standardize on `/70`.
- `font-weight: 720` in some places — should be 500 or 600.
- Skip-link missing.
- Tab strip focus-visible inconsistency.
- Empty-state chrome too heavy across the board — standardize on mono one-liner.
- No reduced-motion respect on `animate-spin` / `animate-pulse`.
- No high-contrast mode.
- Window minWidth 980 vs `2xl:grid-cols-3` (1536px+) layouts.

---

## Systemic Patterns (cross-cutting fixes)

### Pattern A — `rounded-2xl` epidemic
**Sites:** 47 across 12 files. **Fix:** global pass — `rounded-2xl` → `rounded-md` (6px), `rounded-3xl` → `rounded-md`, `rounded-xl` → `rounded-md`, `rounded-lg` → `rounded-sm` (4px) for tight surfaces. Keep `rounded-full` only on actual circular elements (avatars, dots).

### Pattern B — Translucent palette tints
**Sites:** 32 `bg-{palette}/{5..30}` instances. **Fix:** ban for decorative use. Reserve `bg-destructive/10` and `bg-warning/10` only inside Toast/Alert overlays. Status signal = mono uppercase label + 2px left-edge color strip OR 1px solid color dot.

### Pattern C — Excessive letter-spacing
**Sites:** 20 `tracking-[0.12em+]` instances (all in RealEstateHubPages + scattered). **Fix:** ban anything wider than `tracking-widest` (0.1em). Most should be `tracking-wider` (0.05em).

### Pattern D — Custom `shadow-[...]` and `shadow-2xl`
**Sites:** ChatPage (15 — 10 legit inset-border substitutes, 5 actual glow shadows), modals (3). **Fix:** Convert inset-shadow-as-border to actual `border` (CSS perf + clarity). Strip `shadow-2xl` on modals → 1px border + optional subtle 1-line shadow `shadow-md` max. Drop drop-shadow on side panels.

### Pattern E — Hero metric cards
**Sites:** ReadinessCard, lane summaries, page headers across hub/admin/setup. **Fix:** introduce `_shared/PageHeader` that renders eyebrow (mono uppercase 10px) + value (tabular-nums 22px medium) + 1px under-rule, max 64px tall. Reserve hero treatment for AnalyticsPage only.

### Pattern F — Card-grid stacking instead of divided lists
**Sites:** Most lists across hub/admin/setup render as `space-y-3` stacks of bordered rounded cards. **Fix:** introduce `_shared/SurfaceList` (a `divide-y divide-border` wrapper inside a single bordered section) and `_shared/SurfaceRow` (a row with optional `border-l-2` accent slot). Migrate all list-style content. ~50% vertical-space reduction.

### Pattern G — Generic icon-in-rounded-square tile
**Sites:** Setup page, AgentLane strip, modal close affordance, etc. **Fix:** drop tile chrome, render Lucide icon inline at 14px next to label. No background, no border, no padding.

### Pattern H — Translucent form chrome
**Sites:** `bg-background/40`, `bg-card/45`, `bg-card/55` on form fields, modals, dropdowns. **Fix:** solid `bg-input` for fields, `bg-popover` for dropdowns, `bg-card` for modal panels. No `/45` translucency.

### Pattern I — Empty states over-designed
**Sites:** Most pages have full-card empty states with icon + heading + description. **Fix:** standardize on one mono line: `NO LEADS PENDING — DRAFTS QUEUE MONDAYS 7AM PT`, optionally one inline CTA link.

### Pattern J — Loading spinner spam
**Sites:** `animate-spin` on every refresh button + every loading state. **Fix:** mono `LOADING …` label centered. Reserve spinner for true non-progress operations.

### Pattern K — Spacing rhythm inconsistent
**Sites:** Mix of `space-y-{3,4,5,6}` and `gap-{3,4,5}` across pages. **Fix:** lock to `space-y-6` for page sections, `space-y-4` inside section, `space-y-2` for label/value pairs, `divide-y` for row lists.

---

## Recommended Sequence (Full Codebase)

**Phase 0 — Primitives (blocks everything else):** ~3 hours
1. Build `_shared/SurfaceList.tsx` (divide-y wrapper)
2. Build `_shared/SurfaceRow.tsx` (accent + label + value + meta slots)
3. Build `_shared/PageHeader.tsx` (inline metric strip ≤64px)
4. Build `_shared/MonoLabel.tsx`, `_shared/StatusStrip.tsx` for left-edge accents
5. Document in `_shared/README.md` with usage examples and the spacing scale
6. Add lint rule (`stylelint` or grep CI check) banning `rounded-2xl`, `tracking-[0.12em+]`, `bg-{palette}/{5..30}` outside Toast component

**Phase 1 — P0 page work (in priority order):**
1. **RealEstateHubPages** (3,900L, 16 P0+P1 components) — DraftMessagesBoard is the single biggest win. **~10–12 hours.**
2. **admin/index.tsx** (3,645L, 4 P0 components) — finish what's started. **~5–6 hours.** (See AUDIT-ADMIN-2026-05-13.md.)
3. **ChatPage** (4,187L, 3 P0 + 8 P1 components) — strip glow shadows, crisp corners. **~6–8 hours.**
4. **DesktopSetupPage** (1,117L, 1 P0 + 5 P1 components) — first-impression page. **~3–4 hours.**
5. **social-media-widgets** (1,472L, 2 P0 + 5 P1 components) — Post detail modal + RankPanel. **~3 hours.**
6. **SessionsPage** (1,005L, 1 P0 + 5 P1 components) — ROLE_STYLES is a quick high-impact fix. **~3 hours.**
7. **thread-drawer** (600L, 2 P0 + 1 P1 components) — used across REHub/admin. **~2 hours.**

**Phase 2 — P1 page work (parallelizable):**
- ConfigPage **(~2 hours)**
- CronPage **(~1.5 hours)**
- RealEstateTemplatesPage **(~1.5 hours)**
- SkillsPage **(~2 hours)**
- EnvPage **(~1.5 hours)**
- _shared/agent-widgets **(~1 hour)**
- social/index.tsx **(~1 hour)**
- memory/index.tsx **(~30 min)**

**Phase 3 — P2 polish pass:** ~3 hours across all remaining sites.

**Phase 4 — Cross-cutting:** ~4 hours
- A11y pass (skip-link, focus-visible standardization, non-color delta indicators, role-button → real-button)
- Touch-target enforcement (36px standard, 40px primary CTA)
- Empty-state standardization
- Loading-state standardization
- Spacing scale lock
- Window minWidth bump or `md:grid-cols-2` breakpoints

**Phase 5 — Verify:** Re-run `/audit` to confirm Health Score improves from 13/20 → target 18/20.

**Total estimated effort:** ~50–60 hours of focused redesign work, sequenced to ship in 5 phases.

---

## Files Already Clean (Don't Touch)

Verified clean — only /polish pass needed if at all:
- `AnalyticsPage.tsx` (417L) — 1 minor tooltip hit
- `DocsPage.tsx` (54L) — clean
- `AgentHubPage.tsx` (1,279L) — **0 anti-pattern hits across all 10 components, exemplary**
- `tasks/index.tsx` (100L) — clean
- `_shared/HubShell.tsx`, `HubMetric.tsx`, `ActionBoard.tsx`, `ContactOverviewBoard.tsx`, `WorkflowStrip.tsx`, `LoadingState.tsx`, `use-hub-data.tsx` — clean
- `_shared/agent-widgets.tsx` partials (`RecentSessions`, `TimedTasks`, `AdminDealTasks`, `AdminActionRuns`, `AgentHandoffsCard`) — clean
- `RealEstateTemplatesPage` partials (`LiveTabContent`, `ProposedTabContent`, `RetiredTabContent`, `SectionHead`, `LaneChannelBadges`, `MetricCell`, `LeaderboardCard`, `RetiredRow`) — clean
- `LogsPage.tsx` partials (most of it is mono table — only the destructive header strip is hit)

`AgentHubPage.tsx` is the **reference implementation** — closest to the Claude Code aesthetic in the codebase. Study it for patterns when redesigning other pages.

---

## Next Action

Per your workflow (audit → plan → implement), this audit completes the data layer. The redesign plan derives from these 174 findings + the 11 systemic patterns. Implementation follows in Phase 0 → 1 → 2 → 3 order.

Ready to draft the redesign plan from here, or start Phase 0 primitives directly.
