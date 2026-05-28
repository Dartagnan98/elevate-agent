// Mock data + types for Leads page (lead desk).
// Used as fallback/scaffold when live data slots aren't populated.

export type LeadsSourceHealth = "live" | "blocked" | "error";
export type LeadsHeat = "hot" | "warm" | "cold";

export interface LeadsSource {
  id: string;
  label: string;
  count: number;
  isAll?: boolean;
  health?: LeadsSourceHealth;
}

export interface LeadsChannel {
  id: string;
  name: string;
  kind: string;
  status: LeadsSourceHealth;
  uncontacted: number;
  contacted: number;
  records: number;
  note: string;
}

export interface LeadsAvailable {
  id: string;
  label: string;
}

export interface LeadsSchedule {
  id: string;
  name: string;
  status: LeadsSourceHealth | "ok";
  schedule: string;
  last: string;
  next: string;
  detail: string;
}

export interface LeadsDraft {
  id: string;
  name: string;
  source: string;
  channel: string;
  age: string;
  body: string;
  heat: LeadsHeat | "warm" | "hot" | "cold";
  sourceId?: string;
  taskId?: string;
}

export type LeadsDraftAction = "approve" | "skip" | "restore";

export interface LeadsHotEntry {
  id: string;
  name: string;
  signal: string;
  age: string;
}

export interface LeadsSkippedEntry {
  id: string;
  name: string;
  reason: string;
}

export interface LeadsPipeline {
  hot: LeadsHotEntry[];
  followups: LeadsHotEntry[];
  buyers: number;
  skipped: LeadsSkippedEntry[];
}

export interface LeadsActivityEntry {
  id: string;
  title: string;
  kind: "cron" | "tui";
  age: string;
  messages: number;
  tools: number;
}

export interface LeadsProfile {
  id: string;
  name: string;
  heat: number;
  group: "active" | "verified" | "unverified";
  verified: boolean;
  status: string;
  source: string;
  email: string;
  phone: string;
  contact: string;
  threads: number;
  age: string;
  tags: string[];
  sub: string;
  lastMsg: string;
  lastTouch: string;
  sourceId?: string;
  threadId?: string;
}

export interface LeadsTemplateItem {
  id: string;
  name: string;
  body: string;
  used: number;
  replies: number;
  replyRate: number | null;
}

export interface LeadsTemplateLane {
  lane: string;
  icon: string;
  active: number;
  sent: number;
  replyRate: number;
  needMore: string;
  templates: LeadsTemplateItem[];
}

export interface LeadsSentMessage {
  id: string;
  when: string;
  recipient: string;
  source: string;
  transport: "SMS" | "IMESSAGE" | "STUB" | string;
  message: string;
  msgId: string;
  status: "sent" | "failed" | string;
}

export const LEADS_SOURCES: LeadsSource[] = [
  { id: "all", label: "All", count: 12, isAll: true },
  { id: "lofty", label: "Lofty CRM", count: 8, health: "live" },
  { id: "composio-insta", label: "Composio · instagram", count: 2, health: "live" },
];

export const LEADS_CHANNELS: LeadsChannel[] = [
  { id: "imessage", name: "Apple Messages", kind: "imessage", status: "blocked", uncontacted: 0, contacted: 0, records: 0, note: "Grant Full Disk Access to the terminal/app running Elevate." },
  { id: "composio-gmail", name: "Composio — gmail", kind: "gmail", status: "live", uncontacted: 0, contacted: 0, records: 728, note: "" },
  { id: "composio-insta", name: "Composio — instagram", kind: "instagram", status: "live", uncontacted: 2, contacted: 0, records: 515, note: "" },
];

export const LEADS_AVAILABLE: LeadsAvailable[] = [
  { id: "sms", label: "SMS Provider" },
  { id: "android", label: "Android Device SMS" },
  { id: "rcs", label: "RCS" },
  { id: "email", label: "Email" },
];

