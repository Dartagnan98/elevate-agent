# Elevate AI Action Harness Implementation Plan

> **For Elevate:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Turn Elevate from a chat/tool assistant into a secure, resumable operating harness that can control approved browser sessions, ingest source material, build rules packs, run transaction/admin workflows, and act only through explicit authority gates.

**Architecture:** Add a durable Action Harness layer around browser control, source ingestion, jobs, approvals, and audit logs. Browser work feeds a source-ingestion pipeline; source material feeds rules-pack builders; rules packs drive transaction heartbeat jobs; all real-world actions flow through an authority/approval model.

**Tech Stack:** Python/FastAPI backend in `elevate_cli/web_server.py`, SQLite state in existing `~/.elevate/state.db`, React/TypeScript web UI in `web/src`, Chrome DevTools Protocol and later Chrome extension bridge, cron jobs in `cron/`, local knowledge/RAG via `fact_store` and existing memory/document systems.

---

## Product North Star

Elevate should operate like this:

```text
observe → extract → reason → plan → ask approval → act → verify → log → resume
```

For Skyleigh first:

```text
Controlled Browser → eXp Agent Centre province extraction → rules packs → Admin Hub → Transaction Heartbeat → calendar/deadline/missing-doc workflows
```

For the broader product:

```text
Any logged-in portal → source ingestion → local RAG/graph → workflow/rules engine → human-approved actions
```

---

## Non-Negotiable Safety Rules

1. Never store plaintext passwords in chat, logs, `.env`, rules packs, or page snapshots.
2. Never extract password fields, cookies, access tokens, ID tokens, refresh tokens, session storage, or local storage secrets.
3. Browser bridge defaults to read-only.
4. Action mode must be domain-allowlisted.
5. Destructive or external actions require explicit approval:
   - send message/email
   - submit form
   - sign document
   - upload compliance document
   - delete file
   - change listing data
   - click payment/funds instructions
6. Every harness run has a durable run ID, checkpoints, source list, actions list, errors list, and resume cursor.
7. Every generated rules pack keeps source citations.
8. If a source page cannot be captured, mark it as blocked, do not guess.

---

## Phase Map

### Phase 1: Harness Core + Audit Ledger

Build the durable state and job model.

**Outcome:** Elevate can start, track, pause, resume, and audit long-running harness jobs.

## Phase 2 — Lightweight Browser Worker v1

**Direction update:** Elevate's browser harness should use [`browser-use/browser-harness`](https://github.com/browser-use/browser-harness) as the browser-control layer, not reinvent that layer inside Elevate.

Browser-use/browser-harness provides the thin editable CDP runtime:

- direct connection to the user's real browser through CDP,
- `browser-harness -c '...'` execution model,
- daemon/IPC session handling,
- screenshot-first interaction helpers,
- coordinate clicks that work through iframes/shadow DOM,
- agent-editable `agent-workspace/agent_helpers.py`,
- opt-in domain skills under `agent-workspace/domain-skills/`,
- local Chrome and Browser Use Cloud support.

Elevate should sit **above** that runtime and own the real-estate operating layer:

- approvals,
- domain/account allowlists,
- redaction,
- source snapshots,
- durable jobs/checkpoints,
- seller/buyer transaction state,
- Hub UI,
- audit logs,
- Transaction Heartbeat.

The boundary:

```text
browser-use/browser-harness = direct browser control
Elevate harness = supervised real-estate operations, memory, approvals, state, snapshots
```

Layer order:

1. browser-use/browser-harness CDP connection to real Chrome.
2. Elevate adapter/wrapper for approved browser commands.
3. Elevate redaction + source snapshot ingestion.
4. Elevate job/checkpoint store.
5. Elevate Admin Hub / Transaction Heartbeat.
6. Later: Chrome extension bridge as product UI over the same harness protocol.

## Phase 2a — Connection Modes

Build a layered browser worker, starting with CDP attach to a controlled Chrome session, then adding Playwright launch mode, Browser Use exploration mode, stealth fallback, cloud fallback, and finally the Chrome extension bridge.

**Outcome:** Elevate can inspect approved pages, extract text/links, navigate, crawl allowlisted links, download allowed docs, and resume interrupted browser jobs without touching credentials.

