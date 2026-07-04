---
name: code-change-reference-package
description: "Assemble a portable reference kit for Elevate-style chat-driven code changes. Use when the user wants a reusable package/folder of prompts, architecture docs, a TypeScript starter kit, or curated Elevate source snippets for wiring an Executive Assistant to run Codex/Claude Code safely against a repo."
---

# Code-change reference package

## When to use

Use this when the user asks for a reusable package/folder/reference kit that helps another app replicate Elevate-style chat-driven code changes, where an Executive Assistant can call a backend tool to run Codex/Claude Code, modify a repo, capture diffs, run verification, and report back.

## Reusable approach

1. **Create a dedicated package folder**
   - Put it under the user-requested destination, for example:
     - `/Users/admin/HIILITE/elevate-code-change-reference`
   - Do not overwrite an existing folder without checking first.

2. **Curate the conceptual docs first**
   Include small, token-efficient markdown docs:
   - `00_README.md` — how to use the package.
   - `docs/01_ARCHITECTURE.md` — user chat → Executive Assistant → code-change tool → worktree → Codex/Claude Code → diff + verification → approval/apply.
   - `docs/02_EXECUTIVE_ASSISTANT_INTEGRATION.md` — explain that the assistant is powerful because it has a controlled backend tool, not because of prompt magic.
   - `docs/03_SECURITY_AND_APPROVALS.md` — repo allowlist, path blocklist, sanitized env, command allowlist, timeouts, audit logs, approval gates.
   - `docs/04_IMPLEMENTATION_CHECKLIST.md` — backend, chat/tool, verification, and test checklist.

3. **Add prompts**
   Include:
   - `prompts/build-feature-claude-code.md` — a paste-ready prompt for Claude Code to implement the feature in the target app.
   - `prompts/internal-coding-agent.md` — the prompt the target app backend should send to Claude Code/Codex for each code-change job.

4. **Add a small starter kit**
   For TypeScript apps, include `starter-kit/typescript/` with:
   - `types.ts` — `CodeChangeJobRequest`, `CodeChangeJobResult`, `RepoConfig`, `CodeAgentRunner`.
   - `process.ts` — safe subprocess helper and sanitized env.
   - `runner.ts` — `ClaudeCodeRunner` and optional `CodexRunner` adapters.
   - `git.ts` — worktree creation, changed-files, diff capture.
   - `policy.ts` — blocked paths, approval policy, verification command allowlist.
   - `codeChangeService.ts` — lifecycle: validate repo, create worktree, invoke runner, capture diff, verify, persist.
   - `assistantTool.ts` — tool schema for `run_code_change` and assistant instruction.
   - `exampleRepoConfig.ts` — sample repo allowlist/config.

5. **Copy curated Elevate source references**
   If available, pull from `~/.elevate/elevate-current-src/cli/` rather than random artifact folders. Useful references include:
   - `tools/delegate_tool.py`
   - `model_tools.py`
   - `toolsets.py`
   - `tools/registry.py`
   - `tools/terminal_tool.py`
   - `tools/file_tools.py`
   - `tools/environments/base.py`
   - `tools/environments/local.py`
   - `agent/claude_code_cli_client.py`
   - `agent/copilot_acp_client.py`
   - `agent/transports/base.py`
   - `agent/transports/types.py`
   - `agent/transports/codex.py`
   - `agent/codex_responses_adapter.py`
   - `agent/codex_runtime.py`
   - relevant delegate/Codex tests.

6. **Also create token-cheap snippets**
   Full source files can be large. Add `snippets/` with line-range excerpts from the load-bearing files so another coding agent can read snippets first and only open full copies if needed.

7. **Write a manifest**
   Create `MANIFEST.json` with:
   - creation time,
   - package root,
   - purpose,
   - starter files,
   - snippets,
   - copied source file list and byte sizes.

8. **Verify the package**
   - List the package tree with `search_files(target='files')` or equivalent.
   - Run a basic secret scan over the package for obvious real secrets, private keys, password/token assignments, and API-key patterns.
   - Test-key strings inside tests like `sk-or-test` are acceptable if clearly fake.

## Practical notes

- The valuable lesson is to package both **implementation references** and **target-app scaffolding**. The target app should not need to consume Elevate’s whole repo.
- Put concise docs and starter-kit files at the top level so Claude Code can start with low token cost.
- Keep full Elevate source copies in a clearly labelled `reference_source_copies/` directory so they are optional deeper context.
- Emphasize the safety model: the Executive Assistant calls a narrow backend tool such as `run_code_change`; the backend owns filesystem access, shell execution, worktrees, approvals, verification, and audit logging.

## Done criteria

- Folder exists at the requested destination.
- It contains prompts, docs, starter kit, snippets, curated source copies, and manifest.
- Package tree is verified.
- Secret scan is clean or only finds clearly fake test credentials.
- Final response gives the exact folder path and brief inventory.
