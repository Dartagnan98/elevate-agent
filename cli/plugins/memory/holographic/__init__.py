"""elevate-memory-store — holographic memory plugin using MemoryProvider interface.

Registers as a MemoryProvider plugin, giving the agent structured fact storage
with entity resolution, trust scoring, and HRR-based compositional retrieval.

Original plugin by dusterbloom (PR #2351), adapted to the MemoryProvider ABC.

Config in $ELEVATE_HOME/config.yaml (profile-scoped):
  plugins:
    elevate-memory-store:
      db_path: $ELEVATE_HOME/memory_store.db   # omit to use the default
      auto_extract: false
      turn_journal_enabled: true
      organize_on_session_end: true
      organize_every_n_turns: 0
      daily_organize_enabled: true
      daily_organize_hour: 23
      daily_organize_minute: 55
      default_trust: 0.5
      min_trust_threshold: 0.3
      temporal_decay_half_life: 0
"""

from __future__ import annotations

import json
import logging
import re
import threading
from pathlib import Path
from typing import Any, Dict, List

from agent.memory_provider import MemoryProvider
from tools.registry import tool_error
from . import activity as memory_activity
from .embeddings import EmbeddingError, build_embedding_client, parse_bool
from .store import MemoryStore
from .retrieval import FactRetriever

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Tool schemas (unchanged from original PR)
# ---------------------------------------------------------------------------

FACT_STORE_SCHEMA = {
    "name": "fact_store",
    "description": (
        "Deep structured memory with algebraic reasoning. "
        "Use alongside the memory tool — memory for always-on context, "
        "fact_store for deep recall and compositional queries.\n\n"
        "ACTIONS (simple → powerful):\n"
        "• add — Store a fact the user would expect you to remember.\n"
        "• search — Keyword lookup ('editor config', 'deploy process').\n"
        "• probe — Entity recall: ALL facts about a person/thing.\n"
        "• related — What connects to an entity? Structural adjacency.\n"
        "• reason — Compositional: facts connected to MULTIPLE entities simultaneously.\n"
        "• contradict — Memory hygiene: find facts making conflicting claims.\n"
        "• embedding_status — Inspect semantic embedding index health.\n"
        "• embedding_backfill — Build missing semantic fact embeddings.\n"
        "• chunk_embedding_backfill — Build missing semantic document/chunk embeddings.\n"
        "• journal_status — Inspect the local turn-journal backlog.\n"
        "• organize_journal — Promote pending turn notes into durable facts.\n"
        "• recent — Recall recent session turns from the local journal.\n"
        "• wiki — Open an entity page with facts and backlinks.\n"
        "• layered_recall — Return the same routed memory lanes used by prefetch.\n"
        "• rag_query — Native Elevate RAG over facts, community reports, recent turns, document chunks, and graph wiki.\n"
        "• community_reports — Build/search durable global summaries over memory clusters.\n"
        "• recall_route — Route a question across durable/recent/document/graph lanes.\n"
        "• document_add/document_search — Chunk-level local RAG over source documents.\n"
        "• import_plaud_archive — Build chunk RAG from the local Plaud JSONL archive.\n"
        "• hygiene — Find stale, overused, duplicate, low-trust, and source-missing facts.\n"
        "• cluster/auto_tag/confidence_maintenance/prune_logs/benchmark — jcode-style upkeep and profiling.\n"
        "• memory_events/memory_replay/memory_profile — Audit recall, injection, and token/byte impact.\n"
        "• supersede — Mark an old fact as replaced by a newer fact.\n"
        "• update/remove/list — CRUD operations.\n\n"
        "IMPORTANT: Before answering questions about the user, ALWAYS probe or reason first."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": [
                    "add",
                    "search",
                    "probe",
                    "related",
                    "reason",
                    "contradict",
                    "embedding_status",
                    "embedding_backfill",
                    "chunk_embedding_backfill",
                    "journal_status",
                    "organize_journal",
                    "recent",
                    "wiki",
                    "layered_recall",
                    "rag_query",
                    "community_reports",
                    "recall_route",
                    "document_add",
                    "document_search",
                    "import_plaud_archive",
                    "hygiene",
                    "memory_events",
                    "memory_replay",
                    "memory_profile",
                    "cluster",
                    "auto_tag",
                    "confidence_maintenance",
                    "prune_logs",
                    "benchmark",
                    "supersede",
                    "update",
                    "remove",
                    "list",
                ],
            },
            "content": {"type": "string", "description": "Fact content (required for 'add')."},
            "query": {"type": "string", "description": "Search query (required for 'search')."},
            "entity": {"type": "string", "description": "Entity name for 'probe'/'related'."},
            "entities": {"type": "array", "items": {"type": "string"}, "description": "Entity names for 'reason'."},
            "fact_id": {"type": "integer", "description": "Fact ID for 'update'/'remove'."},
            "category": {
                "type": "string",
                "enum": [
                    "user_pref",
                    "project",
                    "tool",
                    "general",
                    "contact",
                    "lead",
                    "client",
                    "vendor",
                    "property",
                    "deal",
                    "listing",
                    "buyer_need",
                    "showing",
                    "transaction",
                    "task",
                    "market",
                    "follow_up",
                ],
            },
            "tags": {"type": "string", "description": "Comma-separated tags."},
            "trust_delta": {"type": "number", "description": "Trust adjustment for 'update'."},
            "min_trust": {"type": "number", "description": "Minimum trust filter (default: 0.3)."},
            "limit": {"type": "integer", "description": "Max results (default: 10)."},
            "session_id": {"type": "string", "description": "Optional session scope for journal actions."},
            "session_day": {"type": "string", "description": "Optional YYYY-MM-DD day scope for journal actions."},
            "include_assistant": {"type": "boolean", "description": "Include assistant side for recent turn recall."},
            "source_type": {"type": "string", "description": "Source type for facts/documents/chunk searches."},
            "memory_space": {"type": "string", "description": "Optional project/workspace memory scope."},
            "old_fact_id": {"type": "integer", "description": "Old fact ID for supersede."},
            "new_fact_id": {"type": "integer", "description": "New fact ID for supersede."},
            "source_uri": {"type": "string", "description": "Source URI/path/id for facts/documents."},
            "source_excerpt": {"type": "string", "description": "Short evidence excerpt for source-aware facts."},
            "observed_at": {"type": "string", "description": "When this fact/source was observed."},
            "title": {"type": "string", "description": "Document title for document_add/imports."},
            "path": {"type": "string", "description": "Local archive path for import_plaud_archive."},
            "metadata": {"type": "object", "description": "Optional document metadata."},
            "chunks": {"type": "array", "items": {"type": "string"}, "description": "Pre-split chunks for document_add."},
        },
        "required": ["action"],
    },
}

FACT_FEEDBACK_SCHEMA = {
    "name": "fact_feedback",
    "description": (
        "Rate a fact after using it. Mark 'helpful' if accurate, 'unhelpful' if outdated. "
        "This trains the memory — good facts rise, bad facts sink."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["helpful", "unhelpful"]},
            "fact_id": {"type": "integer", "description": "The fact ID to rate."},
        },
        "required": ["action", "fact_id"],
    },
}


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def _load_plugin_config() -> dict:
    from elevate_constants import get_elevate_home
    config_path = get_elevate_home() / "config.yaml"
    if not config_path.exists():
        return {}
    try:
        import yaml
        with open(config_path) as f:
            all_config = yaml.safe_load(f) or {}
        return all_config.get("plugins", {}).get("elevate-memory-store", {}) or {}
    except Exception:
        return {}


def _parse_int(value: object, default: int, *, minimum: int = 0) -> int:
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError):
        return default
    return max(minimum, parsed)


# ---------------------------------------------------------------------------
# MemoryProvider implementation
# ---------------------------------------------------------------------------