**Browser stack order:**
1. CDP attach mode — use the Chrome window the user explicitly opened.
2. Playwright worker mode — launch a dedicated local browser for repeatable extraction/crawls.
3. Browser Use mode — exploratory page reasoning when deterministic scripts are not enough.
4. Camofox/stealth fallback — only if a portal blocks normal automation.
5. Browserbase/Browserless fallback — later for production scale or non-local users.
6. Chrome extension bridge — polished product flow: “Allow Elevate to inspect this tab.”

### Phase 3: Source Ingestion Pipeline

Normalize browser pages, PDFs, Google Docs/Drive links, and downloaded material into source snapshots.

**Outcome:** Every source becomes a cited, hashable, searchable artifact.

### Phase 4: Rules Pack Builder

Convert source material into jurisdiction/brokerage/software rules packs.

**Outcome:** BC/eXp first, then AB through YK, then other regions/brokerages.

### Phase 5: Transaction Heartbeat Engine

Use rules packs to inspect active transactions and generate/repair checklists, deadlines, reminders, blockers, and AI/human action queues.

**Outcome:** Admin Hub becomes a transaction coordinator.

### Phase 6: Approval + Action Authority

Centralize permissioning for AI actions.

**Outcome:** Elevate can safely draft, prepare, and act only inside approved bounds.

### Phase 7: Hub UI

Add operator controls for browser sessions, harness jobs, source ingestion, rules packs, approvals, and Admin Hub transaction health.

**Outcome:** User can supervise the AI harness visually.

### Phase 8: Chrome Extension Bridge

Move from debug-only Chrome sessions to a first-class extension with tab-level approval.

**Outcome:** “Allow Elevate to inspect/control this tab” becomes a product feature.

---

## Data Model

Add these tables to existing `~/.elevate/state.db`. Do not create another database unless profiling proves it necessary.

### `harness_runs`

```sql
CREATE TABLE IF NOT EXISTS harness_runs (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  run_type TEXT NOT NULL,
  status TEXT NOT NULL,
  account_context TEXT,
  jurisdiction TEXT,
  mode TEXT NOT NULL DEFAULT 'read_only',
  allowed_domains_json TEXT NOT NULL DEFAULT '[]',
  input_json TEXT NOT NULL DEFAULT '{}',
  progress_json TEXT NOT NULL DEFAULT '{}',
  resume_cursor_json TEXT NOT NULL DEFAULT '{}',
  error_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  completed_at TEXT
);
```

### `harness_events`

```sql
CREATE TABLE IF NOT EXISTS harness_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id TEXT NOT NULL,
  event_type TEXT NOT NULL,
  message TEXT NOT NULL,
  payload_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  FOREIGN KEY(run_id) REFERENCES harness_runs(id)
);
```

### `source_snapshots`

```sql
CREATE TABLE IF NOT EXISTS source_snapshots (
  id TEXT PRIMARY KEY,
  run_id TEXT,
  source_type TEXT NOT NULL,
  source_uri TEXT NOT NULL,
  title TEXT,
  account_context TEXT,
  jurisdiction TEXT,
  raw_text_path TEXT,
  markdown_path TEXT,
  json_path TEXT,
  file_path TEXT,
  content_hash TEXT NOT NULL,
  trust_level TEXT NOT NULL DEFAULT 'source',
  captured_at TEXT NOT NULL,
  metadata_json TEXT NOT NULL DEFAULT '{}',
  FOREIGN KEY(run_id) REFERENCES harness_runs(id)
);
```

### `approval_requests`

```sql
CREATE TABLE IF NOT EXISTS approval_requests (
  id TEXT PRIMARY KEY,
  run_id TEXT,
  action_type TEXT NOT NULL,
  risk_level TEXT NOT NULL,
  title TEXT NOT NULL,
  summary TEXT NOT NULL,
  proposed_payload_json TEXT NOT NULL DEFAULT '{}',
  status TEXT NOT NULL DEFAULT 'pending',
  decision_by TEXT,
  decision_at TEXT,
  created_at TEXT NOT NULL,
  FOREIGN KEY(run_id) REFERENCES harness_runs(id)
);
```

### `rules_packs`

```sql
CREATE TABLE IF NOT EXISTS rules_packs (
  id TEXT PRIMARY KEY,
  country TEXT NOT NULL,
  province_state TEXT NOT NULL,
  brokerage TEXT,
  board TEXT,
  side TEXT NOT NULL,
  version TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'draft',
  yaml_path TEXT NOT NULL,
  source_snapshot_ids_json TEXT NOT NULL DEFAULT '[]',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
```

