"""Push a lead's status to the connected CRM (Lofty / Follow Up Boss / Sierra).

The Leads board is the source of truth; the CRM is a mirror the realtor also
lives in. When the operator opts in (``crm.push_status: true`` in config), an
AI status change is reflected to the CRM so the two don't drift.

Why it's OFF by default and careful:
- A CRM's native stages are account-specific free text — our six pipeline
  statuses don't map 1:1. So pushing the STAGE requires an explicit
  ``crm.status_map`` ({our_status: "Their Stage Name"}). With a map we update
  the CRM stage; WITHOUT one we fall back to writing a note ("Elevate set
  status: follow_up") so something always lands and we never clobber the
  realtor's pipeline with a wrong stage name.
- Operator precedence is already enforced upstream (set_pipeline_status no-ops
  an AI write over an operator mark), so we only ever push AI-or-unset changes.
- Everything is best-effort and dry-run-aware; a CRM failure never fails the
  local write.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def _onboarding_crm(conn) -> dict[str, Any]:
    """The CRM push settings as captured at ONBOARDING (admin_setup_profile) —
    the source of truth the agent also reads via ADMIN_ONBOARDING.md. Empty on
    any failure so the config fallback still applies."""
    try:
        from elevate_cli.data.admin_setup import get_admin_setup
        prof = (get_admin_setup(conn) or {}).get("profile") or {}
        return {
            "push": str(prof.get("crmPushStatus") or "").strip().lower(),
            "map": prof.get("crmStatusMap") if isinstance(prof.get("crmStatusMap"), dict) else {},
        }
    except Exception:
        return {}


def _push_enabled(config: dict[str, Any], onboarding: dict[str, Any]) -> bool:
    # Onboarding profile wins; config.yaml is the fallback.
    ob = (onboarding or {}).get("push")
    if ob in ("on", "true", "1", "yes"):
        return True
    if ob in ("off", "false", "0", "no"):
        return False
    node = config.get("crm") if isinstance(config, dict) else None
    return bool(isinstance(node, dict) and node.get("push_status"))


def _status_map(config: dict[str, Any], onboarding: dict[str, Any]) -> dict[str, str]:
    ob_map = (onboarding or {}).get("map")
    if isinstance(ob_map, dict) and ob_map:
        return {str(k): str(v) for k, v in ob_map.items()}
    node = config.get("crm") if isinstance(config, dict) else None
    raw = node.get("status_map") if isinstance(node, dict) else None
    return {str(k): str(v) for k, v in raw.items()} if isinstance(raw, dict) else {}


def _dry_run(config: dict[str, Any]) -> bool:
    node = config.get("crm") if isinstance(config, dict) else None
    return bool(isinstance(node, dict) and node.get("push_dry_run"))


def push_lead_status_to_crm(conn, contact: dict[str, Any], status: str) -> dict[str, Any]:
    """Best-effort mirror of a lead's status to the CRM. Returns a small result
    dict ({pushed, mode, ...}); never raises."""
    try:
        from elevate_cli.config import load_config
        config = load_config() or {}
        onboarding = _onboarding_crm(conn)
        if not _push_enabled(config, onboarding):
            return {"pushed": False, "reason": "disabled"}

        email = (contact.get("primaryEmail") or "").strip()
        phone = (contact.get("primaryPhone") or "").strip()
        if not email and not phone:
            return {"pushed": False, "reason": "no_verifier"}

        from elevate_cli.source_connectors import (
            crm_add_note,
            crm_find_lead,
            crm_update_stage,
        )

        lead = crm_find_lead(email, config, phone=phone)
        lead_id = (lead or {}).get("id")
        if not lead_id:
            return {"pushed": False, "reason": "lead_not_in_crm"}

        name = contact.get("displayName") or "lead"
        smap = _status_map(config, onboarding)
        mapped = smap.get(status)

        if _dry_run(config):
            return {
                "pushed": False, "mode": "dry_run", "leadId": lead_id,
                "wouldSet": mapped or f"note:{status}",
            }

        if mapped:
            ok = crm_update_stage(lead_id, mapped, config=config)
            mode = "stage"
        else:
            # No mapping for this status → annotate instead of guessing a stage.
            ok = crm_add_note(
                lead_id,
                f"Elevate set lead status: {status} (no CRM stage mapping "
                "configured; set crm.status_map to sync the pipeline stage).",
                config=config,
            )
            mode = "note"
        logger.info(
            "CRM status push for %s (lead %s): mode=%s ok=%s",
            name, lead_id, mode, ok,
        )
        return {"pushed": bool(ok), "mode": mode, "leadId": lead_id, "set": mapped or status}
    except Exception as exc:  # never fail the local write
        logger.debug("CRM status push skipped: %s", exc)
        return {"pushed": False, "reason": "error", "detail": str(exc)}