class HolographicMemoryProvider(MemoryProvider):
    """Holographic memory with structured facts, entity resolution, and HRR retrieval."""

    def __init__(self, config: dict | None = None):
        self._config = config or _load_plugin_config()
        self._store = None
        self._retriever = None
        self._min_trust = float(self._config.get("min_trust_threshold", 0.3))
        self._embedding_error = ""
        self._session_id = ""
        self._auto_extract = parse_bool(self._config.get("auto_extract"), default=False)
        self._turn_journal_enabled = parse_bool(
            self._config.get("turn_journal_enabled"),
            default=True,
        )
        self._organize_on_session_end = parse_bool(
            self._config.get("organize_on_session_end"),
            default=True,
        )
        self._organize_every_n_turns = _parse_int(
            self._config.get("organize_every_n_turns"),
            0,
            minimum=0,
        )
        self._turn_journal_max_chars = _parse_int(
            self._config.get("turn_journal_max_chars"),
            8000,
            minimum=1000,
        )
        self._organize_batch_limit = _parse_int(
            self._config.get("organize_batch_limit"),
            20,
            minimum=1,
        )
        self._layered_prefetch_enabled = parse_bool(
            self._config.get("layered_prefetch_enabled"),
            default=True,
        )
        self._recent_recall_enabled = parse_bool(
            self._config.get("recent_recall_enabled"),
            default=True,
        )
        self._graph_recall_enabled = parse_bool(
            self._config.get("graph_recall_enabled"),
            default=True,
        )
        self._recent_recall_limit = _parse_int(
            self._config.get("recent_recall_limit"),
            4,
            minimum=1,
        )
        self._durable_recall_limit = _parse_int(
            self._config.get("durable_recall_limit"),
            4,
            minimum=1,
        )
        self._graph_recall_limit = _parse_int(
            self._config.get("graph_recall_limit"),
            2,
            minimum=1,
        )
        self._recent_turn_max_chars = _parse_int(
            self._config.get("recent_turn_max_chars"),
            240,
            minimum=80,
        )
        self._turns_since_organize = 0
        self._prefetch_cache: dict[str, str] = {}
        self._prefetch_lock = threading.RLock()
        self._last_layered_facts: list[dict] = []
        self._last_layered_chunks: list[dict] = []
        self._session_topic_tokens: dict[str, set[str]] = {}
        self._session_turn_counts: dict[str, int] = {}
        self._topic_extraction_enabled = parse_bool(
            self._config.get("topic_extraction_enabled"),
            default=False,
        )
        self._topic_change_threshold = float(self._config.get("topic_change_threshold", 0.28))
        self._topic_extract_min_turns = _parse_int(self._config.get("topic_extract_min_turns"), 4, minimum=1)
        self._periodic_extract_interval = _parse_int(self._config.get("periodic_extract_interval"), 12, minimum=0)

    @property
    def name(self) -> str:
        return "holographic"

    def is_available(self) -> bool:
        return True  # SQLite is always available, numpy is optional

    def save_config(self, values, elevate_home):
        """Write config to config.yaml under plugins.elevate-memory-store."""
        from pathlib import Path
        config_path = Path(elevate_home) / "config.yaml"
        try:
            import yaml
            existing = {}
            if config_path.exists():
                with open(config_path) as f:
                    existing = yaml.safe_load(f) or {}
            existing.setdefault("plugins", {})
            existing["plugins"]["elevate-memory-store"] = values
            with open(config_path, "w") as f:
                yaml.dump(existing, f, default_flow_style=False)
        except Exception:
            pass

    def get_config_schema(self):
        from elevate_constants import display_elevate_home
        _default_db = f"{display_elevate_home()}/memory_store.db"
        return [
            {"key": "db_path", "description": "SQLite database path", "default": _default_db},
            {"key": "auto_extract", "description": "Auto-extract facts at session end", "default": "false", "choices": ["true", "false"]},
            {"key": "turn_journal_enabled", "description": "Record completed turns locally for later memory organization", "default": "true", "choices": ["true", "false"]},
            {"key": "organize_on_session_end", "description": "Organize pending turn-journal entries when a session ends", "default": "true", "choices": ["true", "false"]},
            {"key": "organize_every_n_turns", "description": "Also organize pending journal entries every N completed turns (0 disables)", "default": "0"},
            {"key": "daily_organize_enabled", "description": "Gateway runs a local daily journal organization pass even if sessions stay open", "default": "true", "choices": ["true", "false"]},
            {"key": "daily_organize_hour", "description": "Local hour for daily journal organization", "default": "23"},
            {"key": "daily_organize_minute", "description": "Local minute for daily journal organization", "default": "55"},
            {"key": "daily_organize_max_batches", "description": "Max organization batches in one daily pass", "default": "50"},
            {"key": "turn_journal_max_chars", "description": "Max characters saved per user/assistant side of a turn", "default": "8000"},
            {"key": "organize_batch_limit", "description": "Max pending turns to organize in one pass", "default": "20"},
            {"key": "layered_prefetch_enabled", "description": "Inject recent/durable/graph lanes instead of one flat memory list", "default": "true", "choices": ["true", "false"]},
            {"key": "recent_recall_enabled", "description": "Include recent same-session journal recall", "default": "true", "choices": ["true", "false"]},
            {"key": "graph_recall_enabled", "description": "Include wiki-style entity graph recall", "default": "true", "choices": ["true", "false"]},
            {"key": "recent_recall_limit", "description": "Max recent turns in memory prefetch", "default": "4"},
            {"key": "durable_recall_limit", "description": "Max durable facts in memory prefetch", "default": "4"},
            {"key": "graph_recall_limit", "description": "Max entity wiki pages in memory prefetch", "default": "2"},
            {"key": "recent_turn_max_chars", "description": "Max characters per recent turn in prefetch", "default": "240"},
            {"key": "topic_extraction_enabled", "description": "Incrementally organize memory on topic changes/long sessions", "default": "false", "choices": ["true", "false"]},
            {"key": "topic_change_threshold", "description": "Token/Jaccard threshold for incremental topic-change extraction", "default": "0.28"},
            {"key": "topic_extract_min_turns", "description": "Minimum turns before topic-change journal organization", "default": "4"},
            {"key": "periodic_extract_interval", "description": "Organize journal every N turns during long sessions (0 disables)", "default": "12"},
            {"key": "default_trust", "description": "Default trust score for new facts", "default": "0.5"},
            {"key": "hrr_dim", "description": "HRR vector dimensions", "default": "1024"},
            {"key": "embedding_enabled", "description": "Enable semantic embeddings", "default": "false", "choices": ["true", "false"]},
            {"key": "embedding_provider", "description": "Embedding backend", "default": "openai", "choices": ["openai", "ollama", "openai_compatible", "local_minilm"]},
            {"key": "embedding_model", "description": "Embedding model name", "default": "text-embedding-3-small"},
            {"key": "embedding_dimensions", "description": "Optional vector dimensions override", "default": ""},
            {"key": "embedding_base_url", "description": "Optional provider base URL", "default": ""},
            {"key": "embedding_api_key_env", "description": "API key environment variable", "default": "OPENAI_API_KEY"},
            {"key": "embedding_cache_dir", "description": "Optional local model cache directory for local_minilm", "default": ""},
        ]

    def initialize(self, session_id: str, **kwargs) -> None:
        from elevate_constants import get_elevate_home
        _elevate_home = str(get_elevate_home())
        _default_db = _elevate_home + "/memory_store.db"
        db_path = self._config.get("db_path", _default_db)
        # Expand $ELEVATE_HOME in user-supplied paths so config values like
        # "$ELEVATE_HOME/memory_store.db" or "~/.elevate/memory_store.db" both
        # resolve to the active profile's directory.
        if isinstance(db_path, str):
            db_path = db_path.replace("$ELEVATE_HOME", _elevate_home)
            db_path = db_path.replace("${ELEVATE_HOME}", _elevate_home)
        default_trust = float(self._config.get("default_trust", 0.5))
        hrr_dim = int(self._config.get("hrr_dim", 1024))
        hrr_weight = float(self._config.get("hrr_weight", 0.3))
        embedding_weight = float(self._config.get("embedding_weight", 0.35))
        temporal_decay = int(self._config.get("temporal_decay_half_life", 0))

        embedding_client = None
        self._embedding_error = ""
        if parse_bool(self._config.get("embedding_enabled"), default=False):
            try:
                embedding_client = build_embedding_client(self._config)
            except EmbeddingError as exc:
                self._embedding_error = str(exc)
                logger.warning("Embedding provider unavailable: %s", exc)

        self._store = MemoryStore(
            db_path=db_path,
            default_trust=default_trust,
            hrr_dim=hrr_dim,
            embedding_client=embedding_client,
        )
        self._retriever = FactRetriever(
            store=self._store,
            temporal_decay_half_life=temporal_decay,
            hrr_weight=hrr_weight,
            embedding_weight=embedding_weight if embedding_client else 0.0,
            hrr_dim=hrr_dim,
        )
        self._session_id = session_id
        try:
            self._store.record_memory_event("memory.provider.initialized", session_id=session_id, detail={"db_path": str(db_path)})
        except Exception:
            pass

    def system_prompt_block(self) -> str:
        if not self._store:
            return ""
        try:
            total = self._store._conn.execute(
                "SELECT COUNT(*) FROM facts"
            ).fetchone()[0]
        except Exception:
            total = 0
        embedding_note = ""
        try:
            emb = self._store.embedding_status()
            if emb.get("enabled"):
                embedding_note = (
                    f" Semantic embeddings active via {emb.get('provider')}:{emb.get('model')}."
                )
            elif self._embedding_error:
                embedding_note = f" Semantic embeddings configured but unavailable: {self._embedding_error}."
        except Exception:
            pass
        if total == 0:
            return (
                "# Elevate Memory Core\n"
                f"Active. Empty fact store.{embedding_note} Proactively add facts the user would expect you to remember.\n"
                "Use fact_store(action='add') to store durable structured facts about people, projects, preferences, decisions.\n"
                "Use fact_feedback to rate facts after using them (trains trust scores)."
            )
        return (
            f"# Elevate Memory Core\n"
            f"Active. {total} facts stored with entity resolution, trust scoring, and hybrid retrieval.{embedding_note}\n"
            f"Use fact_store to search, probe entities, reason across entities, or add facts.\n"
            f"Use fact_feedback to rate facts after using them (trains trust scores)."
        )

    def prefetch(self, query: str, *, session_id: str = "") -> str:
        if not self._retriever or not query:
            return ""
        cache_key = self._cache_key(query, session_id=session_id)
        with self._prefetch_lock:
            cached = self._prefetch_cache.pop(cache_key, "")
        if cached:
            try:
                self._store.record_memory_event("memory.prefetch.cache_hit", session_id=session_id, detail={"query": query, "prompt_chars": len(cached)})
            except Exception:
                pass
            return cached
        memory_activity.pipeline_start(reason="prefetch")
        try:
            if self._layered_prefetch_enabled:
                context = self._build_layered_context(query, session_id=session_id)
                memory_activity.record_event(
                    "memory.prefetch.complete",
                    message="layered recall ready" if context else "no relevant memory",
                    state="idle",
                    step="inject",
                    status="done" if context else "skipped",
                    data={"prompt_chars": len(context), "session_id": session_id},
                )
                if context:
                    self._record_context_injection(
                        query,
                        context,
                        session_id=session_id,
                        facts=getattr(self, "_last_layered_facts", []),
                        chunks=getattr(self, "_last_layered_chunks", []),
                        source="layered_prefetch",
                    )
                return context

            results = self._retriever.search(
                query,
                min_trust=self._min_trust,
                limit=self._durable_recall_limit,
            )
            if not results:
                memory_activity.record_event(
                    "memory.prefetch.empty",
                    message="no durable facts matched",
                    state="idle",
                    step="inject",
                    status="skipped",
                    data={"hits": 0},
                )
                return ""
            lines = []
            for r in results:
                trust = r.get("trust_score", r.get("trust", 0))
                lines.append(f"- [{trust:.1f}] {r.get('content', '')}")
            context = "## Elevate Memory Core\n" + "\n".join(lines)
            self._record_context_injection(query, context, session_id=session_id, facts=results, source="flat_prefetch")
            memory_activity.record_event(
                "memory.prefetch.complete",
                message=f"injected {len(results)} durable fact(s)",
                state="idle",
                step="inject",
                status="done",
                data={"hits": len(results), "prompt_chars": len(context)},
            )
            return context
        except Exception as e:
            memory_activity.record_event(
                "memory.prefetch.error",
                message=str(e),
                state="error",
                step="search",
                status="error",
            )
            logger.debug("Holographic prefetch failed: %s", e)
            return ""

    def queue_prefetch(self, query: str, *, session_id: str = "") -> None:
        """Build and cache recall context for a likely next turn.

        This is deliberately local and bounded. If query changes, prefetch()
        simply falls back to live retrieval.
        """
        if not self._retriever or not query or not self._layered_prefetch_enabled:
            return
        def worker() -> None:
            try:
                context = self._build_layered_context(query, session_id=session_id)
                if context:
                    with self._prefetch_lock:
                        self._prefetch_cache[self._cache_key(query, session_id=session_id)] = context
                        if len(self._prefetch_cache) > 16:
                            for key in list(self._prefetch_cache.keys())[:-16]:
                                self._prefetch_cache.pop(key, None)
            except Exception as exc:
                logger.debug("Holographic queue_prefetch failed: %s", exc)
        threading.Thread(target=worker, daemon=True).start()

    def sync_turn(self, user_content: str, assistant_content: str, *, session_id: str = "") -> None:
        if not self._store or not self._turn_journal_enabled:
            return
        turn_session_id = session_id or self._session_id or ""
        try:
            turn_id = self._store.record_turn(
                turn_session_id,
                user_content,
                assistant_content,
                max_chars=self._turn_journal_max_chars,
            )
            memory_activity.record_event(
                "memory.turn_recorded",
                message="turn journaled for later organization",
                state="idle",
                step="maintain",
                status="pending",
                data={"turn_id": turn_id, "session_id": turn_session_id},
            )
        except Exception as exc:
            memory_activity.record_event(
                "memory.turn_record_failed",
                message=str(exc),
                state="error",
                step="maintain",
                status="error",
                data={"session_id": turn_session_id},
            )
            logger.debug("Holographic turn journal write failed: %s", exc)
            return

        self._maybe_incremental_topic_extract(turn_session_id, user_content)

        if self._organize_every_n_turns <= 0:
            return
        self._turns_since_organize += 1
        if self._turns_since_organize < self._organize_every_n_turns:
            return

        self._turns_since_organize = 0
        try:
            memory_activity.record_event(
                "memory.organize.started",
                message="periodic journal organization",
                state="maintaining",
                step="maintain",
                status="running",
                data={"session_id": turn_session_id},
            )
            self._organize_journal(
                session_id=turn_session_id,
                limit=self._organize_batch_limit,
            )
        except Exception as exc:
            memory_activity.record_event(
                "memory.organize.error",
                message=str(exc),
                state="error",
                step="maintain",
                status="error",
            )
            logger.debug("Holographic turn journal organization failed: %s", exc)

    def get_tool_schemas(self) -> List[Dict[str, Any]]:
        return [FACT_STORE_SCHEMA, FACT_FEEDBACK_SCHEMA]

    def handle_tool_call(self, tool_name: str, args: Dict[str, Any], **kwargs) -> str:
        if tool_name == "fact_store":
            return self._handle_fact_store(args)
        elif tool_name == "fact_feedback":
            return self._handle_fact_feedback(args)
        return tool_error(f"Unknown tool: {tool_name}")

    def on_session_end(self, messages: List[Dict[str, Any]]) -> None:
        if not self._store:
            return
        if self._auto_extract and messages:
            self._auto_extract_facts(messages)
        if self._turn_journal_enabled and self._organize_on_session_end:
            self._organize_journal(
                session_id=self._session_id,
                limit=self._organize_batch_limit,
            )

    def on_memory_write(self, action: str, target: str, content: str) -> None:
        """Mirror built-in memory writes as facts."""
        if action == "add" and self._store and content:
            try:
                category = "user_pref" if target == "user" else "general"
                self._store.add_fact(content, category=category)
            except Exception as e:
                logger.debug("Holographic memory_write mirror failed: %s", e)

    def shutdown(self) -> None:
        if self._store:
            try:
                self._store.close()
            except Exception:
                pass
        self._store = None
        self._retriever = None

    # -- Tool handlers -------------------------------------------------------

    def _handle_fact_store(self, args: dict) -> str:
        try:
            action = args["action"]
            store = self._store
            retriever = self._retriever

            if action == "add":
                fact_id = store.add_fact(
                    args["content"],
                    category=args.get("category", "general"),
                    tags=args.get("tags", ""),
                    source_type=args.get("source_type", "manual"),
                    source_uri=args.get("source_uri", ""),
                    source_excerpt=args.get("source_excerpt", ""),
                    observed_at=args.get("observed_at"),
                    memory_space=args.get("memory_space", ""),
                )
                memory_activity.record_event(
                    "memory.tool.remembered",
                    message="fact stored",
                    state="idle",
                    step="maintain",
                    status="done",
                    data={"fact_id": fact_id, "category": args.get("category", "general")},
                )
                return json.dumps({"fact_id": fact_id, "status": "added"})

            elif action == "search":
                results = retriever.search(
                    args["query"],
                    category=args.get("category"),
                    min_trust=float(args.get("min_trust", self._min_trust)),
                    limit=int(args.get("limit", 10)),
                )
                memory_activity.record_event(
                    "memory.tool.recalled",
                    message=f"fact search returned {len(results)} result(s)",
                    state="idle",
                    step="search",
                    status="done",
                    data={"query": args.get("query"), "count": len(results)},
                )
                return json.dumps({"results": results, "count": len(results)})

            elif action == "probe":
                results = retriever.probe(
                    args["entity"],
                    category=args.get("category"),
                    limit=int(args.get("limit", 10)),
                )
                return json.dumps({"results": results, "count": len(results)})

            elif action == "related":
                results = retriever.related(
                    args["entity"],
                    category=args.get("category"),
                    limit=int(args.get("limit", 10)),
                )
                return json.dumps({"results": results, "count": len(results)})

            elif action == "reason":
                entities = args.get("entities", [])
                if not entities:
                    return tool_error("reason requires 'entities' list")
                results = retriever.reason(
                    entities,
                    category=args.get("category"),
                    limit=int(args.get("limit", 10)),
                )
                return json.dumps({"results": results, "count": len(results)})

            elif action == "contradict":
                results = retriever.contradict(
                    category=args.get("category"),
                    limit=int(args.get("limit", 10)),
                )
                return json.dumps({"results": results, "count": len(results)})

            elif action == "embedding_status":
                return json.dumps(store.embedding_status())

            elif action == "embedding_backfill":
                limit = args.get("limit")
                memory_activity.record_event(
                    "memory.embedding_backfill.started",
                    message="embedding backfill started",
                    state="embedding",
                    step="search",
                    status="running",
                    data={"limit": limit},
                )
                result = store.backfill_embeddings(
                    limit=int(limit) if limit is not None else None,
                )
                memory_activity.record_event(
                    "memory.embedding_backfill.complete",
                    message=f"indexed {result.get('indexed', 0)} fact(s)",
                    state="idle",
                    step="search",
                    status="done" if result.get("enabled") else "skipped",
                    data=result,
                )
                return json.dumps(result)

            elif action == "chunk_embedding_backfill":
                limit = args.get("limit")
                batch_size = int(args.get("batch_size", 96))
                source_type = args.get("source_type")
                memory_activity.record_event(
                    "memory.chunk_embedding_backfill.started",
                    message="chunk embedding backfill started",
                    state="embedding",
                    step="search",
                    status="running",
                    data={"limit": limit, "batch_size": batch_size, "source_type": source_type},
                )
                result = store.backfill_chunk_embeddings(
                    limit=int(limit) if limit is not None else None,
                    source_type=source_type,
                    batch_size=batch_size,
                )
                memory_activity.record_event(
                    "memory.chunk_embedding_backfill.complete",
                    message=f"indexed {result.get('indexed', 0)} chunk(s)",
                    state="idle",
                    step="search",
                    status="done" if result.get("enabled") else "skipped",
                    data=result,
                )
                return json.dumps(result)

            elif action == "journal_status":
                return json.dumps(
                    store.journal_status(
                        session_id=args.get("session_id"),
                        session_day=args.get("session_day"),
                    )
                )

            elif action == "organize_journal":
                result = self._organize_journal(
                    session_id=args.get("session_id"),
                    session_day=args.get("session_day"),
                    limit=int(args["limit"]) if args.get("limit") is not None else None,
                )
                return json.dumps(result)

            elif action == "recent":
                turns = store.recent_turns(
                    session_id=args.get("session_id") or self._session_id,
                    session_day=args.get("session_day"),
                    query=args.get("query"),
                    limit=int(args.get("limit", self._recent_recall_limit)),
                    include_assistant=bool(args.get("include_assistant", False)),
                )
                return json.dumps({"turns": turns, "count": len(turns)})

            elif action == "wiki":
                result = store.entity_wiki(
                    args.get("entity") or args.get("query") or "",
                    limit=int(args.get("limit", 8)),
                )
                return json.dumps(result)

            elif action == "layered_recall":
                query = args.get("query") or args.get("content") or ""
                context = self._build_layered_context(
                    query,
                    session_id=args.get("session_id") or self._session_id,
                )
                return json.dumps({"context": context, "empty": not bool(context.strip())})

            elif action == "rag_query":
                query = args.get("query") or args.get("content") or ""
                result = self._rag_query(
                    query,
                    session_id=args.get("session_id") or self._session_id,
                    limit=int(args.get("limit", 8)),
                    source_type=args.get("source_type"),
                    mode=str(args.get("mode") or "mix"),
                    max_chars=int(args.get("max_chars", args.get("token_budget", 12000))),
                )
                return json.dumps(result)

            elif action == "community_reports":
                cluster_id = args.get("cluster_id") or args.get("entity") or ""
                query = args.get("query") or args.get("content") or ""
                if cluster_id:
                    result = store.build_community_report(cluster_id, session_id=args.get("session_id") or self._session_id)
                    return json.dumps(result)
                results = store.search_community_reports(query, limit=int(args.get("limit", 5)))
                return json.dumps({"results": results, "count": len(results)})

            elif action == "recall_route":
                query = args.get("query") or args.get("content") or ""
                result = self._recall_route(query, session_id=args.get("session_id") or self._session_id)
                return json.dumps(result)

            elif action == "document_add":
                source_uri = args.get("source_uri") or args.get("path") or args.get("title") or ""
                chunks = args.get("chunks") or []
                if not chunks and args.get("content"):
                    chunks = store.chunk_text(args.get("content", ""))
                result = store.add_document_chunks(
                    source_uri=source_uri,
                    chunks=chunks,
                    title=args.get("title", ""),
                    source_type=args.get("source_type", "document"),
                    metadata=args.get("metadata") or {},
                    modal_assets=args.get("modal_assets") or args.get("assets") or [],
                )
                return json.dumps(result)

            elif action == "document_search":
                results = store.document_search(
                    args.get("query") or args.get("content") or "",
                    source_type=args.get("source_type"),
                    limit=int(args.get("limit", 8)),
                )
                return json.dumps({"results": results, "count": len(results)})

            elif action == "import_plaud_archive":
                result = self._import_plaud_archive(
                    path=args.get("path"),
                    limit=int(args["limit"]) if args.get("limit") is not None else None,
                )
                return json.dumps(result)

            elif action == "hygiene":
                report = store.memory_hygiene_report(limit=int(args.get("limit", 20)))
                try:
                    report["contradictions"] = retriever.contradict(limit=int(args.get("limit", 20)))
                except Exception:
                    report["contradictions"] = []
                return json.dumps(report)

            elif action == "memory_events":
                events = store.recent_memory_events(
                    session_id=args.get("session_id"),
                    limit=int(args.get("limit", 50)),
                )
                return json.dumps({"events": events, "count": len(events)})

            elif action == "memory_replay":
                return json.dumps(store.memory_replay(
                    session_id=args.get("session_id") or self._session_id,
                    limit=int(args.get("limit", 50)),
                ))

            elif action == "memory_profile":
                return json.dumps(store.memory_profile(
                    session_id=args.get("session_id") or self._session_id,
                ))

            elif action == "cluster":
                fact_ids = args.get("fact_ids") or args.get("entities") or []
                if isinstance(fact_ids, str):
                    fact_ids = [x.strip() for x in fact_ids.split(",") if x.strip()]
                return json.dumps(store.refine_memory_clusters(
                    fact_ids=fact_ids,
                    query=args.get("query") or args.get("content") or "",
                    session_id=args.get("session_id") or self._session_id,
                ))

            elif action == "auto_tag":
                fact_ids = args.get("fact_ids") or []
                if isinstance(fact_ids, str):
                    fact_ids = [x.strip() for x in fact_ids.split(",") if x.strip()]
                return json.dumps(store.infer_tags_for_facts(
                    fact_ids=fact_ids,
                    limit=int(args.get("limit", 50)),
                ))

            elif action == "confidence_maintenance":
                verified_ids = args.get("verified_ids") or []
                rejected_ids = args.get("rejected_ids") or []
                if isinstance(verified_ids, str):
                    verified_ids = [x.strip() for x in verified_ids.split(",") if x.strip()]
                if isinstance(rejected_ids, str):
                    rejected_ids = [x.strip() for x in rejected_ids.split(",") if x.strip()]
                return json.dumps(store.confidence_maintenance(
                    verified_ids=verified_ids,
                    rejected_ids=rejected_ids,
                    prune=str(args.get("prune", "true")).lower() not in ("false", "0", "no"),
                ))

            elif action == "prune_logs":
                return json.dumps(store.prune_memory_logs(
                    retention_days=int(args.get("retention_days", args.get("limit", 30))),
                ))

            elif action == "benchmark":
                queries = args.get("queries") or args.get("entities") or []
                if isinstance(queries, str):
                    queries = [q.strip() for q in queries.split("||") if q.strip()]
                return json.dumps(store.memory_benchmark(queries=queries, limit=int(args.get("limit", 5))))

            elif action == "supersede":
                old_id = int(args.get("old_fact_id") or args.get("fact_id"))
                new_id = int(args.get("new_fact_id"))
                return json.dumps({"superseded": store.supersede_fact(old_id, new_id)})

            elif action == "update":
                updated = store.update_fact(
                    int(args["fact_id"]),
                    content=args.get("content"),
                    trust_delta=float(args["trust_delta"]) if "trust_delta" in args else None,
                    tags=args.get("tags"),
                    category=args.get("category"),
                    source_type=args.get("source_type"),
                    source_uri=args.get("source_uri"),
                    source_excerpt=args.get("source_excerpt"),
                    observed_at=args.get("observed_at"),
                    memory_space=args.get("memory_space"),
                )
                return json.dumps({"updated": updated})

            elif action == "remove":
                removed = store.remove_fact(int(args["fact_id"]))
                return json.dumps({"removed": removed})

            elif action == "list":
                facts = store.list_facts(
                    category=args.get("category"),
                    min_trust=float(args.get("min_trust", 0.0)),
                    limit=int(args.get("limit", 10)),
                )
                return json.dumps({"facts": facts, "count": len(facts)})

            else:
                return tool_error(f"Unknown action: {action}")

        except KeyError as exc:
            return tool_error(f"Missing required argument: {exc}")
        except Exception as exc:
            return tool_error(str(exc))

    def _handle_fact_feedback(self, args: dict) -> str:
        try:
            fact_id = int(args["fact_id"])
            helpful = args["action"] == "helpful"
            result = self._store.record_feedback(fact_id, helpful=helpful)
            return json.dumps(result)
        except KeyError as exc:
            return tool_error(f"Missing required argument: {exc}")
        except Exception as exc:
            return tool_error(str(exc))


    # -- Routed recall / document imports ------------------------------------

    def _record_context_injection(
        self,
        query: str,
        context: str,
        *,
        session_id: str = "",
        facts: list[dict] | None = None,
        chunks: list[dict] | None = None,
        source: str = "prefetch",
    ) -> None:
        if not self._store or not context:
            return
        facts = facts or self._extract_fact_refs_from_context(context)
        chunks = chunks or []
        try:
            self._store.record_memory_injection(
                session_id=session_id or self._session_id,
                query=query,
                content=context,
                fact_ids=[int(f.get("fact_id")) for f in facts if f.get("fact_id")],
                chunk_ids=[int(c.get("chunk_id")) for c in chunks if c.get("chunk_id")],
                source=source,
            )
        except Exception as exc:
            logger.debug("Memory injection recording failed: %s", exc)

    def _extract_fact_refs_from_context(self, context: str) -> list[dict]:
        # Context rendering does not currently carry IDs. This intentionally returns
        # empty until sections pass facts explicitly; replay still stores content.
        return []

    def _verify_fact_results(
        self,
        query: str,
        results: list[dict],
        *,
        limit: int,
        session_id: str = "",
    ) -> tuple[list[dict], list[int]]:
        """Cheap relevance verifier + session-level injection dedupe.

        This is intentionally deterministic. It avoids another model call while
        giving us jcode-style verified/rejected accounting.
        """
        if not results:
            return [], []
        injected = self._store.injected_memory_ids(session_id).get("fact_ids", set()) if self._store else set()
        q_tokens = self._meaningful_tokens(query)
        scored: list[tuple[float, dict]] = []
        rejected: list[int] = []
        for fact in results:
            fid = int(fact.get("fact_id") or 0)
            if fid and fid in injected:
                rejected.append(fid)
                continue
            text = " ".join(str(fact.get(k, "")) for k in ("content", "tags", "category", "source_uri", "memory_space"))
            tokens = self._meaningful_tokens(text)
            overlap = len(q_tokens & tokens)
            relevance = overlap / max(1, len(q_tokens)) if q_tokens else 0.5
            base_score = float(fact.get("score", 0.0) or 0.0)
            trust = float(fact.get("trust_score", 0.0) or 0.0)
            score = (relevance * 0.65) + (base_score * 0.25) + (trust * 0.10)
            # Keep high-trust/source-specific facts even when query is short.
            if score >= 0.08 or (trust >= 0.65 and overlap > 0):
                scored.append((score, fact))
            else:
                if fid:
                    rejected.append(fid)
        scored.sort(key=lambda item: item[0], reverse=True)
        verified = [fact for _, fact in scored[: max(1, int(limit))]]
        if not verified and results:
            # Avoid over-pruning only when the verifier did not explicitly reject every candidate.
            # Session dedupe is an explicit rejection and should not be bypassed by fallback.
            candidate_ids = [int(f.get("fact_id") or 0) for f in results if f.get("fact_id")]
            if set(candidate_ids) - set(rejected):
                verified = [results[0]]
                rejected = [int(f.get("fact_id")) for f in results[1:] if f.get("fact_id")]
        return verified, rejected

    def _maybe_incremental_topic_extract(self, session_id: str, user_content: str) -> None:
        if not self._topic_extraction_enabled or not self._store or not self._turn_journal_enabled:
            return
        tokens = self._meaningful_tokens(user_content)
        if not tokens:
            return
        count = self._session_turn_counts.get(session_id, 0) + 1
        self._session_turn_counts[session_id] = count
        previous = self._session_topic_tokens.get(session_id)
        self._session_topic_tokens[session_id] = tokens
        should_extract = False
        reason = ""
        if previous and count >= self._topic_extract_min_turns:
            sim = len(previous & tokens) / max(1, len(previous | tokens))
            if sim < self._topic_change_threshold:
                should_extract = True
                reason = f"topic_change:{sim:.2f}"
        if self._periodic_extract_interval and count % self._periodic_extract_interval == 0:
            should_extract = True
            reason = reason or "periodic"
        if not should_extract:
            return
        try:
            self._store.record_memory_event("memory.topic_extract.started", session_id=session_id, detail={"reason": reason, "turn_count": count})
            self._organize_journal(session_id=session_id, limit=self._organize_batch_limit)
            self._store.record_memory_event("memory.topic_extract.complete", session_id=session_id, detail={"reason": reason, "turn_count": count})
        except Exception as exc:
            logger.debug("Topic-change memory extraction failed: %s", exc)

    @staticmethod
    def _meaningful_tokens(text: str) -> set[str]:
        stop = {
            "the", "and", "for", "that", "this", "with", "you", "your", "are", "was", "were",
            "what", "when", "where", "why", "how", "can", "could", "should", "would", "have",
            "has", "had", "from", "into", "about", "like", "just", "but", "not", "all", "our",
        }
        return {t for t in re.findall(r"[A-Za-z0-9_]+", str(text or "").lower()) if len(t) >= 3 and t not in stop}

    def _recall_route(self, query: str, *, session_id: str = "") -> dict:
        """Route a question across the best memory lanes without dumping everything."""
        query = str(query or "").strip()
        q = query.lower()
        lanes: list[str] = []
        if any(term in q for term in ("plaud", "meeting", "call", "transcript", "discuss", "talked", "conversation")):
            lanes.append("plaud")
        if any(term in q for term in ("ad", "ads", "campaign", "google", "meta", "facebook", "instagram")):
            lanes.append("ads")
        if any(term in q for term in ("repo", "code", "file", "skill", "project", "graphify")):
            lanes.append("project")
        if not lanes:
            lanes.extend(["durable", "recent", "graph"])

        result: dict[str, object] = {"query": query, "lanes": lanes, "sections": {}}
        sections: dict[str, object] = {}
        if "plaud" in lanes and self._store:
            sections["plaud_chunks"] = self._store.document_search(query, source_type="plaud", limit=6)
        if "durable" in lanes or "project" in lanes or "ads" in lanes:
            if self._retriever:
                sections["durable"] = self._retriever.search(query, min_trust=self._min_trust, limit=self._durable_recall_limit)
        if "recent" in lanes and self._store:
            sections["recent"] = self._store.recent_turns(
                session_id=session_id or self._session_id,
                query=query,
                limit=self._recent_recall_limit,
            )
        if "graph" in lanes or "project" in lanes or "ads" in lanes:
            graph = []
            if self._store:
                for entity in self._store.entity_candidates(query, limit=self._graph_recall_limit):
                    wiki = self._store.entity_wiki(entity, limit=3)
                    if wiki.get("exists"):
                        graph.append(wiki)
            sections["graph"] = graph
        if "project" in lanes and self._store:
            sections["project_chunks"] = self._store.document_search(query, source_type="project", limit=4)
        result["sections"] = sections
        result["context"] = self._format_route_context(sections)
        return result

    def _rag_query(
        self,
        query: str,
        *,
        session_id: str = "",
        limit: int = 8,
        source_type: str | None = None,
        mode: str = "mix",
        max_chars: int = 12000,
    ) -> dict:
        """Native Elevate RAG: retrieve answer-ready context from all memory lanes.

        This is intentionally local and deterministic. It does not call another
        model to synthesize the final answer; it returns grounded context and
        citations so the active agent can answer from retrieved memory.
        """
        query = str(query or "").strip()
        limit = max(1, int(limit or 8))
        mode = str(mode or "mix").strip().lower()
        if mode not in {"local", "global", "hybrid", "naive", "mix"}:
            mode = "mix"
        include_facts = mode in {"local", "hybrid", "mix"}
        include_chunks = mode in {"naive", "hybrid", "mix"}
        include_recent = mode in {"local", "hybrid", "mix"}
        include_graph = mode in {"local", "global", "hybrid", "mix"}
        include_communities = mode in {"global", "hybrid", "mix"}
        sections: dict[str, object] = {}

        communities: list[dict] = []
        if self._store and query and include_communities:
            communities = self._store.search_community_reports(query, limit=min(limit, 6))
        sections["communities"] = communities

        facts: list[dict] = []
        rejected_ids: list[int] = []
        if self._retriever and query and include_facts:
            candidates = self._retriever.search(
                query,
                min_trust=self._min_trust,
                limit=max(limit * 3, limit),
            )
            facts, rejected_ids = self._verify_fact_results(
                query,
                candidates,
                limit=limit,
                session_id=session_id or self._session_id,
            )
        sections["facts"] = facts

        chunks: list[dict] = []
        if self._store and query and include_chunks:
            chunks = self._store.document_search(query, source_type=source_type, limit=limit)
        sections["chunks"] = chunks

        recent: list[dict] = []
        if self._store and query and self._recent_recall_enabled and include_recent:
            recent = self._store.recent_turns(
                session_id=session_id or self._session_id,
                query=query,
                limit=min(limit, self._recent_recall_limit),
                include_assistant=True,
            )
        sections["recent"] = recent

        graph: list[dict] = []
        if self._store and query and self._graph_recall_enabled and include_graph:
            for entity in self._store.entity_candidates(query, limit=min(limit, self._graph_recall_limit)):
                wiki = self._store.entity_wiki(entity, limit=3)
                if wiki.get("exists"):
                    graph.append(wiki)
        sections["graph"] = graph
        sections = self._pack_rag_sections(query, sections, max_chars=max_chars)
        facts = sections.get("facts") if isinstance(sections.get("facts"), list) else []
        chunks = sections.get("chunks") if isinstance(sections.get("chunks"), list) else []
        communities = sections.get("communities") if isinstance(sections.get("communities"), list) else []

        citations: list[dict] = []
        seen_citations: set[tuple[str, str]] = set()
        for fact in facts:
            key = ("fact", str(fact.get("fact_id", "")))
            if key in seen_citations:
                continue
            seen_citations.add(key)
            citations.append({
                "type": "fact",
                "id": fact.get("fact_id"),
                "source_uri": fact.get("source_uri") or "",
                "excerpt": self._clip(fact.get("source_excerpt") or fact.get("content") or "", 220),
            })
        for chunk in chunks:
            key = ("chunk", str(chunk.get("chunk_id", "")))
            if key in seen_citations:
                continue
            seen_citations.add(key)
            citations.append({
                "type": "chunk",
                "id": chunk.get("chunk_id"),
                "source_uri": chunk.get("source_uri") or "",
                "title": chunk.get("title") or "",
                "excerpt": self._clip(chunk.get("source_excerpt") or chunk.get("content") or "", 220),
            })
        for community in communities:
            key = ("community", str(community.get("community_id", "")))
            if key in seen_citations:
                continue
            seen_citations.add(key)
            citations.append({
                "type": "community",
                "id": community.get("community_id"),
                "source_uri": f"community:{community.get('community_id')}",
                "title": community.get("name") or "Community report",
                "excerpt": self._clip(community.get("summary") or "", 220),
            })

        context = self._format_rag_context(query, sections, citations=citations)
        if self._store:
            try:
                self._store.post_retrieval_maintenance(
                    verified_ids=[int(f.get("fact_id")) for f in facts if f.get("fact_id")],
                    rejected_ids=rejected_ids,
                    query=query,
                    session_id=session_id or self._session_id,
                )
                if context:
                    self._record_context_injection(
                        query,
                        context,
                        session_id=session_id or self._session_id,
                        facts=facts,
                        chunks=chunks,
                        source="rag_query",
                    )
            except Exception as exc:
                logger.debug("RAG query maintenance failed: %s", exc)

        return {
            "query": query,
            "mode": mode,
            "sections": sections,
            "citations": citations,
            "context": context,
            "empty": not bool(context.strip()),
        }

    def _pack_rag_sections(self, query: str, sections: dict[str, object], *, max_chars: int = 12000) -> dict[str, object]:
        """Rerank, dedupe, and fit RAG evidence into a deterministic context budget."""
        budget = max(2000, int(max_chars or 12000))
        q_tokens = self._meaningful_tokens(query)

        def text_score(text: str, base: float = 0.0) -> float:
            tokens = self._meaningful_tokens(text)
            overlap = len(q_tokens & tokens) / max(1, len(q_tokens)) if q_tokens else 0.0
            return float(base or 0.0) + overlap

        packed: dict[str, object] = {}
        used = 0

        def reserve(items: list[dict], key: str, id_key: str, text_keys: tuple[str, ...], base_key: str = "score", cap: int = 8) -> None:
            nonlocal used
            seen: set[str] = set()
            ranked = []
            for item in items or []:
                item_id = str(item.get(id_key) or item.get("source_uri") or item.get("name") or item.get("entity") or len(ranked))
                if item_id in seen:
                    continue
                seen.add(item_id)
                text = " ".join(str(item.get(k) or "") for k in text_keys)
                ranked.append((text_score(text, float(item.get(base_key) or item.get("trust_score") or 0.0)), len(text), item))
            ranked.sort(key=lambda row: row[0], reverse=True)
            selected = []
            for _score, text_len, item in ranked[:cap * 2]:
                cost = max(80, min(1800, text_len))
                if selected and used + cost > budget:
                    continue
                selected.append(item)
                used += cost
                if len(selected) >= cap or used >= budget:
                    break
            packed[key] = selected

        communities = sections.get("communities") if isinstance(sections.get("communities"), list) else []
        facts = sections.get("facts") if isinstance(sections.get("facts"), list) else []
        chunks = sections.get("chunks") if isinstance(sections.get("chunks"), list) else []
        recent = sections.get("recent") if isinstance(sections.get("recent"), list) else []
        graph = sections.get("graph") if isinstance(sections.get("graph"), list) else []

        reserve(communities, "communities", "community_id", ("name", "summary", "tags", "entity_names"), cap=6)
        reserve(facts, "facts", "fact_id", ("content", "tags", "category", "source_uri"), base_key="trust_score", cap=8)
        reserve(chunks, "chunks", "chunk_id", ("content", "source_excerpt", "title", "source_uri"), cap=8)
        reserve(recent, "recent", "turn_id", ("user_content", "assistant_content", "session_id"), cap=5)

        # Graph pages are already entity-neighborhood summaries; keep them after text lanes.
        selected_graph = []
        for wiki in graph[:6]:
            fact_text = " ".join(str(f.get("content") or "") for f in wiki.get("facts", [])[:3])
            cost = max(120, min(1200, len(fact_text)))
            if selected_graph and used + cost > budget:
                continue
            selected_graph.append(wiki)
            used += cost
        packed["graph"] = selected_graph
        packed["budget"] = {"max_chars": budget, "estimated_chars": used}
        return packed

    def _format_rag_context(self, query: str, sections: dict[str, object], *, citations: list[dict]) -> str:
        lines = ["## Elevate Native RAG", f"Query: {query}"]

        facts = sections.get("facts") if isinstance(sections.get("facts"), list) else []
        communities = sections.get("communities") if isinstance(sections.get("communities"), list) else []
        if communities:
            lines.append("### Community Reports")
            for community in communities[:6]:
                source = f"community:{community.get('community_id')}"
                score = float(community.get("score", 0.0) or 0.0)
                entities = community.get("entity_names") or ""
                suffix = f" Entities: {self._clip(entities, 160)}" if entities else ""
                lines.append(f"- [{source} score={score:.3f}] {community.get('name')}: {self._clip(community.get('summary', ''), 420)}{suffix}")

        if facts:
            lines.append("### Facts")
            for fact in facts[:8]:
                trust = float(fact.get("trust_score", 0.0) or 0.0)
                source = fact.get("source_uri") or f"fact:{fact.get('fact_id')}"
                lines.append(f"- [{source} trust={trust:.2f}] {self._clip(fact.get('content', ''), 320)}")

        chunks = sections.get("chunks") if isinstance(sections.get("chunks"), list) else []
        if chunks:
            lines.append("### Document Chunks")
            for chunk in chunks[:8]:
                source = chunk.get("source_uri") or f"chunk:{chunk.get('chunk_id')}"
                score = float(chunk.get("score", 0.0) or 0.0)
                lines.append(f"- [{source} score={score:.3f}] {self._clip(chunk.get('content', ''), 420)}")

        recent = sections.get("recent") if isinstance(sections.get("recent"), list) else []
        if recent:
            lines.append("### Recent Turns")
            for turn in recent[:5]:
                label = f"{turn.get('session_day')}, {turn.get('session_id')}"
                text = turn.get("user_content") or ""
                if turn.get("assistant_content"):
                    text = f"User: {text} / Assistant: {turn.get('assistant_content')}"
                lines.append(f"- [{label}] {self._clip(text, 360)}")

        graph = sections.get("graph") if isinstance(sections.get("graph"), list) else []
        if graph:
            lines.append("### Entity Graph")
            for wiki in graph[:6]:
                fact_bits = "; ".join(self._clip(f.get("content", ""), 160) for f in wiki.get("facts", [])[:2])
                related = ", ".join(rel.get("wiki_link", "") for rel in wiki.get("related_entities", [])[:4])
                suffix = f" Related: {related}." if related else ""
                lines.append(f"- {wiki.get('wiki_link') or wiki.get('entity')}: {fact_bits}{suffix}")

        if citations:
            lines.append("### Citations")
            for citation in citations[:12]:
                source = citation.get("source_uri") or citation.get("title") or f"{citation.get('type')}:{citation.get('id')}"
                lines.append(f"- {source}: {citation.get('excerpt', '')}")

        return "\n".join(lines) if len(lines) > 2 else ""

    def _format_route_context(self, sections: dict[str, object]) -> str:
        lines = ["## Elevate Routed Recall"]
        for name, value in sections.items():
            if not value:
                continue
            lines.append(f"### {name}")
            items = value if isinstance(value, list) else []
            for item in items[:8]:
                if isinstance(item, dict):
                    text = item.get("content") or item.get("user_content") or item.get("entity") or str(item)
                    source = item.get("source_uri") or item.get("session_id") or item.get("wiki_link") or ""
                    suffix = f" ({source})" if source else ""
                    lines.append(f"- {self._clip(str(text), 320)}{suffix}")
        return "\n".join(lines) if len(lines) > 1 else ""

    def _import_plaud_archive(self, path: str | None = None, limit: int | None = None) -> dict:
        """Import Plaud transcript JSONL into chunk-level local RAG."""
        if not self._store:
            return {"imported": 0, "chunks": 0}
        archive_path = Path(path or "/Users/dartagnanpatricio/claudeclaw/artifacts/plaud-memory/plaud-transcripts-chronological.jsonl").expanduser()
        if not archive_path.exists():
            return {"imported": 0, "chunks": 0, "error": f"not found: {archive_path}"}
        imported = 0
        chunks_total = 0
        with archive_path.open("r", encoding="utf-8") as f:
            for line in f:
                if limit is not None and imported >= limit:
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    item = json.loads(line)
                except Exception:
                    continue
                transcript = item.get("transcript") or item.get("content") or item.get("text") or ""
                summary = item.get("summary") or ""
                title = item.get("title") or item.get("name") or "Plaud transcript"
                if not transcript and not summary:
                    continue
                source_id = item.get("id") or item.get("recording_id") or item.get("created_at") or title
                source_uri = f"plaud:{source_id}"
                body = f"Title: {title}\nRecorded at: {item.get('recorded_at') or item.get('created_at') or ''}\n\nSummary:\n{summary}\n\nTranscript:\n{transcript}"
                chunks = self._store.chunk_text(body)
                result = self._store.add_document_chunks(
                    source_uri=source_uri,
                    chunks=chunks,
                    title=title,
                    source_type="plaud",
                    metadata={
                        "id": source_id,
                        "recorded_at": item.get("recorded_at"),
                        "created_at": item.get("created_at"),
                        "archive_path": str(archive_path),
                    },
                )
                imported += 1
                chunks_total += int(result.get("chunks", 0))
        return {"imported": imported, "chunks": chunks_total, "path": str(archive_path)}

    # -- Layered recall ------------------------------------------------------

    def _build_layered_context(self, query: str, *, session_id: str = "") -> str:
        if not self._store or not self._retriever:
            return ""
        self._last_layered_facts = []
        self._last_layered_chunks = []

        sections: list[str] = []

        if self._recent_recall_enabled:
            recent = self._store.recent_turns(
                session_id=session_id or self._session_id,
                query=query,
                limit=self._recent_recall_limit,
                include_assistant=False,
            )
            if recent:
                lines = []
                for turn in recent:
                    text = self._clip(turn.get("user_content", ""), self._recent_turn_max_chars)
                    lines.append(
                        f"- ({turn.get('session_day')}, {turn.get('session_id')}) {text}"
                    )
                sections.append("### Recent Session\n" + "\n".join(lines))

        durable_candidates = self._retriever.search(
            query,
            min_trust=self._min_trust,
            limit=max(self._durable_recall_limit * 3, self._durable_recall_limit),
        )
        durable, rejected_ids = self._verify_fact_results(
            query,
            durable_candidates,
            limit=self._durable_recall_limit,
            session_id=session_id or self._session_id,
        )
        if durable:
            self._last_layered_facts = list(durable)
            lines = []
            for fact in durable:
                trust = float(fact.get("trust_score", fact.get("trust", 0.0)) or 0.0)
                category = fact.get("category", "general")
                lines.append(
                    f"- [{category} trust={trust:.2f}] {self._clip(fact.get('content', ''), 320)}"
                )
            sections.append("### Durable + Semantic\n" + "\n".join(lines))
        if self._store:
            self._store.post_retrieval_maintenance(
                verified_ids=[int(f.get("fact_id")) for f in durable if f.get("fact_id")],
                rejected_ids=rejected_ids,
                query=query,
                session_id=session_id or self._session_id,
            )

        document_chunks = self._store.document_search(query, limit=self._durable_recall_limit)
        if document_chunks:
            self._last_layered_chunks = list(document_chunks)
            lines = []
            for chunk in document_chunks[: self._durable_recall_limit]:
                source = chunk.get("source_uri") or f"chunk:{chunk.get('chunk_id')}"
                score = float(chunk.get("score", 0.0) or 0.0)
                lines.append(
                    f"- [{source} score={score:.3f}] {self._clip(chunk.get('content', ''), 360)}"
                )
            sections.append("### Document RAG\n" + "\n".join(lines))

        if self._graph_recall_enabled:
            graph_lines = []
            injected_ids = self._store.injected_memory_ids(session_id or self._session_id).get("fact_ids", set())
            for entity in self._store.entity_candidates(query, limit=self._graph_recall_limit):
                wiki = self._store.entity_wiki(entity, limit=3)
                if not wiki.get("exists"):
                    continue
                related = ", ".join(
                    rel["wiki_link"] for rel in wiki.get("related_entities", [])[:4]
                )
                fact_bits = [
                    self._clip(f.get("content", ""), 180)
                    for f in wiki.get("facts", [])[:2]
                    if int(f.get("fact_id") or 0) not in injected_ids
                ]
                if not fact_bits:
                    continue
                suffix = f" Related: {related}." if related else ""
                graph_lines.append(
                    f"- {wiki.get('wiki_link')}: {'; '.join(fact_bits)}.{suffix}"
                )
            if graph_lines:
                sections.append("### Graph Wiki\n" + "\n".join(graph_lines))

        if not sections:
            return ""
        return "## Elevate Memory Core\n" + "\n\n".join(sections)

    # -- Turn-journal organization / auto-extraction -------------------------

    def _organize_journal(
        self,
        session_id: str | None = None,
        session_day: str | None = None,
        limit: int | None = None,
    ) -> dict:
        if not self._store:
            return {"processed": 0, "promoted": 0, "pending": 0}

        scoped_session = session_id or None
        scoped_day = session_day or None
        batch_limit = limit if limit is not None else self._organize_batch_limit
        rows = self._store.pending_turns(
            session_id=scoped_session,
            session_day=scoped_day,
            limit=batch_limit,
        )
        memory_activity.record_event(
            "memory.organize.started",
            message=f"organizing {len(rows)} pending turn(s)",
            state="maintaining",
            step="maintain",
            status="running",
            data={"session_id": scoped_session, "session_day": scoped_day, "limit": batch_limit},
        )
        processed = 0
        promoted = 0

        for row in rows:
            row_promoted = 0
            for fact in self._extract_fact_candidates(row.get("user_content", "")):
                try:
                    self._store.add_fact(
                        fact["content"],
                        category=fact["category"],
                        tags=fact["tags"],
                    )
                    row_promoted += 1
                except Exception as exc:
                    logger.debug("Journal fact promotion failed: %s", exc)
            try:
                self._store.mark_turn_processed(row["turn_id"], row_promoted)
            except Exception as exc:
                logger.debug("Journal mark-processed failed: %s", exc)
            processed += 1
            promoted += row_promoted

        status = self._store.journal_status(
            session_id=scoped_session,
            session_day=scoped_day,
        )
        memory_activity.record_event(
            "memory.organize.complete",
            message=f"processed {processed}, promoted {promoted}",
            state="idle",
            step="maintain",
            status="done",
            data={"processed": processed, "promoted": promoted, "pending": status.get("pending", 0)},
        )
        return {
            "processed": processed,
            "promoted": promoted,
            "pending": status.get("pending", 0),
            "total": status.get("total", 0),
        }

    def _auto_extract_facts(self, messages: list) -> None:
        extracted = 0
        for msg in messages:
            if msg.get("role") != "user":
                continue
            content = msg.get("content", "")
            for fact in self._extract_fact_candidates(content):
                try:
                    self._store.add_fact(
                        fact["content"],
                        category=fact["category"],
                        tags=fact["tags"],
                    )
                    extracted += 1
                except Exception:
                    pass

        if extracted:
            logger.info("Auto-extracted %d facts from conversation", extracted)

    def _extract_fact_candidates(self, content: str) -> list[dict]:
        if not isinstance(content, str) or len(content.strip()) < 10:
            return []

        text = " ".join(content.strip().split())
        candidates: list[dict] = []
        seen: set[tuple[str, str]] = set()

        def add(raw: str, category: str, tags: str) -> None:
            fact = self._clean_fact_text(raw)
            if len(fact) < 8:
                return
            key = (fact.lower(), category)
            if key in seen:
                return
            seen.add(key)
            candidates.append({
                "content": fact,
                "category": category,
                "tags": tags,
            })

        sentence_end = r"(?:[.!?](?:\s|$)|$)"
        explicit_patterns = [
            re.compile(
                rf"\b(?:remember(?: this| that)?|note(?: this)?|save this|store this)"
                rf"(?:\s+for\s+later)?\s*[:\-]\s*(.+?){sentence_end}",
                re.IGNORECASE,
            ),
            re.compile(
                rf"\bremember\s+(?!(?:this|that)\s*:)(?:this\s+|that\s+)?(.+?){sentence_end}",
                re.IGNORECASE,
            ),
        ]
        for pattern in explicit_patterns:
            for match in pattern.finditer(text):
                add(match.group(1), "general", "auto,journal,explicit")

        preference_verbs = {
            "prefer": "prefers",
            "like": "likes",
            "love": "loves",
            "use": "uses",
            "want": "wants",
            "need": "needs",
        }
        pref_pattern = re.compile(
            rf"\bI\s+(prefer|like|love|use|want|need)\s+(.+?){sentence_end}",
            re.IGNORECASE,
        )
        for match in pref_pattern.finditer(text):
            verb = preference_verbs.get(match.group(1).lower(), match.group(1).lower())
            add(f"User {verb} {match.group(2)}", "user_pref", "auto,journal,preference")

        my_pattern = re.compile(
            rf"\bmy\s+(favorite|preferred|default)\s+(.+?)\s+is\s+(.+?){sentence_end}",
            re.IGNORECASE,
        )
        for match in my_pattern.finditer(text):
            add(
                f"User's {match.group(1).lower()} {match.group(2)} is {match.group(3)}",
                "user_pref",
                "auto,journal,preference",
            )

        habit_pattern = re.compile(
            rf"\bI\s+(always|never|usually)\s+(.+?){sentence_end}",
            re.IGNORECASE,
        )
        for match in habit_pattern.finditer(text):
            add(
                f"User {match.group(1).lower()} {match.group(2)}",
                "user_pref",
                "auto,journal,preference",
            )

        decision_pattern = re.compile(
            rf"\bwe\s+(decided|agreed|chose)\s+(?:to\s+)?(.+?){sentence_end}",
            re.IGNORECASE,
        )
        for match in decision_pattern.finditer(text):
            add(
                f"Project decision: we {match.group(1).lower()} to {match.group(2)}",
                "project",
                "auto,journal,decision",
            )

        project_pattern = re.compile(
            rf"\bthe\s+project\s+(uses|needs|requires)\s+(.+?){sentence_end}",
            re.IGNORECASE,
        )
        for match in project_pattern.finditer(text):
            add(
                f"Project {match.group(1).lower()} {match.group(2)}",
                "project",
                "auto,journal,project",
            )

        agent_pattern = re.compile(
            rf"\b(?:this|the|elevate)\s+agent\s+(uses|needs|requires|should)\s+(.+?){sentence_end}",
            re.IGNORECASE,
        )
        for match in agent_pattern.finditer(text):
            add(
                f"Elevate agent {match.group(1).lower()} {match.group(2)}",
                "project",
                "auto,journal,agent",
            )

        return candidates

    @staticmethod
    def _clean_fact_text(text: str, max_chars: int = 400) -> str:
        cleaned = " ".join(str(text or "").strip().strip("\"'` ").split())
        if len(cleaned) <= max_chars:
            return cleaned
        return cleaned[:max_chars].rstrip() + "..."

    @staticmethod
    def _cache_key(query: str, *, session_id: str = "") -> str:
        return f"{session_id}::{' '.join(str(query or '').lower().split())[:500]}"

    @staticmethod
    def _clip(text: str, max_chars: int) -> str:
        clean = " ".join(str(text or "").strip().split())
        if len(clean) <= max_chars:
            return clean
        return clean[:max_chars].rstrip() + "..."


# ---------------------------------------------------------------------------
# Plugin entry point
# ---------------------------------------------------------------------------

def register(ctx) -> None:
    """Register the holographic memory provider with the plugin system."""
    config = _load_plugin_config()
    provider = HolographicMemoryProvider(config=config)
    ctx.register_memory_provider(provider)
