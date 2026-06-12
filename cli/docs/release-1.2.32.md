# Elevate 1.2.32 — release notes

Agents stop losing their own tools.

## Dashboard chats keep the full toolset

A per-message keyword filter in the dashboard could silently narrow the
agent's tools based on how your message was worded — a request mentioning
deals or WEBForms landed in a profile with terminal access but no browser,
so the agent truthfully said it "didn't have browser controls" and then
tried to script a browser by hand through the terminal. The filter is now
strictly opt-in; every dashboard message gets the full configured toolset.

## Selecting an agent in chat binds its real loadout

Switching the chat to a fleet agent (Admin, Outreach, ...) used to apply only
its persona — its actual hub toolsets stayed unbound, while *delegating* to
the same agent granted everything. Agents learned that gap and routed work
to "their own" subagent lane. Lane switching now binds the agent's real
loadout onto the live session.

## Every agent knows how to touch the world

All agents now carry an execution-surfaces doctrine: use the built-in
browser tools directly (the managed visible Chrome is already logged in and
persistent), use the computer tool for native apps, never hand-roll
Selenium through the terminal, and report genuinely missing tools as an
install issue instead of scripting around them.
