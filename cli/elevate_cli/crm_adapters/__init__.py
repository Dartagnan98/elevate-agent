"""CRM adapter package — plug-and-play layer between Elevate and any
supported CRM (Lofty, Follow Up Boss, Sierra, Brivity, BoldTrail).

The cron sync function picks an adapter by ``crm_provider``, calls the
adapter's ``fetch_lead_detail`` / ``fetch_transactions`` / ``fetch_notes``
methods, and writes the normalized dataclasses to operational.db. No
provider-specific code lives outside this package.

See :mod:`elevate_cli.crm_adapters.base` for the contract.
"""

from elevate_cli.crm_adapters.base import (
    CrmAdapter,
    CrmConsent,
    CrmInquiry,
    CrmLeadDetail,
    CrmNote,
    CrmProperty,
    CrmQualification,
    CrmTransaction,
    get_adapter,
)

__all__ = [
    "CrmAdapter",
    "CrmConsent",
    "CrmInquiry",
    "CrmLeadDetail",
    "CrmNote",
    "CrmProperty",
    "CrmQualification",
    "CrmTransaction",
    "get_adapter",
]
