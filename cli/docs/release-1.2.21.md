# Elevate 1.2.21 — release notes

The app can't be broken by an agent anymore.

## Safety

Agents can **read** anything (they need to, to do their job), but they can no
longer **write** to anything that would break the install:

- the app bundle (since 1.2.20),
- the installed program code and Python runtime,
- `config.yaml`,
- system paths.

Their real work is untouched — they still write freely to their own data, their
`~/Elevation` workspace, and scratch space (reports, PDFs, drafts). If an agent
tries to edit the app's code or config, it's stopped and pointed at the proper
tool (the Agent Hub Tools & Skills panel / `manage_agent`) instead.

The database was already protected: agents can read (SELECT) and add/update data
through validated operations, but cannot run schema-changing SQL (DROP/ALTER) — so
"add something to my situation" can never corrupt the database structure.

## Net

Agents are fully capable on *your data and your surfaces* (Leads, Admin, Social,
Today), and the app itself — code, config, runtime, database structure — is
off-limits. Carries the full 1.2.20 baseline.
