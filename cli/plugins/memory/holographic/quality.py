"""Write-time quality gate for the holographic fact store.

Pure-rules (NO LLM) heuristics used by ``store.MemoryStore`` as the single
choke point every fact write flows through:

- ``classify_fact_durability(content)`` — ``durable`` vs ``ephemeral``.
  Ephemeral = one-off task chatter ("User wants to just run a test"),
  placeholder content ("a skill for X"), present-progressive task framing
  with no proper nouns / paths / values / conventions to anchor it.
  Durable = conventions/rules, verified values (paths, URLs, ids, prices),
  scoped preferences, corrections.
- ``is_entity_skippable(name)`` / ``entity_mint_allowed(name)`` — entity
  minting throttle helpers for the extraction path.

Everything here is deterministic and cheap enough for the per-write hot path.
"""

from __future__ import annotations

import re

__all__ = [
    "EphemeralFactSkipped",
    "classify_fact_durability",
    "is_entity_skippable",
    "entity_mint_allowed",
    "normalize_for_dedup",
    "key_tokens",
    "token_jaccard",
]


class EphemeralFactSkipped(ValueError):
    """Raised by the write gate when a non-explicit ephemeral candidate is refused."""


# ---------------------------------------------------------------------------
# Ephemeral signals
# ---------------------------------------------------------------------------

# Leading one-off task framing: "User wants/needs/asked/is asking ..."
_TASK_LEAD_RE = re.compile(
    r"^(?:the\s+)?user\s+"
    r"(?:just\s+)?(?:wants?|needs?|asked|asks|is\s+asking|would\s+like|"
    r"is\s+trying|tried|requested|told\s+me)\b",
    re.IGNORECASE,
)

# Present-progressive task framing: "User is testing/debugging/working on ..."
_PROGRESSIVE_RE = re.compile(
    r"^(?:the\s+)?user\s+is\s+(?:currently\s+)?\w+ing\b", re.IGNORECASE
)

# One-off task verbs that typically follow the task framing.
_ONEOFF_VERB_RE = re.compile(
    r"\b(?:to\s+)?(?:just\s+)?"
    r"(run|test|try|check|make|create|build|fix|see|look|debug|verify|"
    r"write|generate|draft|send|do|finish|update|restart|deploy)\b",
    re.IGNORECASE,
)

# Placeholder content: "for X", "a test", trailing single letters, "something".
_PLACEHOLDER_RES = [
    re.compile(r"\bfor\s+[XYZ]\b"),
    re.compile(r"\ba\s+test\b", re.IGNORECASE),
    re.compile(r"\bsomething\b\s*\.?$", re.IGNORECASE),
    re.compile(r"\b[XYZ]\b\s*\.?$"),
    re.compile(r"\bplaceholder\b", re.IGNORECASE),
    re.compile(r"\bthis\s+thing\b", re.IGNORECASE),
]

# ---------------------------------------------------------------------------
# Durable signals
# ---------------------------------------------------------------------------

# Conventions / rules / policies.
_CONVENTION_RE = re.compile(
    r"\b(should|must|never|always|convention|policy|rule|standard|"
    r"do\s+not|don'?t|required|forbidden|banned|only\s+use)\b",
    re.IGNORECASE,
)

# Durable preference / habit verbs (vs one-off "wants").
_PREFERENCE_RE = re.compile(
    r"\buser(?:'s)?\s+(?:prefers?|likes?|loves?|hates?|dislikes?|uses|"
    r"always|never|usually|default|favorite|preferred)\b",
    re.IGNORECASE,
)

# Corrections supersede something — high durability.
_CORRECTION_RE = re.compile(
    r"\b(actually|correction|corrected|instead\s+of|rather\s+than|"
    r"renamed\s+to|moved\s+to|no\s+longer|not\s+\w+[,;]\s)\b",
    re.IGNORECASE,
)

# Compliance / legal / filing language — narrow, high-stakes. These are the
# rules a model must never silently forget (signatures, disclosures, accepted
# offers, the contract of purchase and sale). Deliberately conservative: only
# clear compliance terms fire it, never generic workflow words.
_COMPLIANCE_RE = re.compile(
    r"\b(signatures?|initials?|disclosures?|compliance|"
    r"accepted\s+offer|cps|contract\s+of\s+purchase|filing|"
    r"seller-?\s?side|buyer-?\s?side)\b",
    re.IGNORECASE,
)