export const LEADS_SCHEDULES: LeadsSchedule[] = [
  { id: "outreach", name: "New Outreach", status: "error", schedule: "0 8 * * *", last: "4h ago", next: "queued", detail: "Failed to compute next run for recurring schedule (is the 'croniter' package installed in the gateway's Python env?)" },
  { id: "hot", name: "Hot Leads Watcher", status: "error", schedule: "0 8 * * *", last: "4h ago", next: "queued", detail: "Failed to compute next run for recurring schedule (is the 'croniter' package installed in the gateway's Python env?)" },
  { id: "followups", name: "Follow-ups", status: "error", schedule: "0 10,15 * * *", last: "2h ago", next: "queued", detail: "Failed to compute next run for recurring schedule (is the 'croniter' package installed in the gateway's Python env?)" },
  { id: "private", name: "Private Searches", status: "error", schedule: "0 3 * * *", last: "9h ago", next: "queued", detail: "Failed to compute next run for recurring schedule (is the 'croniter' package installed in the gateway's Python env?)" },
  { id: "seller", name: "Seller Update", status: "blocked", schedule: "0 16 * * 1-5", last: "—", next: "19d ago", detail: "Admin setup incomplete: enable after ShowingTime/BrokerBay access, Gmail draft lane, deal matching, and result callback are verified." },
];

export const LEADS_DRAFTS: LeadsDraft[] = [
  { id: "d1", name: "Randi Demo", source: "Lofty CRM", channel: "SMS", age: "4h", body: "Hi Randi! It's Avery from Demo Realty. Saw you were looking at homes on my website. I do not want to send listings that miss the mark, so what areas have been catching your eye?", heat: "warm" },
  { id: "d2", name: "Christina Sample", source: "Lofty CRM", channel: "SMS", age: "4h", body: "Hi Christina! It's Avery from Demo Realty. Saw you were looking at homes on my website. I do not want to send listings that miss the mark, so what areas have been catching your eye?", heat: "warm" },
  { id: "d3", name: "Tara Sample", source: "Lofty CRM", channel: "SMS", age: "4h", body: "Hi Tara! It's Avery from Demo Realty. Saw you were looking at one of my listings. Because it is my listing, I always like to ask first if you are already working with an agent. Are you represented already, or just casually browsing right now?", heat: "hot" },
  { id: "d4", name: "Nataly Demo", source: "Lofty CRM", channel: "SMS", age: "4h", body: "Hi Nataly! It's Avery from Demo Realty. Saw you were looking at homes on my website. I do not want to send listings that miss the mark, so what areas have been catching your eye?", heat: "warm" },
  { id: "d5", name: "Judy Sample", source: "Lofty CRM", channel: "SMS", age: "4h", body: "Hi Judy! It's Avery from Demo Realty. I saw your name come through around a property search, but I do not want to assume what you are after. Are you searching Kamloops, the Okanagan, or somewhere else?", heat: "warm" },
  { id: "d6", name: "Hannah & Bill", source: "Lofty CRM", channel: "SMS", age: "4h", body: "Hi Hannah! It's Avery from Demo Realty. I saw your name come through around a property search, but I do not want to assume what you are after. Are you searching Kamloops, the Okanagan, or somewhere else?", heat: "warm" },
  { id: "d7", name: "Elle Sample", source: "Lofty CRM", channel: "SMS", age: "4h", body: "Hi Elle! It's Avery from Demo Realty. Saw you were looking at homes on my website. I do not want to send listings that miss the mark, so what areas have been catching your eye?", heat: "warm" },
  { id: "d8", name: "Karen Sample", source: "Lofty CRM", channel: "SMS", age: "4h", body: "Hi Karen! It's Avery from Demo Realty. Saw you were looking at homes on my website. I do not want to send listings that miss the mark, so what areas have been catching your eye?", heat: "warm" },
];

export const LEADS_PIPELINE: LeadsPipeline = {
  hot: [
    { id: "h1", name: "Tara Bourassa", signal: "Replied to last touch", age: "2h" },
    { id: "h2", name: "Mark Liu", signal: "Opened listing 3×", age: "5h" },
    { id: "h3", name: "Priya Devi", signal: "Replied to listing alert", age: "yesterday" },
    { id: "h4", name: "Jordan Trent", signal: "CRM stage → Active", age: "yesterday" },
    { id: "h5", name: "Sam & Rosie", signal: "Repeat opens", age: "2d" },
  ],
  followups: [],
  buyers: 500,
  skipped: [
    { id: "s1", name: "Courtney Sijan", reason: "Already replied · 2d ago" },
    { id: "s2", name: "Hehehehehhe", reason: "Spam-y handle · no signal" },
    { id: "s3", name: "Pulkit Mittal", reason: "Off-market · just browsing" },
    { id: "s4", name: "Andra Illman", reason: "Wrong channel · prefers email" },
    { id: "s5", name: "Ashley Duffin", reason: "Out of market · Toronto" },
    { id: "s6", name: "Avery Rob", reason: "Recently signed with another agent" },
    { id: "s7", name: "Ariel Liberato", reason: "No reply in 14d · cooled" },
    { id: "s8", name: "Tanner", reason: "Already on a nurture loop" },
    { id: "s9", name: "Robin Daniel", reason: "Test contact · ignored" },
    { id: "s10", name: "Norma", reason: "Asked to be removed" },
    { id: "s11", name: "Mason Lee", reason: "Already replied · 5d ago" },
    { id: "s12", name: "Beatrice Holm", reason: "Duplicate of another profile" },
  ],
};