---

## File Layout

### Backend modules

Create:

```text
elevate_cli/harness/__init__.py
elevate_cli/harness/models.py
elevate_cli/harness/store.py
elevate_cli/harness/redaction.py
elevate_cli/harness/browser_cdp.py
elevate_cli/harness/ingestion.py
elevate_cli/harness/jobs.py
elevate_cli/harness/approvals.py
elevate_cli/harness/rules_pack.py
elevate_cli/harness/transaction_heartbeat.py
elevate_cli/harness/schemas.py
```

Modify:

```text
elevate_cli/web_server.py
cron/jobs.py
cron/scheduler.py
model_tools.py          # only if exposing harness tools to agents
```

### Frontend files

Create:

```text
web/src/pages/HarnessPage.tsx
web/src/pages/HarnessJobDetailPage.tsx
web/src/pages/BrowserSessionsPage.tsx
web/src/pages/SourceIngestionPage.tsx
web/src/pages/RulesPacksPage.tsx
web/src/pages/ApprovalsPage.tsx
web/src/lib/harnessApi.ts
web/src/types/harness.ts
```

Modify:

```text
web/src/App.tsx
web/src/components/SidebarFooter.tsx or sidebar nav component
```

### Tests

Create:

```text
tests/elevate_cli/harness/test_store.py
tests/elevate_cli/harness/test_redaction.py
tests/elevate_cli/harness/test_browser_cdp.py
tests/elevate_cli/harness/test_ingestion.py
tests/elevate_cli/harness/test_rules_pack.py
tests/elevate_cli/harness/test_approvals.py
tests/elevate_cli/test_harness_endpoints.py
```

### Local artifact paths

Use:

```text
~/.elevate/harness/runs/<run_id>/
~/.elevate/harness/sources/<snapshot_id>/
~/.elevate/knowledge/<client>/admin/...
~/.elevate/rules-packs/<country>/<province>/<brokerage>/
```

For Skyleigh eXp:

```text
~/.elevate/knowledge/skyleigh/admin/exp-agent-centre/all-provinces-raw/
~/.elevate/rules-packs/canada/bc/exp/
~/.elevate/rules-packs/canada/ab/exp/
```

---

## Phase 1 Tasks: Harness Core + Audit Ledger

### Task 1: Add harness package skeleton

**Objective:** Create empty modules so later tasks have stable imports.

**Files:**
- Create: `elevate_cli/harness/__init__.py`
- Create: `elevate_cli/harness/models.py`
- Create: `elevate_cli/harness/store.py`
- Create: `elevate_cli/harness/redaction.py`

**Verification:**

```bash
cd /Users/dartagnanpatricio/elevate/cli
.venv/bin/python -m pytest tests/elevate_cli/data/test_data_module_isolation.py -q
```

Expected: existing test passes.

---

### Task 2: Define harness dataclasses

**Objective:** Add typed models for runs, events, source snapshots, approval requests, and rules packs.

**File:** `elevate_cli/harness/models.py`

**Implementation:**

```python
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

RunStatus = Literal['pending', 'running', 'paused', 'blocked', 'failed', 'completed', 'cancelled']
HarnessMode = Literal['read_only', 'read_download', 'controlled_navigation', 'action']


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:16]}"


@dataclass(slots=True)
class HarnessRun:
    id: str
    name: str
    run_type: str
    status: RunStatus
    account_context: str | None = None
    jurisdiction: str | None = None
    mode: HarnessMode = 'read_only'
    allowed_domains: list[str] = field(default_factory=list)
    input: dict[str, Any] = field(default_factory=dict)
    progress: dict[str, Any] = field(default_factory=dict)
    resume_cursor: dict[str, Any] = field(default_factory=dict)
    error: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)
    completed_at: str | None = None


@dataclass(slots=True)
class HarnessEvent:
    run_id: str
    event_type: str
    message: str
    payload: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now_iso)


@dataclass(slots=True)
class SourceSnapshot:
    id: str
    source_type: str
    source_uri: str
    content_hash: str
    captured_at: str
    run_id: str | None = None
    title: str | None = None
    account_context: str | None = None
    jurisdiction: str | None = None
    raw_text_path: str | None = None
    markdown_path: str | None = None
    json_path: str | None = None
    file_path: str | None = None
    trust_level: str = 'source'
    metadata: dict[str, Any] = field(default_factory=dict)
```

