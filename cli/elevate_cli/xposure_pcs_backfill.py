"""One-shot identity heal for xposure-pcs (MLS private-search) contacts.

The old `finalize-pcs-run.py` script (in ~/elevate-premium/scripts/xposure/)
wrote contacts straight to a SQLite operational.db that no longer exists
after the PG cutover. The contacts themselves were migrated into PG, but
the identity rows that the script wrote alongside them were not — so
1,000+ xposure-pcs contacts sit in `contacts` with `primary_email` /
`primary_phone` set but ZERO matching rows in `identities`. That means
no cross-source matching: a Lofty lead with the same email never resolves
to the xposure-pcs row, so the same buyer shows up twice on /leads.

This module walks every xposure-pcs contact and:

  1. Normalizes its primary_email / primary_phone (E.164 for phones).
  2. Looks up whether either canonical value already maps to a
     different contact via the `identities` table.
  3. If a match exists on a non-self contact (typically a Lofty/CRM
     contact), MERGES the xposure-pcs contact INTO the CRM contact —
     pcs_buyers + events + identities all move over, the xposure-pcs
     row is deleted. This is the "inbox enriches CRM" pattern: CRM is
     canonical, the scrape just hydrates intent signals onto it.
  4. If no match exists, just writes the email/phone identity rows on
     the xposure-pcs contact so the next cross-source pull can merge.

Enrichment / merge only — never invents new contacts, never overwrites
human-readable names. Default is dry-run; pass --apply to commit.

Entry point: :func:`run` — invoked from the CLI as
``elevate xposure-pcs resolve [--apply]``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from elevate_cli.data import connect
from elevate_cli.data._util import normalize_email, normalize_phone
from elevate_cli.data.identities import (
    add_identity,
    merge_contacts,
    resolve_identity,
)

_log = logging.getLogger(__name__)

ACTOR = "human:xposure-pcs-backfill"


@dataclass
class BackfillStats:
    """Counters for the report. Mutated during the walk; rendered at
    end so the operator sees exactly what changed (or would change in
    dry-run)."""

    contacts_walked: int = 0
    contacts_already_resolved: int = 0
    email_identity_written: int = 0
    phone_identity_written: int = 0
    merged_into_crm: int = 0
    conflicts_recorded: int = 0
    contacts_with_no_handle: int = 0
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d = {k: v for k, v in self.__dict__.items() if k != "errors"}
        d["errors"] = list(self.errors)
        return d


def _identity_owner(conn, *, kind: str, value: str) -> str | None:
    """Return the contact_id that already owns (kind, value), or None.

    Uses raw SQL so we don't depend on resolve_identity's full row
    hydration (we only need the contact id)."""
    row = conn.execute(
        "SELECT contact_id FROM identities WHERE kind=? AND value=?",
        (kind, value),
    ).fetchone()
    return row["contact_id"] if row else None


def _has_any_identity(conn, contact_id: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM identities WHERE contact_id=? LIMIT 1",
        (contact_id,),
    ).fetchone()
    return row is not None


def run(*, apply: bool = False, actor: str = ACTOR) -> BackfillStats:
    """Walk every xposure-pcs contact, write identity rows, and merge
    into the canonical CRM contact when an email/phone match exists.

    Default ``apply=False`` is a dry-run: walk + count + render report,
    but every DB write is rolled back. Pass ``apply=True`` to commit.

    ``actor`` must start with ``human`` because the merge path calls
    :func:`merge_contacts`, which enforces that constraint.
    """
    stats = BackfillStats()

    if not actor.startswith("human"):
        stats.errors.append(
            f"actor {actor!r} must start with 'human' to run merges"
        )
        return stats

    with connect() as conn:
        rows = conn.execute(
            """
            SELECT id, display_name, primary_email, primary_phone
            FROM contacts
            WHERE source_key LIKE ?
            """,
            ("xposure-pcs:%",),
        ).fetchall()

        for row in rows:
            contact_id = row["id"]
            stats.contacts_walked += 1

            # Skip contacts that already have identities — they were
            # either healed in a prior run or came in through the
            # canonical walk_jsonl_source path.
            if _has_any_identity(conn, contact_id):
                stats.contacts_already_resolved += 1
                continue

            canon_email = normalize_email(row["primary_email"])
            canon_phone = normalize_phone(row["primary_phone"])

            if canon_email is None and canon_phone is None:
                stats.contacts_with_no_handle += 1
                continue

            # ─── Step 1: look for a canonical contact via email ──
            #
            # Email is the higher-trust signal — xposure scrapes Lofty's
            # member list so email overlap is by-design. Phone is more
            # often missing or differently formatted.
            canonical_id: str | None = None
            if canon_email:
                owner = _identity_owner(conn, kind="email", value=canon_email)
                if owner and owner != contact_id:
                    canonical_id = owner
            if canonical_id is None and canon_phone:
                owner = _identity_owner(conn, kind="phone", value=canon_phone)
                if owner and owner != contact_id:
                    canonical_id = owner

            # ─── Step 2: merge into canonical, or attach identities ──
            try:
                if canonical_id:
                    merge_contacts(
                        conn,
                        primary_id=canonical_id,
                        duplicate_id=contact_id,
                        actor=actor,
                    )
                    stats.merged_into_crm += 1
                    continue

                # Standalone xposure-pcs contact — just attach the
                # identity rows so a future Lofty pull can merge.
                if canon_email:
                    result = add_identity(
                        conn,
                        contact_id=contact_id,
                        kind="email",
                        value=canon_email,
                        source_id="xposure-pcs",
                        verified=True,
                    )
                    if result is not None:
                        # add_identity returns the existing row on
                        # conflict — detect by checking owner mismatch.
                        if result["contactId"] == contact_id:
                            stats.email_identity_written += 1
                        else:
                            stats.conflicts_recorded += 1

                if canon_phone:
                    result = add_identity(
                        conn,
                        contact_id=contact_id,
                        kind="phone",
                        value=canon_phone,
                        source_id="xposure-pcs",
                        verified=True,
                    )
                    if result is not None:
                        if result["contactId"] == contact_id:
                            stats.phone_identity_written += 1
                        else:
                            stats.conflicts_recorded += 1
            except Exception as exc:
                stats.errors.append(f"contact {contact_id}: {exc}")
                _log.exception("xposure-pcs backfill failed for %s", contact_id)

        if not apply:
            conn.rollback()
        else:
            conn.commit()

    return stats


def render(stats: BackfillStats, *, applied: bool) -> str:
    """Format a one-screen report for the CLI."""
    header = "APPLIED" if applied else "DRY-RUN"
    lines = [
        f"[{header}] xposure-pcs identity backfill",
        f"  contacts walked              : {stats.contacts_walked}",
        f"  already had identities       : {stats.contacts_already_resolved}",
        f"  merged into CRM contact      : {stats.merged_into_crm}",
        f"  email identity rows written  : {stats.email_identity_written}",
        f"  phone identity rows written  : {stats.phone_identity_written}",
        f"  identity conflicts recorded  : {stats.conflicts_recorded}",
        f"  no usable email/phone        : {stats.contacts_with_no_handle}",
    ]
    if stats.errors:
        lines.append("  errors:")
        for err in stats.errors[:20]:
            lines.append(f"    - {err}")
        if len(stats.errors) > 20:
            lines.append(f"    ... and {len(stats.errors) - 20} more")
    return "\n".join(lines)


__all__ = ["ACTOR", "BackfillStats", "render", "run"]