export const LEADS_ACTIVITY: LeadsActivityEntry[] = [
  { id: "la1", title: "Daily outreach delivery", kind: "cron", age: "2h ago", messages: 13, tools: 7 },
  { id: "la2", title: "Outreach lanes — Lofty queue", kind: "tui", age: "4h ago", messages: 57, tools: 33 },
  { id: "la3", title: "Daily outreach delivery", kind: "cron", age: "4h ago", messages: 6, tools: 2 },
  { id: "la4", title: "Outreach lanes — Composio", kind: "tui", age: "4h ago", messages: 1, tools: 0 },
  { id: "la5", title: "Daily outreach delivery", kind: "cron", age: "9h ago", messages: 24, tools: 11 },
  { id: "la6", title: "MLS Per-Listing Engagement", kind: "tui", age: "21h ago", messages: 26, tools: 12 },
];

export const LEADS_PROFILES: LeadsProfile[] = [
  { id: "p1", name: "Carol Chen", heat: 100, group: "active", verified: true, status: "Follow Up", source: "Lofty CRM", email: "carol.chen@example.com", phone: "(250) 555-0142", contact: "DB contact", threads: 1, age: "7m ago", tags: ["CRM-LEAD","LOFTY-CRM","XPOSURE-PCS"], sub: "Carol Chen from Lofty is in Active Lead via Other.", lastMsg: "Hi Avery — saw your listing, can we book a viewing this week?", lastTouch: "7m ago" },
  { id: "p2", name: "Norm Carter", heat: 100, group: "active", verified: true, status: "Follow Up", source: "Lofty CRM", email: "norm.carter@example.com", phone: "(250) 555-0188", contact: "DB contact", threads: 1, age: "7m ago", tags: ["CRM-LEAD","LOFTY-CRM","XPOSURE-PCS"], sub: "Norm Carter from Lofty is in Active Lead via Other.", lastMsg: "Got the showing time, see you at 2.", lastTouch: "7m ago" },
  { id: "p3", name: "Cal Carson", heat: 87, group: "active", verified: true, status: "New Lead", source: "Lofty CRM", email: "cal.carson@example.com", phone: "(250) 555-0211", contact: "DB contact", threads: 1, age: "7m ago", tags: ["CRM-LEAD","LOFTY-CRM","XPOSURE-PCS"], sub: "Cal Carson from Lofty is in New Leads via Other.", lastMsg: "Hey — what's pricing like in Sahali?", lastTouch: "7m ago" },
  { id: "p4", name: "David Carswell", heat: 87, group: "active", verified: true, status: "New Lead", source: "Lofty CRM", email: "david.carswell@example.com", phone: "(250) 555-0277", contact: "DB contact", threads: 1, age: "7m ago", tags: ["CRM-LEAD","LOFTY-CRM","XPOSURE-PCS"], sub: "David Carswell from Lofty is in New Leads via Other.", lastMsg: "Interested in the Greenway place. Any open houses?", lastTouch: "7m ago" },
  { id: "p5", name: "David Chestin", heat: 87, group: "active", verified: true, status: "New Lead", source: "Lofty CRM", email: "david.chestin@example.com", phone: "(250) 555-0319", contact: "DB contact", threads: 1, age: "7m ago", tags: ["CRM-LEAD","LOFTY-CRM","XPOSURE-PCS"], sub: "David Chestin from Lofty is in New Leads via Other.", lastMsg: "Are you still showing the condo downtown?", lastTouch: "7m ago" },
  { id: "p6", name: "Mindy Caruso", heat: 87, group: "active", verified: true, status: "New Lead", source: "Lofty CRM", email: "mindy.caruso@example.com", phone: "(778) 555-0356", contact: "DB contact", threads: 1, age: "7m ago", tags: ["CRM-LEAD","LOFTY-CRM","XPOSURE-PCS"], sub: "Mindy Caruso from Lofty is in New Leads via Other.", lastMsg: "Quick q on the property tax — does it include strata?", lastTouch: "7m ago" },
  { id: "p7", name: "Tracy Carver", heat: 87, group: "active", verified: true, status: "New Lead", source: "Lofty CRM", email: "tracy.carver@example.com", phone: "(778) 555-0421", contact: "DB contact", threads: 1, age: "7m ago", tags: ["CRM-LEAD","LOFTY-CRM","XPOSURE-PCS"], sub: "Tracy Carver from Lofty is in New Leads via Other.", lastMsg: "Just texted my partner, will get back tonight.", lastTouch: "7m ago" },
  { id: "p8", name: "Wayne Chorney", heat: 69, group: "active", verified: true, status: "New Lead", source: "Lofty CRM", email: "wayne.chorney@example.com", phone: "(250) 555-0468", contact: "DB contact", threads: 1, age: "7m ago", tags: ["CRM-LEAD","LOFTY-CRM","XPOSURE-PCS"], sub: "Wayne Chorney from Lofty is in New Leads via Other.", lastMsg: "Sorry for the slow reply — interested in townhomes.", lastTouch: "7m ago" },
  { id: "p9", name: "Bonnie Gerrior", heat: 100, group: "active", verified: true, status: "Follow Up", source: "Lofty CRM", email: "bonnie.gerrior@example.com", phone: "(250) 555-0509", contact: "DB contact", threads: 1, age: "7m ago", tags: ["CRM-LEAD","LOFTY-CRM","XPOSURE-PCS"], sub: "Bonnie Gerrior from Lofty is in Active Lead via Other.", lastMsg: "Yes still in the market, what's new in West End?", lastTouch: "7m ago" },
  { id: "p10", name: "Marcus Greene", heat: 60, group: "verified", verified: true, status: "Follow Up", source: "Composio", email: "marcus.greene@example.com", phone: "(604) 555-0612", contact: "Web form", threads: 0, age: "2d ago", tags: ["BUYER","COMPOSIO-IG"], sub: "Marcus Greene from Composio is queued for buyer workflow.", lastMsg: "Verified by phone, ready for the buyer fit call.", lastTouch: "2d ago" },
  { id: "p11", name: "Linda Hayworth", heat: 55, group: "verified", verified: true, status: "Follow Up", source: "Lofty CRM", email: "linda.hayworth@example.com", phone: "(250) 555-0673", contact: "DB contact", threads: 0, age: "3d ago", tags: ["SELLER","LOFTY-CRM"], sub: "Linda Hayworth is verified and ready for seller CMA.", lastMsg: "Confirmed — CMA next week works.", lastTouch: "3d ago" },
  { id: "p12", name: "Priya Devi", heat: 72, group: "verified", verified: true, status: "Follow Up", source: "Lofty CRM", email: "priya.devi@example.com", phone: "(250) 555-0734", contact: "DB contact", threads: 0, age: "4d ago", tags: ["BUYER","LOFTY-CRM"], sub: "Priya Devi verified, awaiting buyer fit call.", lastMsg: "Buyer profile filled in, send me listings.", lastTouch: "4d ago" },
  { id: "p13", name: "Tanner Brooks", heat: 45, group: "unverified", verified: false, status: "New Lead", source: "Composio", email: "tanner.brooks@example.com", phone: "(236) 555-0801", contact: "IG DM", threads: 1, age: "1d ago", tags: ["COMPOSIO-IG"], sub: "Tanner Brooks reached out via Instagram DM — needs verification.", lastMsg: "Hey, saw your reel about the West End townhomes.", lastTouch: "1d ago" },
  { id: "p14", name: "Robin Daniel", heat: 38, group: "unverified", verified: false, status: "New Lead", source: "Composio", email: "robin.daniel@example.com", phone: "(778) 555-0884", contact: "IG DM", threads: 1, age: "2d ago", tags: ["COMPOSIO-IG"], sub: "Robin Daniel via Instagram — verify before workflow.", lastMsg: "DM from IG — looking for a 2BR around Brock.", lastTouch: "2d ago" },
];

