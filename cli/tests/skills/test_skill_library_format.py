"""Skill-library format lint — keeps descriptions routable and doctrine in sync.

Descriptions are the routing surface, truncated to 60/180/1024 chars by three
consumers. This test enforces the trigger-first format from
``docs/skill-doctrine.md`` so the discriminating signal survives every cut, and
byte-compares the shared doctrine blocks against their canonical source so a
block edited in one skill (instead of in the doctrine file) fails loudly.

Content-only lint; it never judges prose quality. Parses with the production
frontmatter parser so it agrees with the runtime.
"""
import pathlib
import re

import pytest

from tools.skills_tool import _parse_frontmatter

CLI_ROOT = pathlib.Path(__file__).resolve().parents[2]
SKILLS_DIR = CLI_ROOT / "skills"
DOCTRINE = CLI_ROOT / "docs" / "skill-doctrine.md"

# Frozen: frontmatter name != directory name. These carry a sync-manifest cost
# to rename and no loadout references them. Compared with == so the set cannot
# silently grow (a NEW mismatch is a bug, not a new exception).
ALLOWED_NAME_MISMATCHES = {
    "lm-evaluation-harness": "evaluating-llms-harness",
    "vllm": "serving-llms-vllm",
    "audiocraft": "audiocraft-audio-generation",
    "segment-anything": "segment-anything-model",
    "trl-fine-tuning": "fine-tuning-with-trl",
}

TRIGGER_RE = re.compile(r"\bUse (when|whenever|for|it|this)\b", re.IGNORECASE)
ANTI_RE = re.compile(r"\b(Not for|Do NOT use|Don't use)\b", re.IGNORECASE)

MAX_DESC = 950
MAX_FRONTMATTER_BYTES = 3500
TRIGGER_MUST_START_BY = 120
MAX_FIRST_SENTENCE = 90


def _skill_files():
    files = []
    for p in sorted(SKILLS_DIR.glob("**/SKILL.md")):
        if "optional-skills" in p.parts:
            continue
        files.append(p)
    return files


def _rel(p: pathlib.Path) -> str:
    return str(p.relative_to(SKILLS_DIR).parent)


def _frontmatter_bytes(text: str) -> int:
    # The runtime reads the first 4000 bytes; the fenced frontmatter must fit.
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            return len(text[: end + 4].encode("utf-8"))
    return 0


ALL_SKILLS = _skill_files()


@pytest.mark.parametrize("path", ALL_SKILLS, ids=_rel)
def test_skill_description_format(path):
    text = path.read_text(encoding="utf-8")
    fm, _ = _parse_frontmatter(text)
    assert fm, f"{_rel(path)}: no parseable frontmatter"

    name = str(fm.get("name") or "").strip()
    dirname = path.parent.name
    if name != dirname:
        assert ALLOWED_NAME_MISMATCHES.get(dirname) == name, (
            f"{_rel(path)}: frontmatter name {name!r} != dir {dirname!r} "
            f"and not a frozen exception"
        )

    desc = str(fm.get("description") or "").strip()
    assert desc, f"{_rel(path)}: empty description"
    assert len(desc) <= MAX_DESC, f"{_rel(path)}: description {len(desc)} > {MAX_DESC}"

    fb = _frontmatter_bytes(text)
    assert fb <= MAX_FRONTMATTER_BYTES, (
        f"{_rel(path)}: frontmatter {fb} bytes > {MAX_FRONTMATTER_BYTES}"
    )

    m = TRIGGER_RE.search(desc)
    assert m, f"{_rel(path)}: description has no 'Use when/for/...' trigger clause"
    assert m.start() < TRIGGER_MUST_START_BY, (
        f"{_rel(path)}: trigger clause starts at char {m.start()} "
        f"(must be < {TRIGGER_MUST_START_BY} to survive the 180-char cron cut)"
    )

    first_sentence = re.split(r"(?<=[.!?])\s", desc, maxsplit=1)[0]
    assert len(first_sentence) <= MAX_FIRST_SENTENCE, (
        f"{_rel(path)}: first sentence {len(first_sentence)} > {MAX_FIRST_SENTENCE} "
        f"chars (Zone A must stay legible at the 60-char cut)"
    )

    anti = ANTI_RE.search(desc)
    if anti:
        assert anti.start() > m.start(), (
            f"{_rel(path)}: anti-trigger appears before the trigger clause"
        )


# --- Doctrine block parity ---------------------------------------------------

def _canonical_blocks():
    text = DOCTRINE.read_text(encoding="utf-8")
    blocks = {}
    for mm in re.finditer(r"## BLOCK: (\S+).*?```markdown\n(.*?)\n```", text, re.DOTALL):
        blocks[mm.group(1)] = mm.group(2).rstrip("\n")
    return blocks


DOCTRINE_TARGETS = {
    "search-doctrine": [
        "research/arxiv", "research/blogwatcher", "research/llm-wiki",
        "research/polymarket", "research/research-paper-writing",
        "agent-ops/web-research", "agent-ops/autoresearch",
        "agent-ops/source-collection", "agent-ops/signal-scoring",
        "real-estate-admin/market-stats-watcher",
    ],
    "fair-housing": [
        "real-estate-admin/marketing", "real-estate-admin/listing-outreach",
        "real-estate-admin/listing-build", "real-estate-admin/marketing-landing",
        "real-estate-admin/seller-updates", "real-estate-admin/outreach",
        "real-estate-admin/relisting", "social-content-engine",
        "social-media/xurl", "outreach-lanes", "lead-scorer",
        "creative/creative-ideation",
    ],
    "provenance": [
        "cma", "real-estate-admin/cma-generator",
        "real-estate-admin/market-stats-watcher", "real-estate-admin/deal-matcher",
        "real-estate-admin/property-lookup", "real-estate-admin/offer-review",
        "real-estate-admin/seller-package", "real-estate-admin/closing-admin",
    ],
}

_PARITY_CASES = [
    (block, target)
    for block, targets in DOCTRINE_TARGETS.items()
    for target in targets
]


@pytest.mark.parametrize("block,target", _PARITY_CASES, ids=lambda v: v)
def test_doctrine_block_parity(block, target):
    canonical = _canonical_blocks()[block]
    path = SKILLS_DIR / target / "SKILL.md"
    body = path.read_text(encoding="utf-8")
    # Whitespace-normalized line compare — the block must appear verbatim.
    want = [ln.rstrip() for ln in canonical.splitlines()]
    hay = [ln.rstrip() for ln in body.splitlines()]
    heading = want[0]
    assert heading in hay, (
        f"{target}: missing doctrine block {block!r} "
        f"(edit docs/skill-doctrine.md and re-paste everywhere)"
    )
    start = hay.index(heading)
    assert hay[start : start + len(want)] == want, (
        f"{target}: doctrine block {block!r} drifted from canonical "
        f"(edit docs/skill-doctrine.md and re-paste everywhere)"
    )
