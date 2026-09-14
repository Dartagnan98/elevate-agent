# Elevate Memory Recall-Starvation — Fix Plan (v1.1, narrow + safe)

Status: IMPLEMENTED on branch `memory-critical-tier` (committed, not deployed) — see `elevate-memory-fix-IMPLEMENTATION-HANDOFF.md`. Premium-repo engine change → ships to all customers → supervised + soak.
v1.1 narrows scope per Dartagnan's corrections (2026-06-16). Grounded in
`elevate-memory-architecture-map.md`. Source: `~/elevate/cli` @ `main cccbb60f1`.

## Repo state confirmed (2026-06-16)
- HEAD = `main @ cccbb60f1`. Migrations in `elevate_cli/data/migrations_pg/` run to **0031**. NOTE: the
  shipped desktop release already carries a `0032_chat_session_compaction.sql` that is NOT on main yet,
  and the runner (`data/migrations.py`) HARD-ERRORS on a duplicate version number. So this migration uses
  **0033** (0032 left as a reserved gap) to avoid colliding with that shipped 0032.
- `MemoryManager.prefetch_all(query, *, session_id)` (memory_manager.py:437) takes **no task context**;
  prefetch fires before the tool loop (conversation_loop.py:657 / run_agent.py). Active-skill context is
  NOT plumbed into prefetch or fact writes today → confirms Phase 3b must be deferred.
- The `facts` compat view (`0008_memory_store_compat_views.sql`) has a **FIXED column list** that excludes
  plugin-added columns. The plugin adds metadata columns (durability, reinforced_count, …) directly to
  `memory_facts` via the idempotent `_init_db` ALTER (store.py:540) and accesses them directly. Reads
  elsewhere use `FROM facts` (the view).
- `quality.py` already has `CONVENTIONS` regex (line 78: should/must/never/always/policy/rule/standard),
  `CORRECTION` regex (line 92: actually/instead of/rather than/renamed to/moved to/no longer), and emits a
  `"correction"` signal (line 185). The classifier extends cleanly — no new detector needed.
- `build_embedding_client` (embeddings.py) raises `EmbeddingError` if the API key is missing (line 169) or
  the package is unavailable → any auto-enable MUST catch and degrade silently.

---

## V1 SCOPE (narrow)

**BUILD in v1:**
1. Trust-ratchet fix (decouple trust from ranking outcome, behind a flag).
2. Critical fact fields on `memory_facts` (+ classifier that sets them).
3. Reserved **Must-Follow Rules** recall lane.
4. Conservative classifier + conservative dry-run-first backfill.
5. Fact-45 replay test + the rest of the test matrix.

**DO NOT build in v1 (deferred):**
- Skill-load re-prefetch / Phase 3b (active-skill not plumbed into prefetch; defer).
- Always-injected memory-bank eviction (`tools/memory_tool.py` stays reject-on-over-limit).
- Fleet-wide forced embeddings.
- `admin-result-writer` hard gate (the code-level filing gate — separate effort).

---

## Ordered build

### Phase 0 — break the trust ratchet
- New config knob `plugins.elevate-memory-store.trust_from_ranking_enabled`, **default false**.
- When **false** (the new default), the post-retrieval ranking outcome must NOT mutate trust:
  - `store.py::post_retrieval_maintenance` (~1563): skip the +0.03 verified / −0.01 rejected trust deltas
    (lines ~1577/1583).
  - `store.py::confidence_maintenance` (~1996): skip the +0.05 verified / −0.02 rejected deltas
    (lines ~2012/2018) **and do NOT increment `helpful_count`** on ranking-verified facts.
  - Keep ALL telemetry: `retrieval_count`, `last_recalled_at`, `memory_injections`, `memory_gaps`,
    `memory_events`, co-recalled `fact_links`, clustering. Only the trust/helpful_count mutations are gated.
- `record_feedback` (explicit `fact_feedback` helpful/unhelpful, ±0.05/−0.10) stays the ONLY normal trust
  mutation path. (The `critical` flag, below, is the other influence on recall — not trust.)
- When `trust_from_ranking_enabled=true`, behavior is byte-identical to today (full back-compat).