---

### Task 3: Write redaction tests

**Objective:** Ensure tokens, cookies, local/session storage, and password fields are removed before storage.

**File:** `tests/elevate_cli/harness/test_redaction.py`

**Tests:**

```python
from elevate_cli.harness.redaction import redact_sensitive_text, sanitize_browser_snapshot


def test_redacts_bearer_tokens():
    text = 'Authorization: Bearer abc.def.ghi'
    assert 'abc.def.ghi' not in redact_sensitive_text(text)
    assert '[REDACTED_BEARER_TOKEN]' in redact_sensitive_text(text)


def test_redacts_okta_token_storage():
    snapshot = {
        'url': 'https://example.com',
        'localStorage': {'okta-token-storage': '{"accessToken":"secret"}'},
        'sessionStorage': {'safe': 'still secret-adjacent'},
        'text': 'hello',
    }
    cleaned = sanitize_browser_snapshot(snapshot)
    assert 'localStorage' not in cleaned
    assert 'sessionStorage' not in cleaned
    assert cleaned['text'] == 'hello'


def test_redacts_password_input_values():
    snapshot = {'fields': [{'type': 'password', 'name': 'pw', 'value': 'super-secret'}]}
    cleaned = sanitize_browser_snapshot(snapshot)
    assert cleaned['fields'][0]['value'] == '[REDACTED_PASSWORD_FIELD]'
```

---

### Task 4: Implement redaction utilities

**Objective:** Centralize safety filters.

**File:** `elevate_cli/harness/redaction.py`

**Implementation:**

```python
from __future__ import annotations

import copy
import re
from typing import Any

BEARER_RE = re.compile(r'Bearer\s+[A-Za-z0-9._\-]+')
JWT_RE = re.compile(r'eyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+')
COOKIE_RE = re.compile(r'(?i)(cookie|set-cookie)\s*[:=]\s*[^\n\r]+')
PASSWORD_RE = re.compile(r'(?i)(password\s*[=:]\s*)[^\n\r&]+')

SENSITIVE_KEYS = {
    'cookie', 'cookies', 'authorization', 'access_token', 'refresh_token',
    'id_token', 'idToken', 'accessToken', 'refreshToken', 'okta-token-storage',
    'localStorage', 'sessionStorage', 'password', 'passwd', 'secret', 'token',
}


def redact_sensitive_text(text: str) -> str:
    text = BEARER_RE.sub('Bearer [REDACTED_BEARER_TOKEN]', text)
    text = JWT_RE.sub('[REDACTED_JWT]', text)
    text = COOKIE_RE.sub(lambda m: f"{m.group(1)}: [REDACTED_COOKIE]", text)
    text = PASSWORD_RE.sub(lambda m: f"{m.group(1)}[REDACTED_PASSWORD]", text)
    return text


def _is_sensitive_key(key: str) -> bool:
    lowered = key.lower()
    return any(s.lower() in lowered for s in SENSITIVE_KEYS)


def sanitize_browser_snapshot(value: Any) -> Any:
    if isinstance(value, str):
        return redact_sensitive_text(value)
    if isinstance(value, list):
        return [sanitize_browser_snapshot(v) for v in value]
    if isinstance(value, dict):
        cleaned: dict[str, Any] = {}
        for key, child in value.items():
            if key in {'localStorage', 'sessionStorage'}:
                continue
            if _is_sensitive_key(key):
                cleaned[key] = '[REDACTED]'
                continue
            if isinstance(child, dict) and str(child.get('type', '')).lower() == 'password':
                redacted = copy.deepcopy(child)
                redacted['value'] = '[REDACTED_PASSWORD_FIELD]'
                cleaned[key] = redacted
                continue
            if isinstance(child, list) and key == 'fields':
                cleaned[key] = [
                    {**f, 'value': '[REDACTED_PASSWORD_FIELD]'}
                    if isinstance(f, dict) and str(f.get('type', '')).lower() == 'password'
                    else sanitize_browser_snapshot(f)
                    for f in child
                ]
                continue
            cleaned[key] = sanitize_browser_snapshot(child)
        return cleaned
    return value
```