export const LEADS_TEMPLATES: LeadsTemplateLane[] = [
  {
    lane: "New Outreach",
    icon: "✨",
    active: 3, sent: 1, replyRate: 0,
    needMore: "Need 5+ more sends to rank.",
    templates: [
      { id: "t1", name: "Warm intro", body: "Hey {first_name}, saw you came through {source}. I help folks in {city} find the right place without the usual back and forth. What are you trying to figure out first?", used: 1, replies: 0, replyRate: 0 },
      { id: "t2", name: "Buyer fit", body: "Hey {first_name}, you mentioned {topic} on {source}. Quick question: are you looking to be in by a date or still figuring out timing?", used: 0, replies: 0, replyRate: null },
      { id: "t3", name: "Listing alert", body: "Hi {first_name}, a couple new {area} listings just hit that match what you flagged. Want me to send the short list?", used: 0, replies: 0, replyRate: null },
    ],
  },
  {
    lane: "Hot Leads Watcher",
    icon: "🔥",
    active: 3, sent: 0, replyRate: 0,
    needMore: "Need 5+ more sends to rank.",
    templates: [
      { id: "t4", name: "Live nudge", body: "{first_name}, just saw your {signal}. Want me to set up a viewing this week?", used: 0, replies: 0, replyRate: null },
      { id: "t5", name: "Open house live", body: "{first_name}, open house going on now at {address}. I can hold a slot for you in the next hour — want me to?", used: 0, replies: 0, replyRate: null },
      { id: "t6", name: "Just-listed match", body: "Hot off MLS — {address} just hit and matches your {criteria}. Showings booking fast. Tonight or tomorrow morning easier?", used: 0, replies: 0, replyRate: null },
    ],
  },
  {
    lane: "Follow-ups",
    icon: "↻",
    active: 6, sent: 0, replyRate: 0,
    needMore: "Need 5+ more sends to rank.",
    templates: [
      { id: "t7", name: "7 day check-in", body: "Hey {first_name}, circling back on {topic}. Anything change on your end? Happy to send fresh options.", used: 0, replies: 0, replyRate: null },
      { id: "t8", name: "Soft close", body: "Hi {first_name}, no pressure, just want to make sure I'm not missing anything. What would make the next step easy for you?", used: 0, replies: 0, replyRate: null },
      { id: "t9", name: "GIF nudge", body: "Hey {first_name}, still on the hunt? [[gif:waving-hello]]\n\nIf timing shifted, no stress — just say the word and I'll pause the alerts.", used: 0, replies: 0, replyRate: null },
      { id: "t10", name: "Market update", body: "{first_name}, quick one: median in {area} moved {delta} this month. Want a 30-second voice note breaking down what that means for your search?", used: 0, replies: 0, replyRate: null },
      { id: "t11", name: "Breakup", body: "Hey {first_name}, I'll close out the file for now so you're not getting noise. Door's open whenever — just text and I'll pick right back up.", used: 0, replies: 0, replyRate: null },
      { id: "t12", name: "Referral ask", body: "{first_name}, since timing's not right for you — anyone in your circle thinking about a move in the next 6 months? Happy to be a no-pressure resource for them too.", used: 0, replies: 0, replyRate: null },
    ],
  },
];