### Phase 1 — data model (new fields on `memory_facts`)
- Add to `memory_facts`: `critical BOOLEAN DEFAULT false`, `pinned BOOLEAN DEFAULT false`,
  `task_tags TEXT DEFAULT ''`, `critical_reason TEXT DEFAULT ''`.
- **Approach (matches the existing plugin-owned metadata-column pattern):** add these in the `_init_db`
  ALTER column set (store.py ~540, idempotent `ADD COLUMN IF NOT EXISTS`), AND ship a real numbered
  migration **`0033_memory_critical_fields.sql`** that performs the same `ALTER TABLE memory_facts ADD
  COLUMN IF NOT EXISTS …` for versioned parity. Read/write these columns **directly against
  `memory_facts`** (like durability), NOT through the `facts` view. **Do NOT recreate the `facts` view**
  in v1 (lowest blast radius; the view's fixed column list is left exactly as-is).
- Partial index `CREATE INDEX … ON memory_facts (status) WHERE (critical OR pinned)` to keep the critical-lane query cheap (the lane queries `critical OR pinned`, not only `critical`).

### Phase 2 — write path: set critical / task_tags (conservative)
- Extend `quality.py::classify_fact_durability` to additionally return `critical` + `critical_reason`,
  set ONLY for two clear cases (v1 auto-critical = correction OR compliance, precedence correction first):
  - corrections (existing `CORRECTION` signal): "you got X wrong", "I told you", "actually use…",
    "instead of", "renamed to", "no longer".
  - compliance/legal/filing language (new narrow regex): signature/initials/disclosure/compliance/
    accepted offer/CPS/filing/seller-side/buyer-side.
  - conventions (should/must/never/always/policy/rule) are deliberately NOT auto-critical in v1: a
    read-only pass on a real 294-fact corpus showed convention = 72/92 critical candidates and pushed
    the reserved lane to 31% of active facts, defeating the point of a RARE Must-Follow lane. Conventions
    still add `durable_score` and keep the `convention` signal, but `critical` stays false. Making a
    convention must-always requires a future deliberate pin action. (Tightening this to correction +
    compliance only dropped the rate to 20/294 ≈ 7%.)
  - `pinned` is set ONLY by a deliberate pin action ("must-always"). In v1 there is NO pin action, so
    explicit/manual saves do NOT imply pinned; the lane's no-match bypass additionally requires the fact
    be critical.
  - **Never** mark generic workflow facts critical.
- Persist `critical`/`pinned`/`task_tags`/`critical_reason` via a direct `UPDATE memory_facts SET …`
  (mirroring `_set_fact_quality`), from `add_fact_detailed` / `_handle_fact_store` / `on_memory_write`.
- `task_tags` inferred at write time from **content + category + tags + source_uri + linked entities**
  (NOT from active-skill context, which isn't plumbed). e.g. content mentioning "accepted offer/CPS/
  SkySlope" → `task:accepted-offer`; "CMA/comps" → `task:cma`; "post/reel/caption" → `task:social`.

### Phase 3 — reserved Must-Follow Rules recall lane
- New config: `critical_tier_enabled` (**default true**), `critical_recall_limit` (**default 2**).
- New `store.critical_facts_matching(query, session_text, entities, limit)` — selects directly from
  `memory_facts WHERE (critical OR pinned) AND COALESCE(status,'active')='active'`, matching on:
  - `task_tags` tokens present in the query/session text, OR
  - entity overlap (reuse `entity_candidates`), OR
  - category/task words present in the query/session (accepted-offer, cma, social, filing, …).
  - **Bypasses** the min-trust floor (`min_trust=0`), the trust multiplier, and the token-overlap verifier.
  - Order: **pinned first, then match strength, then recency**. Cap at `critical_recall_limit` (2).
- `__init__.py::_build_layered_context` (~1825): when `critical_tier_enabled`, prepend a section
  **before** Durable + Semantic:
  ```
  ### Must-Follow Rules
  - …
  ```
  Dedup these fact_ids against the Durable + Semantic lane (don't double-inject). Record injected
  critical fact_ids in `memory_injections` as usual.
- When `critical_tier_enabled=false`: the Must-Follow Rules lane is absent. (Full byte-identical legacy
  recall additionally requires `trust_from_ranking_enabled=true` — tier-off alone does not restore the
  legacy trust ratchet.) When no critical facts match: the section is omitted entirely.

### Phase 4 — embeddings (safe auto only; existing accounts unchanged)
- Do NOT force `embedding_enabled=true` globally. Existing accounts unchanged.
- New accounts only: support an auto/conditional mode — attempt `build_embedding_client`; if it raises
  `EmbeddingError` (missing key / package), **silently fall back to disabled** (no startup failure, no
  warning spam). The critical lane does NOT depend on embeddings — this is an independent, optional
  improvement and can be dropped from v1 if it adds any startup risk.

### Phase 5 — backfill the existing facts (dry-run first, conservative)
- `backfill_critical` op (sibling to existing `backfill_*`), **dry-run by default**.
- Dry-run REPORT must list, per affected fact: exact `fact_id`, current `status`, and proposed
  `critical` / `pinned` / `task_tags` / `critical_reason`.
- Apply only after the dry-run report is reviewed.
- **Unarchive rule:** only un-archive a fact if it classifies critical AND is NOT `superseded` AND NOT
  explicitly outdated AND appears in the reviewed dry-run report. **Never** auto-unarchive superseded or
  explicitly-outdated facts.
- Idempotent.

### Phase 6 — config + kill switches (`plugins.elevate-memory-store.*`)
- `trust_from_ranking_enabled` — default **false** (ratchet off).
- `critical_tier_enabled` — default **true** (false = exact current recall).
- `critical_recall_limit` — default **2**.
- (No memory-bank knobs in v1; `tools/memory_tool.py` unchanged.)

---

## Test plan (all required)
1. Ratchet: with `trust_from_ranking_enabled=false`, a candidate that loses the top-N cut has its
   `trust_score` and `helpful_count` UNCHANGED after N retrievals (telemetry counters may still move).
2. Explicit feedback still changes trust (`fact_feedback` helpful/unhelpful adjusts as before).
3. A critical fact at trust 0.30 appears in `### Must-Follow Rules` for a matching accepted-offer query.
4. Critical lane absent when `critical_tier_enabled=false` (recall identical to baseline).
5. No critical facts → no `### Must-Follow Rules` section.
6. **Fact-45 replay:** seed the signature rule with `critical=true`, `task_tags=accepted-offer`; assert it
   lands in the injected prompt for an accepted-offer query (was 1/3693 pre-fix).
7. Migration / view compatibility: 0033 applies cleanly; the `facts` view still works unchanged; new
   columns are readable directly from `memory_facts`.
8. Embedding auto/fallback: missing credentials do NOT break startup (degrades silently).

---

## Rollout / soak (LATER — not this turn; do not deploy yet)
1. Branch + worktree in `~/elevate`; implement + full memory test suite green.
2. (On approval) deploy to HER box, run backfill dry-run → review → apply. Soak ~1 week.
   Success metric = `skyleigh-user-corrections.py` rate drops AND critical fact_ids start appearing in
   `memory_injections`.
3. Then Justin's box (confirm fleet vs her-only first). Then fleet via desktop release.
- **This turn: do NOT deploy to Skyleigh, Justin, or fleet. Do NOT touch live boxes. Do NOT modify
  unrelated systems.**

## Top residual risks + mitigation
1. Prompt flooding / cost → hard cap `critical_recall_limit=2`, content clip, dedup vs durable lane,
   kill switch.
2. Over-tagging critical (tier loses meaning) → conservative classifier (corrections + narrow
   compliance regex only — conventions excluded, ~7% of facts on real data); `pinned` for
   must-always; monitor critical count/account.
3. Task mismatch on opaque "[Background task result]" queries → entity + session-text match as backstop;
   Phase 3b (skill-load re-prefetch) is the deferred deeper fix if soak shows misses.

## What v1 does NOT change
- `tools/memory_tool.py` (always-injected bank) — unchanged (no eviction).
- The `facts` compat view — unchanged (new columns read directly off `memory_facts`).
- `session_search`, dedup-at-write, HRR, clustering — unchanged.
- The accepted-offer SKILL gate (already shipped) — stays as the deterministic high-stakes enforcement.
- No `admin-result-writer` hard gate in v1.
