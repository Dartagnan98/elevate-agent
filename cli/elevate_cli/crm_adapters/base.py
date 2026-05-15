"""CRM adapter contract — provider-agnostic dataclasses + ABC.

Each adapter (Lofty, FUB, Sierra, Brivity, BoldTrail) implements this
interface so the sync cron is provider-blind:

    adapter = get_adapter(provider, env_values)
    detail = adapter.fetch_lead_detail(remote_lead_id)
    upsert_lead_inquiry(conn, contact_id, detail.inquiry)
    upsert_lead_properties(conn, contact_id, detail.properties)
    update_contact_qualification(conn, contact_id, detail.qualification)
    update_contact_consent(conn, contact_id, detail.consent)
    for txn in adapter.fetch_transactions(remote_lead_id):
        upsert_deal(conn, contact_id, txn)
    for note in adapter.fetch_notes(remote_lead_id, since=last_sync):
        pull_mirror_note(conn, contact_id, note)

Dataclass field names match the operational.db column names exactly
(snake_case) so the writer code is a 1:1 mapping with no translation
layer.

Lofty is the only CRM that bundles inquiry + properties + qualification
+ consent into a single detail call. The other providers may need 2-4
HTTP calls per lead — each adapter hides that internally.

BoldTrail is partner-API only. Its adapter raises
:class:`NotImplementedError` until Inside Real Estate grants access.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Iterable


# ─── Normalized shapes ─────────────────────────────────────────────────


@dataclass
class CrmInquiry:
    """Buyer search criteria — one per contact (1:1 with lead_inquiries).

    All numeric ranges may be None (operator didn't fill them in).
    ``locations`` is a free-form list of strings as the CRM stores it —
    "Saskatoon", "S7K 0H4", "Stonebridge". Geocoding happens downstream
    if at all; the adapter doesn't normalize geography.
    """

    price_min: int | None = None
    price_max: int | None = None
    property_types: list[str] = field(default_factory=list)
    bedrooms_min: int | None = None
    bedrooms_max: int | None = None
    bathrooms_min: str | None = None
    bathrooms_max: str | None = None
    locations: list[str] = field(default_factory=list)
    modify_by_agent: bool | None = None
    is_default: bool | None = None
    source_created_at: str | None = None
    source_updated_at: str | None = None


@dataclass
class CrmProperty:
    """One property of interest / favorite — many per contact.

    ``source_record_id`` is the CRM's native id for the property row
    (NOT the MLS id). We dedupe on (contact_id, source_record_id) so
    re-imports are idempotent.
    """

    source_record_id: str
    listing_id: str | None = None
    auto_listing_id: str | None = None
    address: str | None = None
    city: str | None = None
    region: str | None = None
    postal_code: str | None = None
    country: str | None = None
    beds: int | None = None
    baths: str | None = None
    sqft: int | None = None
    lot_size: str | None = None
    parking: str | None = None
    floors: int | None = None
    price: int | None = None
    price_min: int | None = None
    price_max: int | None = None
    label: str | None = None
    label_type: str | None = None
    label_list: list[str] = field(default_factory=list)
    picture_url: str | None = None
    site_listing_url: str | None = None
    is_mailing_address: bool | None = None
    source_created_at: str | None = None
    source_updated_at: str | None = None


@dataclass
class CrmQualification:
    """Buying/selling readiness signals — folded into contacts table.

    All fields are free-form strings as the CRM stores them — Lofty uses
    enums like ``'1-3 months'``, FUB uses customField labels, Sierra uses
    flag names. We persist what the CRM gave us; downstream UI buckets
    them.
    """

    buying_time_frame: str | None = None
    selling_time_frame: str | None = None
    pre_qual_status: str | None = None
    has_house_to_sell: str | None = None
    first_time_home_buyer: str | None = None
    with_buyer_agent: str | None = None
    with_listing_agent: str | None = None
    mortgage_status: str | None = None
    buy_house_intent: str | None = None
    opportunity: str | None = None
    referred_by: str | None = None
    pond_id: str | None = None
    pond_name: str | None = None
    lead_types: list[str] = field(default_factory=list)
    segments: list[str] = field(default_factory=list)


@dataclass
class CrmConsent:
    """DNC / opt-out flags — folded into contacts table.

    All four channel flags are booleans. ``hidden`` mirrors Lofty's
    "archive" semantics — contact still exists but operator chose to hide
    it from the active queue.
    """

    cannot_text: bool = False
    cannot_call: bool = False
    cannot_email: bool = False
    unsubscribed: bool = False
    hidden: bool = False


@dataclass
class CrmLeadDetail:
    """The full per-lead snapshot the adapter returns from one
    ``fetch_lead_detail`` call (which may internally fan out to multiple
    HTTP calls for non-Lofty providers)."""

    remote_lead_id: str
    inquiry: CrmInquiry | None = None
    properties: list[CrmProperty] = field(default_factory=list)
    qualification: CrmQualification = field(default_factory=CrmQualification)
    consent: CrmConsent = field(default_factory=CrmConsent)


@dataclass
class CrmTransaction:
    """One deal / transaction — maps to deals.crm_* columns.

    ``source_record_id`` is the CRM's native transaction id; we dedupe
    deals on (crm_provider, crm_transaction_id).
    """

    source_record_id: str
    lead_id: str | None = None
    property_id: str | None = None
    status: str | None = None
    transaction_type: str | None = None  # buyer / seller / dual
    assigned_agent_id: str | None = None
    home_price: float | None = None
    gci: float | None = None
    team_revenue: float | None = None
    agent_revenue: float | None = None
    commission_pct: float | None = None
    offer_date: str | None = None
    expected_close_date: str | None = None
    appointment_date: str | None = None
    agreement_signed_date: str | None = None
    contract_date: str | None = None
    appraisal_date: str | None = None
    home_inspection_date: str | None = None
    escrow_date: str | None = None
    expiration_date: str | None = None


@dataclass
class CrmNote:
    """Pull-side mirror of a note that lives in the CRM.

    The push-side equivalent is the local ``notes`` row — fields are
    chosen so a Lofty note can round-trip without losing fidelity.
    """

    source_record_id: str
    body: str
    author_name: str | None = None  # CRM operator who wrote it
    source_created_at: str | None = None
    source_updated_at: str | None = None
    deleted: bool = False


# ─── Adapter contract ──────────────────────────────────────────────────


class CrmAdapter(ABC):
    """Provider adapter ABC.

    Concrete subclasses live next to this file (``lofty.py``, ``fub.py``,
    etc.) and are wired into :func:`get_adapter`. Each implementation owns
    its HTTP layer — we don't share auth/retry plumbing across providers
    because each CRM has its own quirks (header style, rate limits,
    pagination shape).
    """

    #: Provider slug — matches the ``crm_provider`` enum.
    provider: str

    def __init__(self, env_values: dict[str, str], config: dict[str, Any] | None = None) -> None:
        self.env_values = env_values
        self.config = config or {}

    @abstractmethod
    def fetch_lead_detail(self, remote_lead_id: str) -> CrmLeadDetail:
        """Hydrate inquiry + properties + qualification + consent for one
        lead. May fan out to multiple HTTP calls under the hood.

        Returning a ``CrmLeadDetail`` with empty inquiry / no properties /
        all-default qualification is valid — means the CRM has no data
        beyond the basic contact record.
        """

    @abstractmethod
    def fetch_transactions(self, remote_lead_id: str) -> list[CrmTransaction]:
        """Return every transaction / deal attached to this lead.

        Empty list is valid (most contacts don't have a deal yet)."""

    @abstractmethod
    def fetch_notes(
        self,
        remote_lead_id: str,
        *,
        since: str | None = None,
    ) -> list[CrmNote]:
        """Return notes written in the CRM since ``since`` (ISO-8601). If
        ``since`` is None, return everything the CRM exposes. The cron
        passes the local ``crm_synced_at`` watermark so we only fetch
        deltas after the first run."""

    def supports_writes(self) -> bool:
        """Some providers (BoldTrail) are read-only until partner access
        lands. The base contract assumes write support; override to
        False where applicable."""
        return True


# ─── Factory ───────────────────────────────────────────────────────────


_REGISTRY: dict[str, type[CrmAdapter]] = {}


def register_adapter(provider: str, adapter_cls: type[CrmAdapter]) -> None:
    """Register a concrete adapter. Called from each adapter module at
    import time so :func:`get_adapter` can resolve it without a circular
    import dance."""
    _REGISTRY[provider] = adapter_cls


def get_adapter(
    provider: str,
    env_values: dict[str, str],
    config: dict[str, Any] | None = None,
) -> CrmAdapter:
    """Return a configured adapter for ``provider``.

    Raises :class:`KeyError` if no adapter is registered — caller should
    catch and surface "CRM not supported yet" rather than crashing the
    cron. The registry is populated lazily: importing this module alone
    gives you the ABC but no providers; import the provider modules (or
    use a top-level import of :mod:`elevate_cli.crm_adapters.all`) to
    populate the registry.
    """
    if provider not in _REGISTRY:
        # Lazy import so we don't drag every adapter into memory when
        # the caller only needs one provider.
        from elevate_cli.crm_adapters import all as _all  # noqa: F401

    if provider not in _REGISTRY:
        raise KeyError(
            f"No CRM adapter registered for provider={provider!r}. "
            f"Known providers: {sorted(_REGISTRY)}"
        )
    return _REGISTRY[provider](env_values=env_values, config=config)


def registered_providers() -> Iterable[str]:
    """Return the providers currently registered. Useful for the
    onboarding UI's "supported CRM" dropdown."""
    # Trigger lazy load so the answer is accurate.
    from elevate_cli.crm_adapters import all as _all  # noqa: F401

    return tuple(sorted(_REGISTRY))