export const LEADS_SENT: LeadsSentMessage[] = [
  { id: "sm1", when: "5/14/2026, 11:15:03 PM", recipient: "SMS Smoketest (250) · +12509993457", source: "apple-messages", transport: "SMS", message: "elevate sms — dynamic detect should pick sms based on chat history", msgId: "sms-f117c8dffc", status: "sent" },
  { id: "sm2", when: "5/14/2026, 11:11:43 PM", recipient: "SMS Smoketest (250) · +12509993457", source: "apple-messages", transport: "IMESSAGE", message: "elevate sms test to 250 number — fallback path through messages.app", msgId: "imessage-65ec867208", status: "sent" },
  { id: "sm3", when: "5/14/2026, 11:09:08 PM", recipient: "Native dispatcher test · +12505550199", source: "apple-messages", transport: "IMESSAGE", message: "elevate native dispatcher live — if you got this, /leads can send", msgId: "imessage-d2b74dbaf1", status: "sent" },
  { id: "sm4", when: "5/14/2026, 10:56:01 PM", recipient: "test-native-imessage-001", source: "apple-messages", transport: "STUB", message: "yo this is a test from elevate — if you got this the send pipeline is live", msgId: "stub-sms-67aede9f362e", status: "sent" },
  { id: "sm5", when: "5/14/2026, 10:42:14 PM", recipient: "apple-messages-review:2026-05-15T05:35:16.403615+00:00", source: "apple-messages", transport: "STUB", message: "Confirm which imported conversations should be treated as real estate clients or leads.", msgId: "stub-sms-fa22855057b5", status: "sent" },
];
