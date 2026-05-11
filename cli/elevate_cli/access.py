"""Local access profiles and skill entitlement checks for Elevate.

This module is intentionally local-first. It does not make the core agent
depend on a payment server. Instead it gives Elevate a clear way to decide
which installed skill packs should be available for the current profile.
"""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from typing import Any

PROFILE_STANDALONE = "standalone"
PROFILE_EXP = "exp"
PROFILE_TEAM_PACK = "team_pack"

PROFILE_CHOICES = (
    PROFILE_STANDALONE,
    PROFILE_EXP,
    PROFILE_TEAM_PACK,
)

PROFILE_LABELS = {
    PROFILE_STANDALONE: "Standalone Agent",
    PROFILE_EXP: "Standalone eXp Agent",
    PROFILE_TEAM_PACK: "Team Pack Agent",
}

ENTITLEMENT_CORE = "elevate_core"
ENTITLEMENT_EXP = "exp_agent_pack"
ENTITLEMENT_TEAM_PACK = "real_estate_team_pack"
ENTITLEMENT_REAL_ESTATE_SALES = "real_estate_sales"
ENTITLEMENT_REAL_ESTATE_MARKETING = "real_estate_marketing"
ENTITLEMENT_REAL_ESTATE_ADMIN = "real_estate_admin"
ENTITLEMENT_REAL_ESTATE_CMA = "real_estate_cma"

REAL_ESTATE_ENTITLEMENTS = (
    ENTITLEMENT_REAL_ESTATE_SALES,
    ENTITLEMENT_REAL_ESTATE_MARKETING,
    ENTITLEMENT_REAL_ESTATE_ADMIN,
    ENTITLEMENT_REAL_ESTATE_CMA,
)

KNOWN_ENTITLEMENTS = (
    ENTITLEMENT_CORE,
    ENTITLEMENT_EXP,
    ENTITLEMENT_TEAM_PACK,
    *REAL_ESTATE_ENTITLEMENTS,
)

ACTIVE_STATUSES = {"active", "owned", "lifetime", "trial", "granted"}
LOCKED_STATUSES = {
    "locked",
    "inactive",
    "expired",
    "revoked",
    "left_team",
    "cancelled",
    "canceled",
}
ACTIVE_AFFILIATION_STATUSES = {"active", "member", "verified"}


BASE_ACCESS_CONFIG: dict[str, Any] = {
    "profile": PROFILE_STANDALONE,
    "offline_grace_days": 14,
    "affiliation": {
        "brokerage": "",
        "team": "",
        "status": "active",
    },
    "entitlements": {
        ENTITLEMENT_CORE: {
            "status": "active",
            "owned_snapshot": True,
            "description": "Core local Elevate runtime and personal data.",
        },
        ENTITLEMENT_EXP: {
            "status": "locked",
            "owned_snapshot": False,
            "description": "Direct eXp real estate skill pack.",
        },
        ENTITLEMENT_TEAM_PACK: {
            "status": "locked",
            "owned_snapshot": False,
            "requires_active_affiliation": True,
            "description": "team-only skill pack.",
        },
        ENTITLEMENT_REAL_ESTATE_SALES: {
            "status": "locked",
            "owned_snapshot": False,
            "description": "Paid real estate sales, leads, and outreach dashboards and skills.",
        },
        ENTITLEMENT_REAL_ESTATE_MARKETING: {
            "status": "locked",
            "owned_snapshot": False,
            "description": "Paid real estate marketing, listing launch, and social dashboards and skills.",
        },
        ENTITLEMENT_REAL_ESTATE_ADMIN: {
            "status": "locked",
            "owned_snapshot": False,
            "description": "Paid real estate admin transaction dashboards, automations, and skills.",
        },
        ENTITLEMENT_REAL_ESTATE_CMA: {
            "status": "locked",
            "owned_snapshot": False,
            "description": "Paid real estate CMA pricing and report-generation skills.",
        },
    },
}


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def default_access_config(profile: str = PROFILE_STANDALONE) -> dict[str, Any]:
    """Return a fresh access config for one of the supported profiles."""
    profile = normalize_profile(profile)
    cfg = copy.deepcopy(BASE_ACCESS_CONFIG)
    cfg["profile"] = profile

    if profile == PROFILE_EXP:
        cfg["affiliation"].update({"brokerage": "exp", "team": "", "status": "active"})
        cfg["entitlements"][ENTITLEMENT_EXP].update(
            {"status": "active", "owned_snapshot": True}
        )
    elif profile == PROFILE_TEAM_PACK:
        cfg["affiliation"].update(
            {"brokerage": "exp", "team": "team", "status": "active"}
        )
        cfg["entitlements"][ENTITLEMENT_EXP].update(
            {"status": "active", "owned_snapshot": True}
        )
        cfg["entitlements"][ENTITLEMENT_TEAM_PACK].update(
            {"status": "active", "owned_snapshot": False}
        )

    return cfg


