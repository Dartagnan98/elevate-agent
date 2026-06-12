# Elevate 1.2.29 — release notes

One fix, fleet-wide.

## Every agent can see Composio now

Fleet agents (Admin, Outreach, Analyst, and the rest — including custom
agents) could not see Composio even when the API key was configured: the
toolset was carried by the main assistant's platform presets but was missing
from the shared per-agent baseline. It's in the baseline now, so every agent
picks it up automatically on the next load. Installs without a Composio key
are unaffected (the tool stays hidden until a key is set).
