// Fallback fixture data used by the file-backed HQ store.
// Repo-seeded skill folders are added on top of these in skill-seeds.ts.

export const FIXTURE_USER = {
  id: "00000000-0000-0000-0000-000000000001",
  email: "dev@elevationrealestatehq.com",
  tier: "pro" as const,
};

export const FIXTURE_LICENSE_ID = "00000000-0000-0000-0000-000000001001";

export const FIXTURE_SKILLS = [
  {
    name: "cma-generator",
    version: 1,
    tier_required: "pro",
    manifest: {
      description: "Generate a comparative market analysis from MLS + local comps.",
      category: "real-estate-marketing",
      tags: ["real-estate", "pricing"],
      entitlement: "real_estate_cma",
    },
    body: "# CMA Generator\n\nUse the `cma` workflow for full comparative market analysis: collect property facts, pull comparable listings from the configured MLS/CMA source, analyze condition and market stats, produce pricing guidance, render the report, and require human approval before client delivery.\n",
  },
  {
    name: "listing-outreach",
    version: 1,
    tier_required: "pro",
    manifest: {
      description: "Draft seller outreach messages tuned to the listing's condition.",
      category: "real-estate-sales",
      tags: ["real-estate", "outreach"],
      entitlement: "real_estate_sales",
    },
    body: "# Listing Outreach\n\nUse `outreach-lanes` for real estate sales outreach. Draft approval-gated messages from connected profiles, threads, CRM signals, and active templates. Never auto-send; write drafts to `/leads` for human approval and log attempts for outcome learning.\n",
  },
  {
    name: "builder-only-skill",
    version: 1,
    tier_required: "builder",
    manifest: {
      description: "Advanced skill — only visible at builder tier.",
      category: "real-estate-admin",
      entitlement: "real_estate_admin",
    },
    body: "# Builder-Only\n\nThis would only show up for builder-tier subs.\n",
  },
];