def normalize_profile(profile: str | None) -> str:
    profile = (profile or PROFILE_STANDALONE).strip().lower().replace("-", "_")
    aliases = {
        "personal": PROFILE_STANDALONE,
        "standalone_agent": PROFILE_STANDALONE,
        "exp_agent": PROFILE_EXP,
        "standalone_exp": PROFILE_EXP,
        "aexp": PROFILE_EXP,
        "team": PROFILE_TEAM_PACK,
        "downline": PROFILE_TEAM_PACK,
        "team_pack": PROFILE_TEAM_PACK,
    }
    profile = aliases.get(profile, profile)
    if profile not in PROFILE_CHOICES:
        choices = ", ".join(PROFILE_CHOICES)
        raise ValueError(f"Unknown access profile '{profile}'. Choose: {choices}")
    return profile


def normalize_access_config(raw: dict[str, Any] | None) -> dict[str, Any]:
    raw = raw if isinstance(raw, dict) else {}
    profile = normalize_profile(raw.get("profile"))
    cfg = _deep_merge(default_access_config(profile), raw)
    cfg["profile"] = profile

    entitlements = cfg.setdefault("entitlements", {})
    for name, template in BASE_ACCESS_CONFIG["entitlements"].items():
        if not isinstance(entitlements.get(name), dict):
            entitlements[name] = copy.deepcopy(template)
        else:
            entitlements[name] = _deep_merge(template, entitlements[name])

    # A profile is a product-mode default. Config files created from
    # DEFAULT_CONFIG include locked known entitlements, so promote those default
    # locks when the profile itself implies access. Explicit revocations,
    # expirations, left-team states, or locks set through `elevate access lock`
    # are kept.
    if profile in (PROFILE_EXP, PROFILE_TEAM_PACK):
        exp_entry = entitlements.get(ENTITLEMENT_EXP) or {}
        if _status(exp_entry.get("status")) == "locked" and not exp_entry.get("manual_lock"):
            exp_entry["status"] = "active"
            exp_entry["owned_snapshot"] = True
    if profile == PROFILE_TEAM_PACK:
        team_entry = entitlements.get(ENTITLEMENT_TEAM_PACK) or {}
        if _status(team_entry.get("status")) == "locked" and not team_entry.get("manual_lock"):
            team_entry["status"] = "active"

    affiliation = cfg.setdefault("affiliation", {})
    if not isinstance(affiliation, dict):
        cfg["affiliation"] = copy.deepcopy(BASE_ACCESS_CONFIG["affiliation"])

    return cfg


def load_access_config(config: dict[str, Any] | None = None) -> dict[str, Any]:
    """Load the normalized access config from an optional full config dict."""
    if config is None:
        from elevate_cli.config import read_raw_config

        config = read_raw_config()
    raw = config.get("access") if isinstance(config, dict) else {}
    return normalize_access_config(raw)


def save_access_config(access_config: dict[str, Any]) -> None:
    from elevate_cli.config import load_config, save_config

    cfg = load_config()
    cfg["access"] = normalize_access_config(access_config)
    save_config(cfg)


def _status(value: Any) -> str:
    return str(value or "locked").strip().lower()


def _affiliation_is_active(access_config: dict[str, Any]) -> bool:
    affiliation = access_config.get("affiliation")
    if not isinstance(affiliation, dict):
        return False
    return _status(affiliation.get("status")) in ACTIVE_AFFILIATION_STATUSES


def is_entitlement_active(
    entitlement: str,
    access_config: dict[str, Any] | None = None,
) -> bool:
    """Return whether an entitlement may be used under the current profile."""
    entitlement = str(entitlement or "").strip()
    if not entitlement:
        return True

    access_config = load_access_config({"access": access_config}) if access_config else load_access_config()
    if entitlement == ENTITLEMENT_CORE:
        return True

    entitlements = access_config.get("entitlements") or {}
    entry = entitlements.get(entitlement)
    if not isinstance(entry, dict):
        return False

    requires_affiliation = bool(entry.get("requires_active_affiliation"))
    if requires_affiliation and not _affiliation_is_active(access_config):
        return False

    status = _status(entry.get("status"))
    if status in ACTIVE_STATUSES:
        return True

    # Owned snapshots stay usable for personal/direct packs, but do not override
    # team-affiliation locks such as the pilot realtor downline pack.
    if entry.get("owned_snapshot") and not requires_affiliation:
        return True

    return False


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, (list, tuple, set)):
        return []
    result: list[str] = []
    for item in value:
        text = str(item or "").strip()
        if text:
            result.append(text)
    return result


