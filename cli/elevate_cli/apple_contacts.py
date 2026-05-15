"""Read-only walker over macOS Contacts.app (AddressBook).

Populates the :class:`AddressBookIndex` — a fast, in-memory map from
normalized handle (E.164 phone or lowercased email) to a
:class:`AddressBookRecord` with the person's real name, organization, and
every other handle they have on file.

The walker is the bridge between chat.db (which only knows handles) and
the real human name (which lives in Contacts.app). Per
``docs/database-contract.md``, names are NEVER joined by string — every
chat.db handle has to flow through an ``apple_handle`` identity row to a
``contact_id``, then optionally up to an ``apple_addressbook_id`` identity
row for the matching AddressBook record.

Data flow

    ┌──────────────────────────────────────┐
    │ chat.db handle.id  '+17787163070'    │
    └───────────────┬──────────────────────┘
                    │ normalize → E.164
                    ▼
    ┌──────────────────────────────────────┐
    │ AddressBookIndex.lookup(handle)      │
    │   → AddressBookRecord (Sarah M.)     │
    └──────────────────────────────────────┘

Permission

    Read access to ``~/Library/Application Support/AddressBook/`` requires
    macOS Full Disk Access (FDA) for the running process. Terminal, cron,
    launchd, and Python all need it granted separately in System Settings
    → Privacy & Security → Full Disk Access.

    Without FDA the SQLite open returns ``OperationalError`` immediately —
    no partial state, no silent failure. Caller surfaces that as a setup
    blocker in the apple-messages connector UI.

Multiple sources

    macOS stores contacts in one or more "sources" — iCloud account,
    local-on-Mac, Google sync, etc. Each is a separate
    AddressBook-v22.abcddb under ``Sources/<uuid>/``. The walker scans
    all of them and merges into a single index. If two sources have the
    same person with different handles, both handles end up pointing at
    the same record (deduped by ``ZUNIQUEID``).
"""

from __future__ import annotations

import logging
import re
import sqlite3
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Iterator

_log = logging.getLogger(__name__)


# ─── Normalization ─────────────────────────────────────────────────────


_PHONE_DIGITS_RE = re.compile(r"\D")


def normalize_phone(raw: str | None, *, default_country: str = "1") -> str | None:
    """Normalize a phone string to E.164 (``+15551234567``).

    AddressBook stores phones in many formats: ``+17787163070``,
    ``(778) 716-3070``, ``778-716-3070``, ``17787163070``. chat.db stores
    them as E.164 (``+17787163070``). To join them we need both sides in
    the same shape.

    Returns ``None`` if the input has fewer than 7 digits — too short to
    be a real number, probably an extension or a corrupted row.

    ``default_country`` is the country code (digits, no ``+``) to assume
    when a number has no explicit prefix. Defaults to US/Canada (``1``).
    """
    if not raw:
        return None
    digits = _PHONE_DIGITS_RE.sub("", raw)
    if not digits:
        return None
    # Strip leading zeros from international trunk prefixes (e.g. UK 011).
    if raw.lstrip().startswith("+"):
        # Already had a +; trust the digits as-is.
        return f"+{digits}" if digits else None
    if len(digits) == 10:
        # Bare 10-digit — assume default country.
        return f"+{default_country}{digits}"
    if len(digits) == 11 and digits.startswith(default_country):
        return f"+{digits}"
    if len(digits) < 7:
        return None
    # Anything else: prepend +, trust the operator entered the country code.
    return f"+{digits}"


def normalize_email(raw: str | None) -> str | None:
    """Lowercase + trim. We don't punycode or strip plus-addressing
    because chat.db doesn't either — we want exact matches against what
    iMessage actually stored."""
    if not raw:
        return None
    s = raw.strip().lower()
    return s or None


# ─── Records ───────────────────────────────────────────────────────────


