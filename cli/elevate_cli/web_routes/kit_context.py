"""Shared property and representation facts for document preparation."""
import re
from decimal import Decimal


def retained_commission(toggles):
    """Subtract matching, explicit commission tiers; never guess custom terms."""
    if 'listingBrokerageRetained' in toggles:
        return str(toggles['listingBrokerageRetained'] or '')
    pattern = r'(?:[^:%]+:\s*)?(\d+(?:\.\d+)?)%\s+on the first\s+\$([\d,]+(?:\.\d+)?)\s+and\s+(\d+(?:\.\d+)?)%\s+on the balance(?:,?\s+(plus GST))?\.?'
    total = re.fullmatch(pattern, str(toggles.get('listingCommission') or '').strip(), re.I)
    coop = re.fullmatch(pattern, str(toggles.get('buyerAgencyComp') or '').strip(), re.I)
    if not total or not coop:
        return ''
    a, b = total.groups(), coop.groups()
    threshold = Decimal(a[1].replace(',', ''))
    if threshold != Decimal(b[1].replace(',', '')) or bool(a[3]) != bool(b[3]):
        return ''
    first, balance = Decimal(a[0]) - Decimal(b[0]), Decimal(a[2]) - Decimal(b[2])
    if min(first, balance) < 0:
        return ''
    number = lambda value: format(value.normalize(), 'f')
    return f"{number(first)}% on the first ${threshold:,f} and {number(balance)}% on the balance" + (', plus GST.' if a[3] else '.')


def seller_mailing_parts(toggles):
    """Use a supplied seller mailing address, never assume the listed property."""
    sellers = toggles.get('onboardingSellers') or []
    first = sellers[0] if sellers and isinstance(sellers[0], dict) else {}
    value = toggles.get('sellerMailingAddress', toggles.get('seller_mailing_address', first.get('mailingAddress', first.get('address', ''))))
    if isinstance(value, dict):
        parts = property_parts(value.get('street') or value.get('line1') or '', {
            'unitNumber': value.get('unit'), 'propertyCity': value.get('city'),
            'propertyProvince': value.get('province'), 'postalCode': value.get('postalCode')}, {})
    else:
        parts = property_parts(str(value or ''), {}, {})
    return dict(zip(('sellerUnit','sellerStreetNum','sellerStreet','sellerCity','sellerState','sellerZip'),
                    (parts[k] for k in ('p_unit','p_streetnum','p_street','p_city','p_state','p_zip'))))


def listing_terms(toggles, facts):
    # Preserve deliberate clears and legacy contract-date fields. New intake
    # keeps the contract start separate from the planned MLS go-live date.
    return {
        "listPrice": toggles.get("listPrice", facts.get("listPrice", "")),
        "listDate": toggles.get("contractEffectiveDate", toggles.get("listingDate", "")),
    }


def agents(toggles, preferences=None):
    preferences = preferences or {}
    value = toggles.get("designatedAgency", preferences.get("designatedAgency", "Skyleigh McCallum PREC*"))
    names = [p.strip() for p in re.split(r"\s*&\s*|;|\n", str(value or "")) if p.strip()]
    second = str(toggles.get("designatedAgency2", preferences.get("designatedAgency2", "")) or "").strip()
    return (names[0] if names else ""), (second or " & ".join(names[1:]))


def property_parts(address, toggles, facts):
    parts = [p.strip() for p in str(address or "").split(",")]
    street = parts[0] if parts else ""
    match = re.match(r"^(?:(?:#|Unit\s+)?([\w]+)\s*-\s*)?(\d+[A-Za-z]?)\s+(.+)$", street, re.I)
    unit, number, street_name = match.groups() if match else ("", "", street)
    city = str(toggles.get("propertyCity") or toggles.get("city") or toggles.get("municipality") or facts.get("propertyCity") or (parts[1] if len(parts)>1 else ""))
    region = parts[2].split(" ", 1) if len(parts)>2 else []
    return {
        "p_unit": toggles.get("unitNumber") or unit or "",
        "p_streetnum": number or "", "p_street": street_name,
        "p_city": city,
        "p_state": toggles.get("propertyProvince") or facts.get("province") or (region[0] if region else ""),
        "p_zip": toggles.get("postalCode") or toggles.get("postal") or (region[1] if len(region)>1 else ""),
    }


def clock_time(value):
    match = re.fullmatch(r"(\d{2}):(\d{2})", str(value or ""))
    if not match:
        return value or ""
    hour, minute = map(int, match.groups())
    return f"{hour % 12 or 12}:{minute:02d} {'AM' if hour < 12 else 'PM'}"
