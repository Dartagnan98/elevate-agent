---
name: web-research
description: "Structured web research — sub-query search, content extraction, cited synthesis. Use when the user asks to 'research', 'look up', 'find sources on', or 'summarize what's online about' a topic and the answer lives on the open web. Not for hypothesis-driven metric iteration — use autoresearch; not for extracting from an API-less site's logged-in session — use opencli."
homepage: https://docs.anthropic.com/en/docs/build-with-claude/tool-use
tags: [research, web, search, analysis]
category: agent-ops
---


# Web Research

Patterns for agents performing structured web research.

## Search Strategy
1. Break the research question into sub-queries
2. Search each sub-query independently
3. Extract relevant content from top results
4. Synthesize findings with source attribution

## Search Tools
Use WebSearch for broad queries, WebFetch for specific URLs:
```
WebSearch: "AI agent orchestration best practices 2026"
WebFetch: "https://docs.anthropic.com/en/docs/agents"
```

## Content Extraction
- Extract key facts, quotes, and data points
- Note the source URL for each finding
- Check publication dates for freshness
- Cross-reference claims across multiple sources

## Research Output Format
```markdown
## Finding: [Topic]
**Source:** [URL]
**Date:** [Publication date]
**Key points:**
- Point 1
- Point 2

**Relevance:** [How this relates to the research question]
```

## Best Practices
- Always attribute sources
- Prefer primary sources over secondary
- Check for recency (information may be outdated)
- Synthesize, don't just aggregate
- Flag conflicting information explicitly

## Search doctrine

- Internal first: possessives and client or deal names ("my listing", "the Hendersons", "that Kamloops buyer") mean CRM, deals, threads, and memory BEFORE any web search. The web is for the outside world; this box already knows the inside one.
- Queries are 1-6 words. Start broad, then narrow with one qualifier at a time. Never rerun a near-identical query — if results repeat, change the angle or the tool, not the phrasing.
- Search results are pointers, not sources. Fetch the full page before citing or acting on anything that matters.
- Scale effort to the ask: a single fact is 1 call; a comparison or survey is 3-5; a deep dive is 5-10 with cross-source triangulation. Stop when new results only repeat what you already have.
