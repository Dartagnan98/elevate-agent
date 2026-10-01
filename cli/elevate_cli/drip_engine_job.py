"""No-agent system job: advance the drip campaign engine.

Registered by ``cron.jobs.ensure_drip_engine_job`` and run hourly from the
scheduler. Each run is idempotent: automatic tag moves fire once per touch,
finished runs are closed once, call touches become tasks once, and new leads
are auto-enrolled only while that setting is on.
"""

from __future__ import annotations

import json
import sys


def main() -> int:
    from elevate_cli import drips_db

    with drips_db.connect() as conn:
        summary = drips_db.run_engine(conn)
    changed = (
        summary["autoEnrolled"]
        or summary["routed"]
        or summary["restarted"]
        or summary["completed"]
        or summary["tasksCreated"]
        or summary["errors"]
    )
    if changed:
        print(json.dumps(summary, indent=2))
    return 1 if summary["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