def required_entitlements_from_frontmatter(frontmatter: dict[str, Any]) -> list[str]:
    """Extract entitlement requirements from a skill's YAML frontmatter."""
    if not isinstance(frontmatter, dict):
        return []

    required: list[str] = []

    access = frontmatter.get("access")
    if isinstance(access, dict):
        for key in (
            "entitlement",
            "requires_entitlement",
            "required_entitlement",
            "entitlements",
            "requires_entitlements",
            "required_entitlements",
        ):
            required.extend(_as_list(access.get(key)))

    metadata = frontmatter.get("metadata")
    elevate_meta = metadata.get("elevate") if isinstance(metadata, dict) else None
    if isinstance(elevate_meta, dict):
        for key in (
            "entitlement",
            "requires_entitlement",
            "required_entitlement",
            "entitlements",
            "requires_entitlements",
            "required_entitlements",
        ):
            required.extend(_as_list(elevate_meta.get(key)))

    for key in ("requires_entitlement", "required_entitlement"):
        required.extend(_as_list(frontmatter.get(key)))

    seen: set[str] = set()
    deduped: list[str] = []
    for entitlement in required:
        if entitlement not in seen:
            seen.add(entitlement)
            deduped.append(entitlement)
    return deduped


@dataclass(frozen=True)
class AccessDecision:
    allowed: bool
    required_entitlements: tuple[str, ...] = ()
    locked_entitlements: tuple[str, ...] = ()
    profile: str = PROFILE_STANDALONE

    @property
    def reason(self) -> str:
        if self.allowed:
            return "available"
        locked = ", ".join(self.locked_entitlements) or "required entitlement"
        return (
            f"Requires locked entitlement: {locked}. Core Elevate and personal "
            "memory remain available."
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "required_entitlements": list(self.required_entitlements),
            "locked_entitlements": list(self.locked_entitlements),
            "profile": self.profile,
            "reason": self.reason,
        }


def evaluate_skill_access(
    frontmatter: dict[str, Any],
    config: dict[str, Any] | None = None,
) -> AccessDecision:
    access_config = load_access_config(config)
    required = tuple(required_entitlements_from_frontmatter(frontmatter))
    if not required:
        return AccessDecision(True, profile=access_config["profile"])

    locked = tuple(
        entitlement
        for entitlement in required
        if not is_entitlement_active(entitlement, access_config)
    )
    return AccessDecision(
        allowed=not locked,
        required_entitlements=required,
        locked_entitlements=locked,
        profile=access_config["profile"],
    )


def set_profile(profile: str) -> dict[str, Any]:
    from elevate_cli.config import load_config, save_config

    cfg = load_config()
    existing = load_access_config()
    updated = default_access_config(profile)
    if existing.get("offline_grace_days") is not None:
        updated["offline_grace_days"] = existing["offline_grace_days"]
    for name, entry in (existing.get("entitlements") or {}).items():
        if name not in KNOWN_ENTITLEMENTS or name in REAL_ESTATE_ENTITLEMENTS:
            updated.setdefault("entitlements", {})[name] = copy.deepcopy(entry)
    cfg["access"] = updated
    save_config(cfg)
    return updated


