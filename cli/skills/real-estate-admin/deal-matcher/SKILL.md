---
name: deal-matcher
description: Safely match documents, conversations, drafts, and portal records to the correct Elevate deal using MLS number, property address, phone, email, contact ID, and deal ID.
metadata:
  elevate:
    tags: [real-estate, admin, matching, safety]
---

# Deal Matcher

Use this before writing external material to a deal unless the run context already proves the deal ID.

Match strongest identifiers first:

1. Exact deal ID.
2. MLS number.
3. Normalized property address.
4. Contact ID from CRM/source-of-truth.
5. Email and phone verifiers.

If identifiers conflict, stop and ask for human review. If multiple deals match, return the candidates and the conflicting identifiers. Never attach documents or update checklist cells on a fuzzy match.

## Matching Policy

Treat `deal_id` as proven only when it comes from injected run context, an Admin UI action, or an artifact already attached to that deal. Treat every external source as untrusted until matched.

Strong identifiers:

- MLS number.
- Exact normalized civic address.
- CRM/contact ID.
- Email address.
- Phone number.
- Portal transaction ID or envelope ID already stored on the deal.

Weak identifiers:

- First name only.
- Street name without number.
- Listing nickname.
- Email subject with no attachment body.
- A guessed folder name.

## Result Shape

Return a compact match decision to the caller:

```json
{
  "status": "matched|ambiguous|conflict|not_found",
  "deal_id": "",
  "confidence": 0.0,
  "matched_on": ["mls", "address"],
  "conflicts": [],
  "candidates": []
}
```

Only `matched` may proceed to writes. `ambiguous`, `conflict`, and `not_found` must become a human prompt.