@dataclass
class AddressBookRecord:
    """One person in macOS Contacts.app.

    ``unique_id`` is the AddressBook's stable id — same one Apple uses
    across iCloud sync, so it's safe to persist into the identities
    table as ``kind='apple_addressbook_id'``.

    ``handles`` is every normalized phone + email this person has, used
    for reverse lookup. Cardinality is small (most people: 1-5).
    """

    unique_id: str
    first_name: str | None = None
    last_name: str | None = None
    organization: str | None = None
    nickname: str | None = None
    phones: list[str] = field(default_factory=list)
    emails: list[str] = field(default_factory=list)

    @property
    def display_name(self) -> str:
        """Render the best human-readable name we can produce.

        Order of preference: First + Last, First only, Last only,
        Nickname, Organization. If none of those are populated, fall
        back to the first handle the record has. The fallback only
        triggers on malformed AddressBook rows."""
        parts = [p for p in (self.first_name, self.last_name) if p]
        if parts:
            return " ".join(parts)
        if self.nickname:
            return self.nickname
        if self.organization:
            return self.organization
        if self.phones:
            return self.phones[0]
        if self.emails:
            return self.emails[0]
        return f"Contact {self.unique_id[:8]}"

    @property
    def handles(self) -> list[str]:
        return [*self.phones, *self.emails]


# ─── Index ─────────────────────────────────────────────────────────────


@dataclass
class AddressBookIndex:
    """In-memory map from normalized handle → AddressBookRecord.

    Records are deduped by ``unique_id`` — if the same person appears in
    multiple Sources/, the first walked one wins for name fields, but
    handles get unioned. Build once per sync (~10ms for 400 records),
    keep in memory.
    """

    records: dict[str, AddressBookRecord] = field(default_factory=dict)
    by_handle: dict[str, AddressBookRecord] = field(default_factory=dict)

    def __len__(self) -> int:
        return len(self.records)

    def lookup(self, handle: str) -> AddressBookRecord | None:
        """Resolve a chat.db handle ('+17787163070' or 'user@icloud.com')
        to a Contacts.app record. Returns None if no match. Handle is
        normalized internally so callers can pass whatever shape chat.db
        gave them."""
        if not handle:
            return None
        if "@" in handle:
            key = normalize_email(handle)
        else:
            key = normalize_phone(handle)
        if key is None:
            return None
        return self.by_handle.get(key)

    def add(self, record: AddressBookRecord) -> None:
        existing = self.records.get(record.unique_id)
        if existing is None:
            self.records[record.unique_id] = record
            for h in record.handles:
                self.by_handle.setdefault(h, record)
            return
        # Merge handles from a second source. Names stay with the
        # first-walked record to keep the result deterministic.
        for phone in record.phones:
            if phone not in existing.phones:
                existing.phones.append(phone)
                self.by_handle.setdefault(phone, existing)
        for email in record.emails:
            if email not in existing.emails:
                existing.emails.append(email)
                self.by_handle.setdefault(email, existing)


# ─── Walker ────────────────────────────────────────────────────────────


_ADDRESSBOOK_ROOT = Path.home() / "Library" / "Application Support" / "AddressBook"


class AddressBookAccessError(RuntimeError):
    """Raised when we can't open one of the AddressBook databases.

    Almost always means Full Disk Access isn't granted to the running
    process. Caller should surface this as a setup blocker, not crash."""


def _iter_addressbook_paths(root: Path = _ADDRESSBOOK_ROOT) -> Iterator[Path]:
    """Yield every AddressBook-v22.abcddb under the AddressBook root.

    The root itself has one (sometimes empty), plus one per Sources/<uuid>/.
    iCloud-synced accounts, On My Mac, Google Contacts, etc. each get
    their own Sources directory."""
    direct = root / "AddressBook-v22.abcddb"
    if direct.exists():
        yield direct
    sources_dir = root / "Sources"
    if sources_dir.is_dir():
        for child in sorted(sources_dir.iterdir()):
            candidate = child / "AddressBook-v22.abcddb"
            if candidate.exists():
                yield candidate


def _connect_readonly(path: Path) -> sqlite3.Connection:
    """Open the AddressBook in read-only mode via URI so we never risk
    writes if some upstream code forgets ``conn.rollback``."""
    uri = f"file:{path.as_posix()}?mode=ro&immutable=1"
    return sqlite3.connect(uri, uri=True, isolation_level=None)