---

### Task 5: Add SQLite store tests

**Objective:** Verify runs/events/snapshots persist to existing state DB-compatible schema.

**File:** `tests/elevate_cli/harness/test_store.py`

**Test shape:**

```python
from pathlib import Path

from elevate_cli.harness.models import HarnessRun, new_id
from elevate_cli.harness.store import HarnessStore


def test_create_and_update_run(tmp_path: Path):
    store = HarnessStore(tmp_path / 'state.db')
    store.migrate()
    run = HarnessRun(id=new_id('run'), name='Test', run_type='browser_extract', status='pending')
    store.upsert_run(run)
    loaded = store.get_run(run.id)
    assert loaded is not None
    assert loaded.name == 'Test'

    store.update_run_status(run.id, 'running')
    assert store.get_run(run.id).status == 'running'


def test_append_event(tmp_path: Path):
    store = HarnessStore(tmp_path / 'state.db')
    store.migrate()
    run = HarnessRun(id='run_123', name='Test', run_type='browser_extract', status='running')
    store.upsert_run(run)
    store.append_event('run_123', 'started', 'Started test run', {'x': 1})
    events = store.list_events('run_123')
    assert len(events) == 1
    assert events[0]['event_type'] == 'started'
```

---

### Task 6: Implement HarnessStore

**Objective:** Durable CRUD and migrations.

**File:** `elevate_cli/harness/store.py`

**Implementation notes:**
- Use `sqlite3` stdlib.
- JSON serialize dataclass list/dict fields.
- Keep migration idempotent.
- Use existing state DB path resolver if available; otherwise accept explicit path for tests.

**Verification:**

```bash
cd /Users/dartagnanpatricio/elevate/cli
.venv/bin/python -m pytest tests/elevate_cli/harness/test_store.py tests/elevate_cli/harness/test_redaction.py -q
```

Expected: all pass.

---

## Phase 2 Tasks: Browser Bridge v1

### Task 7: Add CDP client tests with mocked HTTP endpoints

**Objective:** Test listing tabs and domain filtering without real Chrome.

**File:** `tests/elevate_cli/harness/test_browser_cdp.py`

Test cases:

1. lists tabs from `/json/list`
2. selects tab by URL substring
3. rejects non-allowlisted domain
4. redacts localStorage/sessionStorage from page snapshot

---

### Task 8: Implement BrowserCDPClient

**File:** `elevate_cli/harness/browser_cdp.py`

Required methods:

```python
class BrowserCDPClient:
    def __init__(self, host: str = '127.0.0.1', port: int = 9222, allowed_domains: list[str] | None = None): ...
    def list_tabs(self) -> list[dict]: ...
    def select_tab(self, url_contains: str | None = None) -> dict | None: ...
    async def extract_page(self, tab_id: str) -> dict: ...
    async def navigate(self, tab_id: str, url: str) -> dict: ...
    async def click_text(self, tab_id: str, text: str) -> dict: ...
```

Implementation choices:
- Python `websockets` dependency if already available; otherwise use Node bridge script short-term.
- Long term: Python-native CDP client.
- Always pass page snapshot through `sanitize_browser_snapshot()`.
- Never return localStorage/sessionStorage.

---

### Task 9: Add browser harness endpoints

**File:** `elevate_cli/web_server.py`

Endpoints:

```text
GET  /api/harness/browser/tabs
POST /api/harness/browser/extract
POST /api/harness/browser/navigate
POST /api/harness/browser/click-text
```

Request example:

```json
{
  "run_id": "run_...",
  "tab_id": "...",
  "allowed_domains": ["www.expagentcentre.ca", "exptransactionguide.com"],
  "mode": "read_only"
}
```

Verification:

```bash
.venv/bin/python -m pytest tests/elevate_cli/test_harness_endpoints.py -q
```

---

## Phase 3 Tasks: Source Ingestion Pipeline

### Task 10: Write ingestion tests

**File:** `tests/elevate_cli/harness/test_ingestion.py`

Test:
- saves raw text and markdown
- computes stable hash
- does not duplicate identical source content
- records metadata
- rejects snapshots containing obvious JWT/localStorage strings

---

### Task 11: Implement source snapshot writer

**File:** `elevate_cli/harness/ingestion.py`

Core function:

