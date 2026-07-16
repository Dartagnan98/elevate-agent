"""Release-channel policy for unattended scheduled execution.

The Realtor Beta intentionally ships without autonomous execution.  Keeping
the decision here gives every cron entrypoint the same exact-channel check and
prevents a config flag from re-enabling the scheduler by accident.
"""

from __future__ import annotations

from elevate_constants import exact_realtor_beta_active


BETA_SCHEDULED_EXECUTION_DISABLED_CODE = "beta_scheduled_execution_disabled"
BETA_SCHEDULED_EXECUTION_DISABLED_MESSAGE = (
    "Realtor Beta does not run cron jobs, scheduled scripts, or background "
    "agent work. Open the task in a foreground session to continue."
)


def scheduled_execution_disabled_reason() -> str | None:
    """Return the typed release-policy error when scheduling is disabled."""
    if not exact_realtor_beta_active():
        return None
    return (
        f"Error [{BETA_SCHEDULED_EXECUTION_DISABLED_CODE}]: "
        f"{BETA_SCHEDULED_EXECUTION_DISABLED_MESSAGE}"
    )
