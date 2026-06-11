# Elevate 1.2.10 — release notes

Chat polish: what you see stays what you saw.

## Fixes

- **No more internal file chips in chat.** Temp files and pipeline internals
  (`elevate-cwd-…`, `elevate-snap-…`, `.jsonl` data files) no longer appear as
  artifact cards. Only real deliverables — PDFs, docs, images, reports — do.
- **Artifact cards no longer pin to the conversation.** Files the agent
  produces live in the side panel, not stuck inline in your chat for the whole
  session.
- **Replies stop disappearing.** Two rendering races could make a finished
  answer vanish from the transcript (it was always saved — leaving and
  re-opening the chat brought it back) or get replaced by a truncated version.
  Both are fixed: a rendered answer can't be wiped or shrunk by a background
  refresh.