```python
def ingest_browser_page(
    *,
    store: HarnessStore,
    run_id: str,
    page: dict,
    account_context: str,
    jurisdiction: str | None,
    output_root: Path,
) -> SourceSnapshot:
    ...
```

Output:

```text
~/.elevate/harness/sources/<snapshot_id>/raw.txt
~/.elevate/harness/sources/<snapshot_id>/page.md
~/.elevate/harness/sources/<snapshot_id>/metadata.json
```

---

### Task 12: Add source ingestion endpoints

Endpoints:

```text
GET  /api/harness/sources
GET  /api/harness/sources/{snapshot_id}
POST /api/harness/sources/ingest-browser-page
```

---

## Phase 4 Tasks: Rules Pack Builder

### Task 13: Define rules-pack schema

**File:** `elevate_cli/harness/schemas.py`

YAML output shape:

```yaml
id: canada.bc.exp.buyer_purchase
country: Canada
province_state: British Columbia
brokerage: eXp Realty
board: AOIR
side: buyer_purchase
version: 0.1.0
status: draft
sources:
  - snapshot_id: src_...
    uri: https://exptransactionguide.com/BC
workflow:
  stages:
    - id: intake
      name: Intake / Agency
      required_docs: []
      conditional_docs: []
      calendar_triggers: []
      approval_gates: []
```

---

### Task 14: Write parser tests for known BC source text

**File:** `tests/elevate_cli/harness/test_rules_pack.py`

Use a small fixture with BC transaction checklist lines. Verify it extracts:
- required docs
- conditional docs
- deposit instructions references
- calendar/deadline triggers
- AI/human action classes

---

### Task 15: Implement draft rules-pack generator

**File:** `elevate_cli/harness/rules_pack.py`

Functions:

```python
def build_rules_pack_from_sources(sources: list[SourceSnapshot], side: str, context: dict) -> dict: ...
def write_rules_pack_yaml(pack: dict, root: Path) -> Path: ...
def validate_rules_pack(pack: dict) -> list[str]: ...
```

Important: generator can draft, but status stays `draft` until human review.

---

## Phase 5 Tasks: eXp Province Extraction Job

### Task 16: Add resumable province extraction job

**File:** `elevate_cli/harness/jobs.py`

Input:

```json
{
  "account_context": "Skyleigh/eXp",
  "provinces": ["AB", "BC", "MB", "NB", "NL", "NS", "ON", "PEI", "QC", "SK", "YK"],
  "start_at": "AB",
  "allowed_domains": ["www.expagentcentre.ca", "exptransactionguide.com"],
  "mode": "read_only"
}
```

Behavior:
- create run
- for each province, select province or open canonical URL
- extract province home page
- extract transaction guide page
- crawl same-domain subpages
- capture external doc links as source references
- checkpoint after every page
- resume after interruption

Status output:

```json
{
  "AB": {"status": "completed", "pages": 42, "external_docs": 9},
  "BC": {"status": "completed", "pages": 58, "external_docs": 13},
  "MB": {"status": "blocked", "reason": "Google Drive permission required"}
}
```

---

### Task 17: Add endpoint to start/resume extraction job

Endpoints:

```text
POST /api/harness/jobs/exp-agent-centre-extract
POST /api/harness/jobs/{run_id}/resume
POST /api/harness/jobs/{run_id}/pause
GET  /api/harness/jobs
GET  /api/harness/jobs/{run_id}
GET  /api/harness/jobs/{run_id}/events
```

---

## Phase 6 Tasks: Transaction Heartbeat Engine

### Task 18: Define transaction object

**File:** `elevate_cli/harness/transaction_heartbeat.py`

Schema:

```json
{
  "transaction_id": "...",
  "client": "...",
  "side": "seller_listing|buyer_purchase",
  "jurisdiction": "canada.bc",
  "brokerage": "exp",
  "stage": "accepted_offer",
  "dates": {
    "subject_removal": "...",
    "completion": "...",
    "possession": "...",
    "deposit_due": "..."
  },
  "documents": [],
  "calendar_events": [],
  "blockers": []
}
```

---

### Task 19: Implement checklist repair from rules pack

Given a transaction + rules pack, return:

