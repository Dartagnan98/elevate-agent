---
name: local-ultrareview
category: agent-ops
description: Local multi-stage code review — parallel review, synthesis, and implementation planning, then offer to apply fixes.
---

# local-ultrareview

A local replication of /ultrareview that runs three parallel review passes, then synthesis, then an implementation plan. The invoking agent then offers to apply the fixes.

The three review passes run as isolated parallel work using `delegate_task` (worker-agents), one per scope. Synthesis and the implementation plan run as single follow-on delegated tasks. The main agent applies the fixes itself.

**Trigger phrases:**
- "run local ultrareview"
- "/local-ultrareview"
- "/local-ultrareview <PR#>"

---

## Setup

Before running, determine the session folder name. Put it under the agent's workdir so the docs persist with you:

```bash
PR_NUM="${1:-branch}"  # PR number if passed, else "branch"
DATE=$(date +%Y-%m-%d)
SESSION_DIR="reviews/${PR_NUM}-${DATE}"
mkdir -p "$SESSION_DIR"
```

Get the diff:
```bash
# If PR number provided:
gh pr diff $PR_NUM > "$SESSION_DIR/diff.txt"

# If no PR number (current branch):
git diff main > "$SESSION_DIR/diff.txt"
```

If the diff is empty, tell the user there is nothing to review and stop.

---

## Stage 1: Three Parallel Review Passes

Spawn all three simultaneously using `delegate_task` (one isolated worker-agent per scope). Each delegated task writes its review to a file in `$SESSION_DIR`.

Do NOT wait for one to finish before starting the others — issue all three `delegate_task` calls in the same turn so they run in parallel.

### Pass 1: Correctness Review

**Output file:** `$SESSION_DIR/review-correctness.md`

**Task prompt:**
```
You are a senior engineer conducting a focused code review. Your scope: correctness, bugs, and edge cases only.

Read the diff at: $SESSION_DIR/diff.txt

Review every changed file for:
- Logic errors and off-by-one mistakes
- Unhandled edge cases and null/undefined paths
- Incorrect assumptions about input or state
- Race conditions or async handling issues
- Functions that can fail silently
- Tests that are missing or inadequate

For each issue, write:

## [Short Issue Title]
**File:** path/to/file:line
**Severity:** critical | warning | suggestion
**What is wrong:** [specific description]
**Why it matters:** [what breaks or what risk]
**What needs to change:** [specific enough to act on]

If you find no issues in a section, say so explicitly.
Write your full review to $SESSION_DIR/review-correctness.md now.
```

### Pass 2: Security & Performance Review

**Output file:** `$SESSION_DIR/review-security-perf.md`

**Task prompt:**
```
You are a senior security and performance engineer conducting a focused code review. Your scope: security vulnerabilities and performance problems only.

Read the diff at: $SESSION_DIR/diff.txt

Review for:
- Injection vulnerabilities (SQL, command, XSS, etc.)
- Unvalidated or unsanitized user input
- Authentication and authorization issues
- Sensitive data exposure or insecure storage
- N+1 queries or unnecessary database calls
- Memory leaks or unbounded data structures
- Expensive operations in hot paths
- Missing rate limiting or resource guards

For each issue, write:

## [Short Issue Title]
**File:** path/to/file:line
**Severity:** critical | warning | suggestion
**Type:** security | performance
**What is wrong:** [specific description]
**Attack vector / Impact:** [who can exploit it or what degrades]
**What needs to change:** [specific enough to act on]

If you find no issues in a section, say so explicitly.
Write your full review to $SESSION_DIR/review-security-perf.md now.
```

### Pass 3: Architecture Review

**Output file:** `$SESSION_DIR/review-architecture.md`

**Task prompt:**
```
You are a principal engineer conducting a focused code review. Your scope: architecture, design patterns, and codebase fit only.

Read the diff at: $SESSION_DIR/diff.txt
Also read surrounding files referenced in the diff to understand existing patterns.

Review for:
- Inconsistency with existing codebase patterns and conventions
- Unnecessary complexity or over-engineering
- Violation of separation of concerns
- Poor abstractions or leaky interfaces
- Duplicated logic that should be shared
- Coupling that will make future changes harder
- Missing or incorrect error boundaries
- API design that is hard to use correctly

For each issue, write:

## [Short Issue Title]
**File:** path/to/file:line
**Severity:** critical | warning | suggestion
**What is wrong:** [specific description]
**Why it matters:** [maintenance cost, future risk]
**What needs to change:** [specific enough to act on]

If you find no issues in a section, say so explicitly.
Write your full review to $SESSION_DIR/review-architecture.md now.
```