# Verified values: filesystem paths, URLs, emails, money, versions, ports,
# long hex ids, key:value config fragments.
_VALUE_RES = [
    re.compile(r"(?:^|[\s\"'`(=])(?:~?/|[A-Za-z]:\\)[\w.\-/\\~]+"),  # paths
    re.compile(r"https?://\S+"),                                      # urls
    re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.]+\b"),                      # emails
    re.compile(r"[$€£]\s?\d"),                                        # money
    re.compile(r"\bv?\d+\.\d+(?:\.\d+)?\b"),                          # versions
    re.compile(r":\d{2,5}\b"),                                        # ports
    re.compile(r"\b[a-f0-9]{8,}\b"),                                  # hex ids
    re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b"),                       # IPs
]

# Identifier-ish tokens (snake/kebab/dotted) signal concrete, durable content.
_IDENTIFIER_RE = re.compile(r"\b[A-Za-z][A-Za-z0-9]*(?:[._-][A-Za-z0-9]+)+\b")

# Proper nouns (capitalized words/phrases); matches at sentence starts are
# filtered out in ``_proper_nouns`` so sentence case doesn't count.
_PROPER_NOUN_RE = re.compile(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\b")


def _proper_nouns(text: str) -> list[str]:
    """Capitalized words/phrases that are NOT just sentence-initial casing."""
    found: list[str] = []
    for m in _PROPER_NOUN_RE.finditer(text):
        start = m.start()
        if start == 0:
            continue
        prefix = text[:start].rstrip()
        if prefix and prefix[-1] in ".!?:":
            continue
        found.append(m.group(0))
    return found

# Scoped preference: "for Skyleigh CMAs", "for HPA emails".
_SCOPE_RE = re.compile(r"\bfor\s+[A-Z][A-Za-z0-9]+")


def classify_fact_durability(content: str) -> dict:
    """Classify a candidate fact as ``durable`` or ``ephemeral``.

    Pure rules, no LLM. Returns::

        {
          "durability": "durable" | "ephemeral",
          "confidence": float,        # 0..1
          "task_framed": bool,        # task-shaped framing detected
          "signals": [str, ...],      # matched rule names (audit/debug)
        }

    Conservative bias: with no signals either way the result is ``durable``
    at low confidence — the gate only refuses clearly task-shaped chatter.

    Additionally returns ``critical`` (bool) + ``critical_reason`` (str). A
    fact is marked critical ONLY for clear-cut cases — a correction, an
    explicit convention/rule, or compliance/legal/filing language — never for
    generic workflow content. ``critical_reason`` names the firing signal
    (``correction`` | ``convention`` | ``compliance``).
    """
    text = " ".join(str(content or "").strip().split())
    signals: list[str] = []
    ephemeral_score = 0.0
    durable_score = 0.0

    task_lead = bool(_TASK_LEAD_RE.search(text))
    progressive = bool(_PROGRESSIVE_RE.search(text))
    task_framed = task_lead or progressive

    if task_lead:
        ephemeral_score += 2.0
        signals.append("task_lead")
        if _ONEOFF_VERB_RE.search(text):
            ephemeral_score += 1.0
            signals.append("oneoff_verb")
        if re.search(r"\bjust\b", text, re.IGNORECASE):
            ephemeral_score += 0.5
            signals.append("just")
    if progressive and not task_lead:
        ephemeral_score += 1.5
        signals.append("progressive_task")

    placeholder = any(p.search(text) for p in _PLACEHOLDER_RES)
    if placeholder:
        ephemeral_score += 2.0
        signals.append("placeholder")

    is_convention = bool(_CONVENTION_RE.search(text))
    is_correction = bool(_CORRECTION_RE.search(text))
    is_compliance = bool(_COMPLIANCE_RE.search(text))
    if is_convention:
        durable_score += 2.0
        signals.append("convention")
    if _PREFERENCE_RE.search(text):
        durable_score += 2.0
        signals.append("preference")
    if is_correction:
        durable_score += 2.0
        signals.append("correction")
    if is_compliance:
        durable_score += 1.5
        signals.append("compliance")
    if _SCOPE_RE.search(text):
        durable_score += 1.0
        signals.append("scoped")

    value_hits = sum(1 for p in _VALUE_RES if p.search(text))
    if value_hits:
        durable_score += min(2.0, 1.0 * value_hits)
        signals.append("value")

    if _IDENTIFIER_RE.search(text):
        durable_score += 0.5
        signals.append("identifier")

    proper = _proper_nouns(text)
    # Filter pronoun-ish noise.
    proper = [p for p in proper if p.lower() not in ("i", "user", "the", "a")]
    if proper:
        durable_score += min(1.5, 0.75 * len(proper))
        signals.append("proper_noun")
    elif task_framed and value_hits == 0:
        # Task framing AND nothing concrete to anchor on — extra ephemeral.
        ephemeral_score += 1.0
        signals.append("no_anchor")

    if ephemeral_score > durable_score:
        durability = "ephemeral"
        winner, total = ephemeral_score, ephemeral_score + durable_score
    else:
        durability = "durable"
        winner, total = durable_score, ephemeral_score + durable_score

    confidence = round(winner / total, 3) if total > 0 else 0.5

    # Critical tier — clear-cut, RARE only. v1 auto-critical = correction OR
    # compliance, precedence correction > compliance (a correction is the
    # strongest "you got this wrong, remember it" signal). Conventions
    # (should/must/never/always/policy/rule) are deliberately NOT auto-critical:
    # on real corpora they are far too common (~25% of facts) and would dilute
    # the reserved Must-Follow lane back toward the starvation problem. A
    # convention still scores durable + keeps its "convention" signal; making
    # one "must-always" requires a future deliberate pin action. Never critical
    # when the fact reads as task chatter (ephemeral).
    critical = False
    critical_reason = ""
    if durability == "durable":
        if is_correction:
            critical, critical_reason = True, "correction"
        elif is_compliance:
            critical, critical_reason = True, "compliance"

    return {
        "durability": durability,
        "confidence": confidence,
        "task_framed": task_framed,
        "signals": signals,
        "critical": critical,
        "critical_reason": critical_reason,
    }


# ---------------------------------------------------------------------------
# Entity minting throttle helpers
# ---------------------------------------------------------------------------

def is_entity_skippable(name: str, stopwords: set[str] | frozenset[str] = frozenset()) -> bool:
    """Hard skip: single-character or stopword entity candidates."""
    stripped = str(name or "").strip()
    if len(stripped) < 2:
        return True
    return stripped.lower() in stopwords


def entity_mint_allowed(name: str) -> bool:
    """Proper-noun-likeness test used to gate NEW entity rows during
    extraction passes. Existing entities always resolve regardless.

    Allowed: capitalized words/phrases, quoted-style mixed case, identifiers
    (dotted/snake/kebab), tokens with digits, and path/URL-ish strings.
    Denied: bare lowercase prose tokens (those need >=2-fact corroboration,
    checked separately against the store).
    """
    stripped = str(name or "").strip()
    if not stripped:
        return False
    if stripped[0].isupper():
        return True
    if any(ch.isdigit() for ch in stripped):
        return True
    if re.search(r"[._/\\:-]", stripped):
        return True
    # Multi-word lowercase phrases (quoted terms) get a pass — they were
    # deliberately quoted/captured, unlike bare salient-token fallbacks.
    if " " in stripped:
        return True
    return False


# ---------------------------------------------------------------------------
# Dedup helpers
# ---------------------------------------------------------------------------

_NORM_RE = re.compile(r"[^a-z0-9 ]+")

_DEDUP_STOPWORDS = frozenset(
    "a an and are as at be by for from has have in is it of on or that the "
    "this to use uses user with should never always".split()
)


def normalize_for_dedup(text: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace."""
    lowered = str(text or "").lower()
    return " ".join(_NORM_RE.sub(" ", lowered).split())


def key_tokens(text: str) -> set[str]:
    """Salient (non-stopword) tokens used for containment/Jaccard checks."""
    return {
        t for t in normalize_for_dedup(text).split()
        if len(t) >= 3 and t not in _DEDUP_STOPWORDS
    }


def token_jaccard(a: str, b: str) -> float:
    """Jaccard similarity over salient tokens (cheap no-embedding fallback)."""
    ta, tb = key_tokens(a), key_tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)
