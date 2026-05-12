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
