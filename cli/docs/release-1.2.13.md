# Elevate 1.2.13 — release notes

Your agents can do a lot more out of the box.

## What's new

- **Every agent now has the full working toolkit.** Until now agents only had
  data/coordination tools — so they couldn't browse the web, control the
  computer, run code, or touch files, and would say a tool "wasn't available."
  Now every agent (Executive Assistant, Admin, Inside Sales, and the rest) gets
  the complete set: **web browsing, computer use, web search, file read/write,
  terminal, code execution, vision, image generation, video, text‑to‑speech,
  PDF/PowerPoint, and delegation** — plus their existing pipeline/deal tools.
- **Web search works with zero setup.** Agents can now actually search the web
  and pull page content, not just open a link you give them. It uses a free,
  keyless search backend by default — nothing to configure. If you've added a
  premium search key (Firecrawl/Exa/etc.), that keeps taking priority.

## Under the hood

- Capability toolsets are now shared across all agents instead of declared one
  agent at a time, so new agents inherit the full kit automatically.
- Bundled the keyless DuckDuckGo (`ddgs`) search provider into the runtime for
  both Apple Silicon and Intel Macs, so web search registers automatically when
  no premium provider key is configured.
