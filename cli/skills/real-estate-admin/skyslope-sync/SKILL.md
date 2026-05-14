---
name: skyslope-sync
description: Sync configured compliance-platform transaction status and documents to an Elevate deal file. Works with SkySlope or another brokerage compliance portal via browser workflow.
metadata:
  elevate:
    tags: [real-estate, compliance, documents]
    runtime:
      result_writer: admin-result-writer
---

# Compliance Platform Sync

Use after MLC/listing paperwork begins and during closeout.

Open the configured compliance platform playbook, match the deal, pull transaction status and available documents, and write missing-document tasks back to the deal. This skill is provider-neutral; SkySlope is one possible configured portal.

Do not guess document status. If portal access, transaction identity, or document names conflict, ask for human review.

## Provider-Neutral Scope

This skill syncs the configured brokerage compliance portal. The portal may be SkySlope or another provider set during onboarding. Treat the portal name, login URL, and checklist labels as tenant configuration.

## Flow

1. Match the deal by portal transaction ID, MLS, address, or contact verifiers.
2. Open the configured compliance portal through Browser Use or provider connector.
3. Pull transaction status, checklist status, required/missing documents, comments, and available files.
4. Attach downloaded files to the deal when the match is proven.
5. Write missing-document tasks back to SQLite.
6. Close through `admin-result-writer`.

## Rules

- Do not mark a compliance checklist complete unless the portal says complete or the file/status evidence is attached.
- If portal labels differ from the province package, keep both labels in the artifact/task.
- MFA/login needed is `waiting_human`, not a silent failure.

## Output Contract

```json
{
  "workflow": "compliance-sync",
  "status": "done|partial|waiting_human|failed",
  "deal_id": "",
  "provider": "",
  "transaction_id": "",
  "documents_attached": [],
  "missing_document_tasks": [],
  "portal_status": "",
  "risks": []
}
```