```json
{
  "missing_required_docs": [],
  "missing_conditional_docs": [],
  "missing_calendar_events": [],
  "overdue_items": [],
  "risk_level": "low|medium|high|critical",
  "ai_can_do": [],
  "ai_can_draft": [],
  "human_must_approve": [],
  "external_blockers": [],
  "next_action": "..."
}
```

---

### Task 20: Add cron job template for Transaction Heartbeat

**Files:**
- Modify: `cron/jobs.py`
- Add skill/job prompt under Skyleigh/admin if needed

Schedule suggestion:

```text
Weekdays 7:15am local time
```

Run output goes to Admin Hub and Telegram summary.

---

## Phase 7 Tasks: Approval + Authority Model

### Task 21: Define action classes

**File:** `elevate_cli/harness/approvals.py`

Classes:

```text
auto_allowed
prepare_only
requires_approval
physical_human_task
external_blocker
never_allowed
```

Risk matrix:

```text
low: internal note, checklist update
medium: calendar event, draft message
high: send message, upload file, submit form
critical: signature, funds instructions, legal/compliance submission
```

---

### Task 22: Add approval endpoints

Endpoints:

```text
GET  /api/harness/approvals
POST /api/harness/approvals/{id}/approve
POST /api/harness/approvals/{id}/reject
POST /api/harness/approvals/{id}/revise
```

---

## Phase 8 Tasks: Hub UI

### Task 23: Add Harness API client

**File:** `web/src/lib/harnessApi.ts`

Functions:

```ts
export async function listHarnessJobs()
export async function getHarnessJob(id: string)
export async function listBrowserTabs()
export async function startExpAgentCentreExtract(payload)
export async function listSourceSnapshots()
export async function listRulesPacks()
export async function listApprovalRequests()
```

---

### Task 24: Add Harness main page

**File:** `web/src/pages/HarnessPage.tsx`

Cards:
- Active Jobs
- Browser Sessions
- Source Ingestion
- Rules Packs
- Approvals Needed
- Recent Errors

---

### Task 25: Add Browser Sessions page

**File:** `web/src/pages/BrowserSessionsPage.tsx`

Show:
- Chrome debug availability
- tabs
- current URL
- mode
- allowed domains
- extract current tab button
- stop/pause button

---

### Task 26: Add Rules Packs page

**File:** `web/src/pages/RulesPacksPage.tsx`

Show:
- country/province/brokerage
- side
- status
- version
- sources
- validation errors
- approve/publish button

---

### Task 27: Add Approvals page

**File:** `web/src/pages/ApprovalsPage.tsx`

Show:
- action type
- risk level
- proposed action
- approve/reject/revise
- linked source/run

---

## Phase 9 Tasks: Chrome Extension Bridge

### Task 28: Create extension scaffold

Path:

```text
browser-extension/elevate-bridge/
```

Files:

```text
manifest.json
src/background.ts
src/content.ts
src/popup.tsx
src/options.tsx
```

Start as read-only.

Manifest permissions:

```json
{
  "permissions": ["activeTab", "scripting", "tabs", "storage", "downloads"],
  "host_permissions": [
    "https://www.expagentcentre.ca/*",
    "https://exptransactionguide.com/*"
  ]
}
```

---

### Task 29: Implement tab extraction message

Flow:

```text
Popup click → content script extracts page text/links → background posts to localhost Elevate endpoint
```

Endpoint:

```text
POST http://127.0.0.1:9119/api/harness/sources/ingest-browser-page
```

---

### Task 30: Add extension pairing token

Do not let any random extension post to localhost.

Add:
- one-time pairing token in Hub
- extension stores token locally
- API validates token

---

## Testing Strategy

### Backend targeted tests

```bash
cd /Users/dartagnanpatricio/elevate/cli
.venv/bin/python -m pytest tests/elevate_cli/harness -q
.venv/bin/python -m pytest tests/elevate_cli/test_harness_endpoints.py -q
```

### Existing dashboard/API tests

```bash
.venv/bin/python -m pytest tests/elevate_cli/test_admin_templates_endpoints.py tests/elevate_cli/test_lifecycle_endpoints.py -q
```

### Full smoke

```bash
.venv/bin/python -m elevate_cli.main hub --host 127.0.0.1 --port 9119 --no-open
curl -s http://127.0.0.1:9119/api/status
curl -s http://127.0.0.1:9119/api/harness/jobs
```

### Browser smoke

1. Launch controlled Chrome:

