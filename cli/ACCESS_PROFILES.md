# Elevate Access Profiles

Elevate separates the local agent from premium/team skill access.

## Profiles

- `standalone`: core local agent, local memory, and non-gated skills.
- `exp`: standalone agent plus the direct eXp real estate skill pack.
- `skyleigh_downline`: eXp pack plus Skyleigh team/downline-only skills.

Core rule:

```text
Elevate core stays available.
Personal memory stays local and is not deleted.
Purchased snapshots can stay usable.
Skyleigh team packs require active Skyleigh affiliation.
Updates/support/private registry access can require an active subscription.
```

## Commands

```bash
elevate access status
elevate access profile standalone
elevate access profile exp
elevate access profile skyleigh_downline
```

Lock or unlock an installed pack without deleting files:

```bash
elevate access unlock exp_agent_pack --owned-snapshot
elevate access lock skyleigh_team_pack --status left_team
elevate access affiliation --brokerage exp --team skyleigh --status active
elevate access affiliation --status left_team
```

## Skill Frontmatter

Premium or team-only skills declare their required entitlement in `SKILL.md`:

```yaml
---
name: listing-launch-pro
description: Listing launch workflow for eXp agents
access:
  entitlement: exp_agent_pack
---
```

Skyleigh downline-only:

```yaml
---
name: skyleigh-recruiting-system
description: Private Skyleigh team recruiting workflow
access:
  entitlement: skyleigh_team_pack
---
```

When locked, the skill is hidden from the model's skill index and slash commands.
If requested directly, `skill_view` returns a locked response instead of loading
the skill body.

## Security Reality

This is an access lock, not impossible DRM. If plaintext premium skills are
decrypted and used locally, a technical user may be able to copy them. The
business protection should come from private distribution, signed official
packs, updates, support, setup, and new workflow drops.
