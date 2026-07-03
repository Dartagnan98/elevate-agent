---
name: polymarket
description: "Query Polymarket prediction-market data — markets, prices, orderbooks, history. Use when the user names 'Polymarket', asks 'what are the odds of X', wants betting odds or event probabilities, or wants to track a market's price movement. Not for general news or web research on the event itself — use agent-ops/web-research; not for academic sources — use research/arxiv. Read-only via public REST APIs, no key."
version: 1.0.0
author: Elevate + Teknium
tags: [polymarket, prediction-markets, market-data, trading]
---

# Polymarket — Prediction Market Data

Query prediction market data from Polymarket using their public REST APIs.
All endpoints are read-only and require zero authentication.

See `references/api-endpoints.md` for the full endpoint reference with curl examples.

## When to Use

- User asks about prediction markets, betting odds, or event probabilities
- User wants to know "what are the odds of X happening?"
- User asks about Polymarket specifically
- User wants market prices, orderbook data, or price history
- User asks to monitor or track prediction market movements

## Key Concepts

- **Events** contain one or more **Markets** (1:many relationship)
- **Markets** are binary outcomes with Yes/No prices between 0.00 and 1.00
- Prices ARE probabilities: price 0.65 means the market thinks 65% likely
- `outcomePrices` field: JSON-encoded array like `["0.80", "0.20"]`
- `clobTokenIds` field: JSON-encoded array of two token IDs [Yes, No] for price/book queries
- `conditionId` field: hex string used for price history queries
- Volume is in USDC (US dollars)

## Three Public APIs

1. **Gamma API** at `gamma-api.polymarket.com` — Discovery, search, browsing
2. **CLOB API** at `clob.polymarket.com` — Real-time prices, orderbooks, history
3. **Data API** at `data-api.polymarket.com` — Trades, open interest

## Typical Workflow

When a user asks about prediction market odds:

1. **Search** using the Gamma API public-search endpoint with their query
2. **Parse** the response — extract events and their nested markets
3. **Present** market question, current prices as percentages, and volume
4. **Deep dive** if asked — use clobTokenIds for orderbook, conditionId for history

## Presenting Results

Format prices as percentages for readability:
- outcomePrices `["0.652", "0.348"]` becomes "Yes: 65.2%, No: 34.8%"
- Always show the market question and probability
- Include volume when available

Example: `"Will X happen?" — 65.2% Yes ($1.2M volume)`

## Parsing Double-Encoded Fields

The Gamma API returns `outcomePrices`, `outcomes`, and `clobTokenIds` as JSON strings
inside JSON responses (double-encoded). When processing with Python, parse them with
`json.loads(market['outcomePrices'])` to get the actual array.

## Rate Limits

Generous — unlikely to hit for normal usage:
- Gamma: 4,000 requests per 10 seconds (general)
- CLOB: 9,000 requests per 10 seconds (general)
- Data: 1,000 requests per 10 seconds (general)

## Limitations

- This skill is read-only — it does not support placing trades
- Trading requires wallet-based crypto authentication (EIP-712 signatures)
- Some new markets may have empty price history
- Geographic restrictions apply to trading but read-only data is globally accessible

## Search doctrine

- Internal first: possessives and client or deal names ("my listing", "the Hendersons", "that Kamloops buyer") mean CRM, deals, threads, and memory BEFORE any web search. The web is for the outside world; this box already knows the inside one.
- Queries are 1-6 words. Start broad, then narrow with one qualifier at a time. Never rerun a near-identical query — if results repeat, change the angle or the tool, not the phrasing.
- Search results are pointers, not sources. Fetch the full page before citing or acting on anything that matters.
- Scale effort to the ask: a single fact is 1 call; a comparison or survey is 3-5; a deep dive is 5-10 with cross-source triangulation. Stop when new results only repeat what you already have.