def _walk_one_db(path: Path, default_country: str) -> Iterator[AddressBookRecord]:
    """Yield records from one AddressBook-v22.abcddb."""
    try:
        conn = _connect_readonly(path)
    except sqlite3.OperationalError as exc:
        raise AddressBookAccessError(
            f"Cannot open {path}: {exc}. Grant Full Disk Access in "
            "System Settings → Privacy & Security."
        ) from exc

    try:
        # ZABCDRECORD is the person row. Phones / emails are joined via
        # ZOWNER → ZABCDRECORD.Z_PK. We left-join twice (phones, emails)
        # using two queries instead of a 3-way join to dodge the
        # cartesian explosion on people with multiple of each.
        rows = conn.execute(
            """
            SELECT Z_PK, ZUNIQUEID, ZFIRSTNAME, ZLASTNAME, ZORGANIZATION, ZNICKNAME
            FROM ZABCDRECORD
            WHERE ZFIRSTNAME IS NOT NULL
               OR ZLASTNAME IS NOT NULL
               OR ZORGANIZATION IS NOT NULL
            """
        ).fetchall()

        phones_by_pk: dict[int, list[str]] = {}
        for pk, raw in conn.execute(
            "SELECT ZOWNER, ZFULLNUMBER FROM ZABCDPHONENUMBER "
            "WHERE ZFULLNUMBER IS NOT NULL"
        ).fetchall():
            normalized = normalize_phone(raw, default_country=default_country)
            if normalized is None:
                continue
            phones_by_pk.setdefault(pk, []).append(normalized)

        emails_by_pk: dict[int, list[str]] = {}
        for pk, raw in conn.execute(
            "SELECT ZOWNER, ZADDRESS FROM ZABCDEMAILADDRESS "
            "WHERE ZADDRESS IS NOT NULL"
        ).fetchall():
            normalized = normalize_email(raw)
            if normalized is None:
                continue
            emails_by_pk.setdefault(pk, []).append(normalized)

        for row in rows:
            pk, unique_id, first, last, org, nick = row
            if not unique_id:
                continue
            yield AddressBookRecord(
                unique_id=str(unique_id),
                first_name=first,
                last_name=last,
                organization=org,
                nickname=nick,
                phones=list(dict.fromkeys(phones_by_pk.get(pk, []))),
                emails=list(dict.fromkeys(emails_by_pk.get(pk, []))),
            )
    finally:
        conn.close()


def build_index(
    *,
    default_country: str = "1",
    root: Path | None = None,
) -> AddressBookIndex:
    """Walk every AddressBook source on disk and build a unified index.

    Raises :class:`AddressBookAccessError` if any database can't be
    opened (almost always FDA). Empty-but-readable DBs are fine — we
    skip records with no name fields, which is most of how Apple
    represents iCloud-restore artifacts.

    Default country is the assumed prefix for bare 10-digit phones.
    Override for non-NA installs.
    """
    index = AddressBookIndex()
    walked = 0
    for path in _iter_addressbook_paths(root or _ADDRESSBOOK_ROOT):
        try:
            for record in _walk_one_db(path, default_country=default_country):
                index.add(record)
            walked += 1
        except AddressBookAccessError:
            # Re-raise so the caller sees the FDA prompt. We don't want
            # silent partial indexes.
            raise
        except sqlite3.DatabaseError as exc:
            _log.warning("AddressBook db unreadable at %s: %s", path, exc)
    _log.info(
        "AddressBook index built: %d records from %d source DBs",
        len(index),
        walked,
    )
    return index


# ─── Cached helper for hot paths ───────────────────────────────────────


@lru_cache(maxsize=1)
def cached_index() -> AddressBookIndex:
    """Return a process-cached index. Call :func:`reset_cache` to
    rebuild — useful when the AddressBook changed during a long-running
    sync."""
    return build_index()


def reset_cache() -> None:
    cached_index.cache_clear()


__all__ = [
    "AddressBookAccessError",
    "AddressBookIndex",
    "AddressBookRecord",
    "build_index",
    "cached_index",
    "normalize_email",
    "normalize_phone",
    "reset_cache",
]