```bash
open -na "Google Chrome" --args \
  --remote-debugging-port=9222 \
  --user-data-dir="$HOME/.elevate/chrome-skyleigh"
```

2. Login manually.
3. Open `https://www.expagentcentre.ca/`.
4. Run extraction job for one province first:

```json
{"provinces":["AB"],"mode":"read_only"}
```

5. Verify saved artifacts:

```text
~/.elevate/harness/sources/
~/.elevate/knowledge/skyleigh/admin/exp-agent-centre/all-provinces-raw/
~/.elevate/rules-packs/canada/ab/exp/
```

---

## MVP Definition

MVP is done when:

1. Hub can detect controlled Chrome tabs.
2. User can start “Extract eXp Agent Centre provinces.”
3. Job can run AB → YK with checkpoints.
4. Every captured page is saved as source snapshot with hash and citation.
5. Tokens/localStorage/sessionStorage are never saved.
6. Province source material produces draft rules packs.
7. Rules packs can be reviewed/published.
8. Transaction Heartbeat can consume a published BC/eXp rules pack and produce missing docs/deadlines/actions for a sample transaction.
9. Approval queue exists for risky actions.
10. Job can resume after process interruption.

---

## Recommended Execution Order

1. Harness state tables + store.
2. Redaction utilities.
3. Browser CDP tab listing/extraction.
4. Source ingestion writer.
5. Harness endpoints.
6. Simple Hub pages.
7. Resumable eXp province extraction job.
8. Rules-pack draft generator.
9. Transaction Heartbeat core.
10. Approval queue.
11. Chrome extension bridge.

---

## Immediate Skyleigh Extraction Plan

Until full harness is built, use the controlled Chrome CDP bridge, but run it province-by-province with checkpoints.

Order requested:

```text
AB, MB, NB, NL, NS, ON, PEI, QC, SK, YK
```

BC already has partial/local coverage and should be normalized after the rest.

For each province:

1. Select province in Agent Centre.
2. Save province home page.
3. Save Deposit Instructions page.
4. Save Transaction Guide page from `exptransactionguide.com/<PROVINCE>`.
5. Save every same-domain subpage linked from the transaction guide.
6. Save external Google Doc/Drive/PDF links as source references.
7. Mark blocked docs if permissions prevent extraction.
8. Generate `manifest.json` per province.
9. Generate draft rules pack.

Output folder:

```text
/Users/dartagnanpatricio/.elevate/knowledge/skyleigh/admin/exp-agent-centre/all-provinces-raw/<province>/
```

---

## Implementation Risks

### Risk: Browser jobs die mid-crawl

Mitigation: checkpoint after every page and resume from cursor.

### Risk: Sensitive auth tokens leak from browser storage

Mitigation: never capture localStorage/sessionStorage/cookies; redaction tests fail if token-like strings appear.

### Risk: Rules pack hallucination

Mitigation: every rule requires source citation; unknowns are marked `needs_review`.

### Risk: Too much UI before backend works

Mitigation: build backend and endpoint smoke first; UI after.

### Risk: Browser portals change

Mitigation: browser bridge extracts semantic page data, not brittle selectors where possible; keep per-site adapter thin.

---

## Commit Plan

Commit after each vertical slice:

```bash
git add elevate_cli/harness tests/elevate_cli/harness
git commit -m "feat: add harness state and redaction core"

git add elevate_cli/harness/browser_cdp.py elevate_cli/web_server.py tests/elevate_cli/test_harness_endpoints.py
git commit -m "feat: add browser harness endpoints"

git add elevate_cli/harness/ingestion.py tests/elevate_cli/harness/test_ingestion.py
git commit -m "feat: add source ingestion snapshots"

git add elevate_cli/harness/rules_pack.py tests/elevate_cli/harness/test_rules_pack.py
git commit -m "feat: draft transaction rules packs from sources"

git add web/src/pages/HarnessPage.tsx web/src/lib/harnessApi.ts web/src/types/harness.ts
git commit -m "feat: add harness hub UI"
```

---

## Final Target

Elevate becomes a supervised AI operating system:

```text
It can see approved systems.
It can ingest sources.
It can remember with citations.
It can build rules.
It can run heartbeat jobs.
It can draft and prepare work.
It asks before risky actions.
It verifies and logs everything.
It resumes when interrupted.
```

That is the harness.
