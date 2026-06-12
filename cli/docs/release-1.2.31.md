# Elevate 1.2.31 — release notes

Companion fix to 1.2.30.

## A bad run can't entrench itself in a skill anymore

Agents update their own skills after hard runs — that's how runs compound.
But it also means a run that fought through a login with hand-scripted
Selenium could "learn" that approach into its local copy of a bundled skill,
and local edits normally shadow bundled updates. The very machine that
suffered the bad run would be the one machine the 1.2.30 skill fix couldn't
reach.

The skill sync now detects code signatures of hand-rolled browser automation
baked into local copies of bundled skills and force-replaces them with the
clean bundled version. Genuine customizations are untouched — the detection
keys on automation code, which the bundled skills never contain.
