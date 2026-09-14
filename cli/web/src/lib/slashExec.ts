/**
 * Slash command execution pipeline for the web chat.
 *
 * Mirrors the Ink TUI's createSlashHandler.ts:
 *
 *   1. Parse the command into `name` + `arg`.
 *   2. Try `slash.exec` — covers every registry-backed command the terminal
 *      UI knows about (/help, /resume, /compact, /model, …). Output is
 *      rendered into the transcript.
 *   3. If `slash.exec` errors (command rejected, unknown, or needs client
 *      behaviour), fall back to `command.dispatch` which returns a typed
 *      directive: `exec` | `plugin` | `alias` | `skill` | `send`.
 *   4. Each directive is dispatched to the appropriate callback.
 *
 * Keeping the pipeline here (instead of inline in ChatPage) lets future
 * clients (SwiftUI, Android) implement the same logic by reading the same
 * contract.
 */

import type { GatewayClient } from "@/lib/gatewayClient";

export interface SlashExecResponse {
  display?: string;
  kind?: string;
  output?: string;
  warning?: string;
}

export type CommandDispatchResponse =
  | { type: "exec" | "plugin"; output?: string }
  | { type: "alias"; target: string }
  | { type: "skill"; name: string; message?: string }
  | { type: "send"; message: string };

export interface SlashExecCallbacks {
  /** Complete the manual /compact activity row without rendering raw diagnostics. */
  compactDone?(text: string, rawOutput?: string): void;
  /** Clear a manual /compact activity row and render the user-facing failure. */
  compactFailed?(text: string): void;
  /** Render a transcript system message. */
  sys(text: string): void;
  /** Submit a user message to the agent (prompt.submit). */
  send(message: string): Promise<void> | void;
  /**
   * Submit a skill payload. The model receives the full SKILL.md `payload`,
   * but the client MUST keep it out of the visible transcript — the leading
   * `/command` bubble is the only thing the user should see. This is what
   * separates `send` (a visible user turn) from a skill load (bulk context
   * that loads quietly on the first slash command).
   */
  sendSkill(
    payload: string,
    commandName: string,
    args?: string,
  ): Promise<void> | void;
}

export interface SlashExecOptions {
  /** Raw command including the leading slash (e.g. "/model opus-4.6"). */
  command: string;
  /** Session id. If empty the call is still issued — some commands are session-less. */
  sessionId: string;
  gw: GatewayClient;
  callbacks: SlashExecCallbacks;
}

export type SlashExecResult = "done" | "sent" | "error" | "transport-error";

/**
 * Run a slash command. Returns the terminal state so callers can decide
 * whether to clear the composer, queue retries, etc.
 */
export async function executeSlash({
  command,
  sessionId,
  gw,
  callbacks: { compactDone, compactFailed, sys, send, sendSkill },
}: SlashExecOptions): Promise<SlashExecResult> {
  const { name, arg } = parseSlash(command);

  if (!name) {
    sys("empty slash command");
    return "error";
  }

  // Primary dispatcher.
  try {
    const r = await gw.request<SlashExecResponse>("slash.exec", {
      command: command.replace(/^\/+/, ""),
      session_id: sessionId,
    });
    const body = r?.output || `/${name}: no output`;
    if (
      name === "compact" &&
      !r?.warning &&
      ((r?.kind === "compact" && r.display) || compactOutputLooksCompleted(body))
    ) {
      const display = r?.display || "Finished compacting";
      if (compactDone) compactDone(display, body);
      else sys(display);
      return "done";
    }
    if (name === "compact" && compactFailed) {
      compactFailed(r?.warning ? `warning: ${r.warning}\n${body}` : body);
      return "done";
    }
    sys(r?.warning ? `warning: ${r.warning}\n${body}` : body);
    return "done";
  } catch (err) {
    if (isGatewayTransportError(err)) return "transport-error";
    /* fall through to command.dispatch */
  }

  try {
    const d = parseCommandDispatch(
      await gw.request<unknown>("command.dispatch", {
        name,
        arg,
        session_id: sessionId,
      }),
    );

    if (!d) {
      sys("error: invalid response: command.dispatch");
      return "error";
    }

    switch (d.type) {
      case "exec":
      case "plugin":
        sys(d.output ?? "(no output)");
        return "done";

      case "alias":
        return executeSlash({
          command: `/${d.target}${arg ? ` ${arg}` : ""}`,
          sessionId,
          gw,
          callbacks: { compactDone, compactFailed, sys, send, sendSkill },
        });

      case "skill": {
        const msg = d.message?.trim() ?? "";
        if (!msg) {
          sys(`/${name}: skill payload missing message`);
          return "error";
        }
        // The model gets the full SKILL.md via sendSkill; the transcript
        // should only show the `/command` bubble the user already typed.
        await sendSkill(msg, d.name, arg);
        return "sent";
      }

      case "send": {
        const msg = d.message?.trim() ?? "";
        if (!msg) {
          sys(`/${name}: empty message`);
          return "error";
        }
        await send(msg);
        return "sent";
      }
    }
  } catch (err) {
    if (isGatewayTransportError(err)) return "transport-error";
    sys(`error: ${err instanceof Error ? err.message : String(err)}`);
    return "error";
  }
}

export function parseSlash(command: string): { name: string; arg: string } {
  const m = command.replace(/^\/+/, "").match(/^(\S+)\s*(.*)$/);
  return m ? { name: m[1], arg: m[2].trim() } : { name: "", arg: "" };
}

function compactOutputLooksCompleted(output: string): boolean {
  const clean = output.toLowerCase();
  return (
    clean.includes("compressed:") ||
    clean.includes("compacted earlier turns:") ||
    clean.includes("no changes from compression") ||
    clean.includes("approx request size")
  );
}

function isGatewayTransportError(err: unknown): boolean {
  const message = err instanceof Error ? err.message : String(err);
  return /gateway not connected|websocket (?:closed|connection failed)/i.test(message);
}

function parseCommandDispatch(raw: unknown): CommandDispatchResponse | null {
  if (!raw || typeof raw !== "object") return null;

  const r = raw as Record<string, unknown>;
  const str = (v: unknown) => (typeof v === "string" ? v : undefined);

  switch (r.type) {
    case "exec":
    case "plugin":
      return { type: r.type, output: str(r.output) };

    case "alias":
      return typeof r.target === "string"
        ? { type: "alias", target: r.target }
        : null;

    case "skill":
      return typeof r.name === "string"
        ? { type: "skill", name: r.name, message: str(r.message) }
        : null;

    case "send":
      return typeof r.message === "string"
        ? { type: "send", message: r.message }
        : null;

    default:
      return null;
  }
}
