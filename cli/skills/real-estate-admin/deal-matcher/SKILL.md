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