def dashboard_access_status(access_config: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return entitlement state shaped for dashboard route/pack gating."""
    access_config = (
        load_access_config({"access": access_config})
        if access_config
        else load_access_config()
    )
    entitlements = access_config.get("entitlements") or {}
    ordered = list(KNOWN_ENTITLEMENTS) + [
        name for name in sorted(entitlements) if name not in KNOWN_ENTITLEMENTS
    ]

    entitlement_payload: dict[str, dict[str, Any]] = {}
    for name in ordered:
        entry = entitlements.get(name)
        if not isinstance(entry, dict):
            continue
        entitlement_payload[name] = {
            "status": entry.get("status", "locked"),
            "active": is_entitlement_active(name, access_config),
            "ownedSnapshot": bool(entry.get("owned_snapshot")),
            "description": entry.get("description") or "",
            "requiresActiveAffiliation": bool(entry.get("requires_active_affiliation")),
            "manualLock": bool(entry.get("manual_lock")),
        }

    sales = is_entitlement_active(ENTITLEMENT_REAL_ESTATE_SALES, access_config)
    marketing = is_entitlement_active(ENTITLEMENT_REAL_ESTATE_MARKETING, access_config)
    admin = is_entitlement_active(ENTITLEMENT_REAL_ESTATE_ADMIN, access_config)
    cma = is_entitlement_active(ENTITLEMENT_REAL_ESTATE_CMA, access_config)

    return {
        "profile": access_config["profile"],
        "entitlements": entitlement_payload,
        "packs": {
            "realEstateSales": sales,
            "realEstateMarketing": marketing,
            "realEstateAdmin": admin,
            "realEstateCma": cma,
            "realEstateAny": any((sales, marketing, admin, cma)),
        },
    }


def update_entitlement(
    entitlement: str,
    *,
    status: str,
    owned_snapshot: bool | None = None,
) -> dict[str, Any]:
    from elevate_cli.config import load_config, save_config

    entitlement = str(entitlement or "").strip()
    if not entitlement:
        raise ValueError("entitlement is required")

    cfg = load_config()
    access = load_access_config()
    entitlements = access.setdefault("entitlements", {})
    entry = entitlements.setdefault(entitlement, {"description": ""})
    entry["status"] = status
    if owned_snapshot is not None:
        entry["owned_snapshot"] = bool(owned_snapshot)
    if _status(status) in LOCKED_STATUSES:
        entry["manual_lock"] = True
    else:
        entry.pop("manual_lock", None)
    save_config({**cfg, "access": access})
    return access


def update_affiliation(
    *,
    brokerage: str | None = None,
    team: str | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    from elevate_cli.config import load_config, save_config

    cfg = load_config()
    access = load_access_config()
    affiliation = access.setdefault("affiliation", {})
    if brokerage is not None:
        affiliation["brokerage"] = brokerage
    if team is not None:
        affiliation["team"] = team
    if status is not None:
        affiliation["status"] = status
    save_config({**cfg, "access": access})
    return access


def format_status(access_config: dict[str, Any] | None = None) -> str:
    access_config = load_access_config({"access": access_config}) if access_config else load_access_config()
    profile = access_config["profile"]
    affiliation = access_config.get("affiliation") or {}

    lines = [
        f"Access profile: {PROFILE_LABELS.get(profile, profile)} ({profile})",
        (
            "Affiliation: "
            f"brokerage={affiliation.get('brokerage') or '-'} "
            f"team={affiliation.get('team') or '-'} "
            f"status={affiliation.get('status') or '-'}"
        ),
        "Entitlements:",
    ]
    entitlements = access_config.get("entitlements") or {}
    ordered = list(KNOWN_ENTITLEMENTS) + [
        name for name in sorted(entitlements) if name not in KNOWN_ENTITLEMENTS
    ]
    for name in ordered:
        entry = entitlements.get(name)
        if not isinstance(entry, dict):
            continue
        usable = is_entitlement_active(name, access_config)
        status = entry.get("status", "locked")
        owned = " owned_snapshot" if entry.get("owned_snapshot") else ""
        manual = " manual_lock" if entry.get("manual_lock") else ""
        requires_team = (
            " requires_active_affiliation"
            if entry.get("requires_active_affiliation")
            else ""
        )
        marker = "available" if usable else "locked"
        lines.append(f"  - {name}: {marker} (status={status}{owned}{manual}{requires_team})")
    return "\n".join(lines)


def cmd_access(args) -> int:
    action = getattr(args, "access_action", None) or "status"

    try:
        if action == "status":
            if getattr(args, "json", False):
                print(json.dumps(load_access_config(), indent=2))
            else:
                print(format_status())
            return 0

        if action == "profile":
            updated = set_profile(args.profile)
            print(format_status(updated))
            return 0

        if action == "unlock":
            updated = update_entitlement(
                args.entitlement,
                status="active",
                owned_snapshot=getattr(args, "owned_snapshot", None),
            )
            print(format_status(updated))
            return 0

        if action == "lock":
            updated = update_entitlement(
                args.entitlement,
                status=getattr(args, "status", None) or "locked",
                owned_snapshot=False if getattr(args, "clear_owned_snapshot", False) else None,
            )
            print(format_status(updated))
            return 0

        if action == "affiliation":
            updated = update_affiliation(
                brokerage=args.brokerage,
                team=args.team,
                status=args.status,
            )
            print(format_status(updated))
            return 0

    except ValueError as exc:
        print(f"error: {exc}")
        return 2

    print(f"unknown access action: {action}")
    return 2
