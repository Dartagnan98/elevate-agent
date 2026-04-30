# Elevate Agent State

Date: 2026-04-30
Checkpoint: Elevate Agent standalone baseline before 2.0 memory work

## What This State Represents

Elevate Agent is separated from the old Hermes/RAGent naming path at the product
surface. Remaining Hermes references are intentional and limited to migration,
upstream attribution, historical/model references, and allowlisted tests or
datasets.

This state is the baseline to preserve before adding Elevate Agent 2.0 Memory.

## Included Capabilities

- `setup-elevate.sh` installs the Elevate CLI and can migrate an existing
  legacy agent profile into `~/.elevate` with a timestamped backup.
- `elevate uninstall` supports dry runs, full uninstall, named profile cleanup,
  and source-checkout protection.
- The top-level CLI presents Elevate Agent branding and an Elevate banner.
- The `elevate` launcher resolves the local virtual environment and runs
  `elevate_cli.main`.
- Legacy Hermes/RAGent environment and parser names have Elevate equivalents.
- `scripts/elevate_separation_audit.py` fails on non-allowlisted legacy coupling.
- `scripts/elevate-harness.sh` runs install, migration, uninstall, smoke, and
  separation checks in temporary homes.

## Verification Commands

```bash
scripts/elevate-harness.sh audit
scripts/elevate-harness.sh smoke
ELEVATE_INSTALL_EXTRAS='' scripts/elevate-harness.sh install
ELEVATE_INSTALL_EXTRAS='' scripts/elevate-harness.sh migration
ELEVATE_INSTALL_EXTRAS='' scripts/elevate-harness.sh uninstall
git diff --check
```

## Next Major Track

Elevate Agent 2.0 Memory should build on this baseline by adding an
Elevate-native memory core with structured entities, timeline events, graph
relations, semantic embeddings, review flows, and real-estate follow-up actions.
