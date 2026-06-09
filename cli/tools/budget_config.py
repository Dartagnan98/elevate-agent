"""Configurable budget constants for tool result persistence.

Per-tool resolution: pinned > config overrides > registry > default.
"""

from dataclasses import dataclass, field
from typing import Dict

# Tools whose thresholds must never be overridden.
# read_file=inf prevents infinite persist->read->persist loops.
PINNED_THRESHOLDS: Dict[str, float] = {
    "read_file": float("inf"),
}

# Conservative defaults for non-pinned tool results. High-volume tools can
# still opt into explicit registry caps; read_file remains pinned separately.
DEFAULT_RESULT_SIZE_CHARS: int = 40_000
DEFAULT_TURN_BUDGET_CHARS: int = 80_000
DEFAULT_PREVIEW_SIZE_CHARS: int = 1_500


@dataclass(frozen=True)
class BudgetConfig:
    """Immutable budget constants for the 3-layer tool result persistence system.

    Layer 2 (per-result): resolve_threshold(tool_name) -> threshold in chars.
    Layer 3 (per-turn):   turn_budget -> aggregate char budget across all tool
                          results in a single assistant turn.
    Preview:              preview_size -> inline snippet size after persistence.
    """

    default_result_size: int = DEFAULT_RESULT_SIZE_CHARS
    turn_budget: int = DEFAULT_TURN_BUDGET_CHARS
    preview_size: int = DEFAULT_PREVIEW_SIZE_CHARS
    tool_overrides: Dict[str, int] = field(default_factory=dict)

    def resolve_threshold(self, tool_name: str) -> int | float:
        """Resolve the persistence threshold for a tool.

        Priority: pinned -> tool_overrides -> registry per-tool -> default.
        """
        if tool_name in PINNED_THRESHOLDS:
            return PINNED_THRESHOLDS[tool_name]
        if tool_name in self.tool_overrides:
            return self.tool_overrides[tool_name]
        from tools.registry import registry
        return registry.get_max_result_size(tool_name, default=self.default_result_size)


DEFAULT_BUDGET = BudgetConfig()

# Memo for budget_for_context_length — tiny domain, avoid re-allocating.
_CTX_BUDGET_CACHE: Dict[int, BudgetConfig] = {}


def budget_for_context_length(context_length: int | None) -> BudgetConfig:
    """Scale the per-turn tool-result budget with the model's context window.

    The flat 80K-char default is ~10% of a 200K-token window (chars/4). On
    1M-context models it spills results to disk long before context pressure
    is real; on 64K models it lets a single turn eat a third of the window.
    Scale to ~10% of the window, clamped to [32K, 400K] chars. Per-result
    thresholds (Layer 2) are unchanged — only the aggregate turn budget moves.
    """
    if not context_length or context_length <= 0:
        return DEFAULT_BUDGET
    turn = max(32_000, min(400_000, int(context_length * 0.10) * 4))
    if turn == DEFAULT_TURN_BUDGET_CHARS:
        return DEFAULT_BUDGET
    cached = _CTX_BUDGET_CACHE.get(turn)
    if cached is None:
        cached = BudgetConfig(turn_budget=turn)
        _CTX_BUDGET_CACHE[turn] = cached
    return cached
