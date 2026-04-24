// Hardcoded fixture data used when ELEVATE_DEV_FIXTURE=1.
// Lets us verify the round trip without a live Supabase.

export const FIXTURE_USER = {
  id: "00000000-0000-0000-0000-000000000001",
  email: "dev@ctrlstrategies.com",
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
      tags: ["real-estate", "pricing"],
    },
    body: "# CMA Generator\n\nProduce a full CMA for the provided listing...\n\n(stub fixture body — real skill loads from Supabase in prod)\n",
  },
  {
    name: "listing-outreach",
    version: 1,
    tier_required: "pro",
    manifest: {
      description: "Draft seller outreach messages tuned to the listing's condition.",
      tags: ["real-estate", "outreach"],
    },
    body: "# Listing Outreach\n\nGiven a seller and their listing context, draft tone-appropriate messages...\n\n(stub fixture body)\n",
  },
  {
    name: "builder-only-skill",
    version: 1,
    tier_required: "builder",
    manifest: {
      description: "Advanced skill — only visible at builder tier.",
    },
    body: "# Builder-Only\n\nThis would only show up for builder-tier subs.\n",
  },
];