Wait until all three files exist before proceeding:
- `$SESSION_DIR/review-correctness.md`
- `$SESSION_DIR/review-security-perf.md`
- `$SESSION_DIR/review-architecture.md`

---

## Stage 2: Synthesis Pass

Run one `delegate_task` to read all three reviews and produce a unified synthesis.

**Output file:** `$SESSION_DIR/synthesis.md`

**Task prompt:**
```
You are synthesizing the output of three independent code reviews into one clear document.

Read:
- $SESSION_DIR/review-correctness.md
- $SESSION_DIR/review-security-perf.md
- $SESSION_DIR/review-architecture.md

Produce $SESSION_DIR/synthesis.md with this structure:

# Code Review Synthesis — [PR/branch] — [date]

## Overall Assessment
[2-3 sentences: is this safe to merge, what is the biggest concern, overall quality]

## Critical Issues (must fix before merge)
[All critical severity items from any reviewer, deduplicated and ranked by risk]

## Warnings (should fix)
[All warning severity items, deduplicated]

## Suggestions (nice to have)
[All suggestion items, grouped by theme]

## Points of Agreement
[Issues flagged by more than one reviewer — these are highest confidence]

## What Looks Good
[Areas where all reviewers found nothing — helps the author know what is solid]

Deduplicate: if multiple reviewers flagged the same issue, merge them into one entry noting all reviewers agreed.
Write $SESSION_DIR/synthesis.md now.
```

Wait for `$SESSION_DIR/synthesis.md` to exist.

---

## Stage 3: Implementation Plan Pass

Run one `delegate_task` to read the synthesis and produce a concrete implementation plan.

**Output file:** `$SESSION_DIR/implementation-plan.md`

**Task prompt:**
```
You are a senior engineer writing a concrete implementation plan to fix every issue identified in a code review.

Read:
- $SESSION_DIR/synthesis.md (the synthesized review)
- $SESSION_DIR/diff.txt (the original changes)
- The actual source files referenced in the review (use Read tool)

Produce $SESSION_DIR/implementation-plan.md with this structure:

# Implementation Plan — [PR/branch] — [date]

## Summary
[What needs to be fixed and the estimated scope of work]

## Fix Plan

For each issue in the synthesis (critical first, then warnings, then suggestions):

### Fix [N]: [Issue Title]
**File(s):** path/to/file:line
**Priority:** critical | warning | suggestion
**Approach:** [exactly what to change and why this approach is correct]
**Code change:**
[Write the exact code that should replace the problematic code. Be precise — actual variable names, actual logic, not pseudocode.]
**Test:** [what to verify after the fix]

## Order of Operations
[If fixes depend on each other, specify the order to apply them]

## Risk
[Any fixes that could introduce new issues and what to watch for]

Write the full implementation plan to $SESSION_DIR/implementation-plan.md now.
```

Wait for `$SESSION_DIR/implementation-plan.md` to exist.

---

## Stage 4: Main Agent Presents and Executes

Once the implementation plan exists, read it and present to the user:

```
local-ultrareview complete.

Session folder: $SESSION_DIR/
- review-correctness.md
- review-security-perf.md
- review-architecture.md
- synthesis.md
- implementation-plan.md

[X] critical issues
[X] warnings
[X] suggestions

Summary: [paste the ## Summary section from implementation-plan.md]

Do you want me to apply the fixes now?
```

### If user says yes:

Work through the implementation plan fix by fix. For each fix:
1. Read the current file
2. Apply the change exactly as specified in the plan
3. Briefly confirm what was changed

After all fixes are applied, ask:

```
All fixes applied. What would you like to do next?

1. Commit the changes
2. Push and re-open the PR
3. Merge
4. Review the changes first (git diff)
```

Execute whichever the user chooses:
- **Commit:** `git add -A && git commit -m "fix: apply code review fixes from local-ultrareview"`
- **Push/re-PR:** `git push` then `gh pr create` or `gh pr push` as appropriate
- **Merge:** `gh pr merge` (confirm with user before executing)
- **Diff:** run `git diff` and show output

### If user says no:

```
No problem. All review docs are in $SESSION_DIR/ when you are ready.
```

---

## Notes

- The three Stage 1 passes run fully in parallel via `delegate_task` worker-agents. On a typical PR this takes a few minutes.
- The session folder `reviews/<pr>-<date>/` persists in the agent's workdir after the run so you can reference it later or hand it to a teammate (share via native Comms / `agent_handoff` if another agent needs it).
- If a PR number is passed, `gh` CLI must be installed and authenticated.
- The main agent handles all git operations and applies the fixes. The delegated review/synthesis/plan tasks only read and write files.
- If you want this review to run on a schedule (e.g. on every PR), wire it up with the `cron` tool rather than firing it manually.
