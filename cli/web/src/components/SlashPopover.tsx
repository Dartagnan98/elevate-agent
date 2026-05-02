import { api, type PluginManifestResponse, type SkillInfo, type ToolsetInfo } from "@/lib/api";
import type { GatewayClient } from "@/lib/gatewayClient";
import { cn } from "@/lib/utils";
import {
  Bot,
  Box,
  Brain,
  CalendarClock,
  CheckSquare,
  Code2,
  FileText,
  Folder,
  GitBranch,
  Globe,
  Hammer,
  ListChecks,
  MessageSquare,
  Plug,
  Sparkles,
  Terminal,
  Zap,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import {
  forwardRef,
  useCallback,
  useEffect,
  useImperativeHandle,
  useMemo,
  useRef,
  useState,
} from "react";

export interface CompletionItem {
  display?: unknown;
  text: string;
  meta?: string;
}

interface PickerItem extends CompletionItem {
  display: string;
  group: string;
  icon: LucideIcon;
  kind: "agent" | "context" | "file" | "plugin" | "skill" | "slash" | "toolset";
}

export interface CompletionAgent {
  description?: string;
  enabled: boolean;
  id: string;
  name: string;
  role?: string;
  status?: string;
}

export interface SlashPopoverHandle {
  /** Returns true if the key was consumed by the popover. */
  handleKey(e: React.KeyboardEvent<HTMLTextAreaElement>): boolean;
}

interface Props {
  agents: CompletionAgent[];
  caretIndex: number;
  gw: GatewayClient | null;
  input: string;
  onApply(nextInput: string, nextCaret: number): void;
}

interface CompletionResponse {
  items?: CompletionItem[];
  replace_from?: number;
}

interface MentionCatalog {
  plugins: PluginManifestResponse[];
  skills: SkillInfo[];
  toolsets: ToolsetInfo[];
}

type Trigger =
  | {
      end: number;
      mode: "mention";
      query: string;
      start: number;
      word: string;
    }
  | {
      end: number;
      mode: "slash";
      start: number;
      text: string;
    };

const DEBOUNCE_MS = 70;
const MAX_GROUP_ITEMS = 12;
const EMPTY_CATALOG: MentionCatalog = {
  plugins: [],
  skills: [],
  toolsets: [],
};

const STATIC_CONTEXT_REFS: PickerItem[] = [
  {
    display: "@diff",
    group: "Context",
    icon: GitBranch,
    kind: "context",
    meta: "Git working tree diff",
    text: "@diff",
  },
  {
    display: "@staged",
    group: "Context",
    icon: CheckSquare,
    kind: "context",
    meta: "Git staged diff",
    text: "@staged",
  },
  {
    display: "@file:",
    group: "Files",
    icon: FileText,
    kind: "file",
    meta: "Attach a file",
    text: "@file:",
  },
  {
    display: "@folder:",
    group: "Files",
    icon: Folder,
    kind: "file",
    meta: "Attach a folder",
    text: "@folder:",
  },
  {
    display: "@url:",
    group: "Context",
    icon: Globe,
    kind: "context",
    meta: "Fetch web content",
    text: "@url:",
  },
  {
    display: "@git:",
    group: "Context",
    icon: GitBranch,
    kind: "context",
    meta: "Git log with diffs",
    text: "@git:",
  },
];

function commandIcon(command: string): LucideIcon {
  const name = command.replace(/^\//, "").trim().split(/\s+/)[0];
  if (["fast", "yolo"].includes(name)) return Zap;
  if (["model", "reasoning"].includes(name)) return Box;
  if (name === "personality") return Brain;
  if (["agents", "tasks", "queue", "steer"].includes(name)) return Bot;
  if (["cron", "background"].includes(name)) return CalendarClock;
  if (["skills", "plugins"].includes(name)) return Sparkles;
  if (["tools", "toolsets", "browser"].includes(name)) return Hammer;
  if (["help", "commands", "status", "usage", "insights"].includes(name)) return ListChecks;
  if (["branch", "fork", "resume", "new"].includes(name)) return MessageSquare;
  if (["compact", "compress"].includes(name)) return Code2;
  return Terminal;
}

function asPlainText(value: unknown, fallback = ""): string {
  if (typeof value === "string") return value;
  if (Array.isArray(value)) {
    return value
      .map((part) => {
        if (Array.isArray(part)) return String(part[1] ?? "");
        if (part && typeof part === "object" && "text" in part) {
          return String((part as { text?: unknown }).text ?? "");
        }
        return typeof part === "string" ? part : "";
      })
      .join("");
  }
  return fallback;
}

function displayCommandLabel(display: unknown, text: string): string {
  const raw = asPlainText(display, text).replace(/^\//, "").trim();
  const base = raw.split(/\s+/)[0];
  return base
    .split(/[-_]/)
    .filter(Boolean)
    .map((part) => part.slice(0, 1).toUpperCase() + part.slice(1))
    .join(" ");
}

function detectTrigger(input: string, caretIndex: number): Trigger | null {
  const caret = Math.max(0, Math.min(caretIndex, input.length));
  const before = input.slice(0, caret);
  const firstNonSpace = before.search(/\S/);

  if (firstNonSpace >= 0 && before.slice(firstNonSpace).startsWith("/")) {
    const lineStart = before.lastIndexOf("\n") + 1;
    if (firstNonSpace === lineStart) {
      return {
        end: caret,
        mode: "slash",
        start: firstNonSpace,
        text: before.slice(firstNonSpace),
      };
    }
  }

  let start = caret;
  while (start > 0 && !/\s/.test(input[start - 1] ?? "")) {
    start -= 1;
  }
  const word = input.slice(start, caret);
  if (!word.startsWith("@")) return null;

  return {
    end: caret,
    mode: "mention",
    query: word.slice(1),
    start,
    word,
  };
}

function matchesMention(item: Pick<PickerItem, "display" | "meta" | "text">, query: string): boolean {
  const q = query.toLowerCase();
  if (!q) return true;
  return [asPlainText(item.display), item.text, item.meta ?? ""]
    .join(" ")
    .toLowerCase()
    .includes(q);
}

function mentionCatalogItems(
  catalog: MentionCatalog,
  agents: CompletionAgent[],
  query: string,
): PickerItem[] {
  const items: PickerItem[] = [];

  for (const agent of agents.filter((agent) => agent.enabled).slice(0, MAX_GROUP_ITEMS)) {
    items.push({
      display: agent.name,
      group: "Agents",
      icon: Bot,
      kind: "agent",
      meta: agent.role || agent.description || agent.status,
      text: `@agent:${agent.id}`,
    });
  }

  for (const plugin of catalog.plugins.slice(0, MAX_GROUP_ITEMS)) {
    items.push({
      display: plugin.label || plugin.name,
      group: "Plugins",
      icon: Plug,
      kind: "plugin",
      meta: plugin.description || plugin.source || "Dashboard plugin",
      text: `@plugin:${plugin.name}`,
    });
  }

  for (const toolset of catalog.toolsets.filter((toolset) => toolset.enabled).slice(0, MAX_GROUP_ITEMS)) {
    items.push({
      display: toolset.label || toolset.name,
      group: "Toolsets",
      icon: Hammer,
      kind: "toolset",
      meta: toolset.description || `${toolset.tools.length} tools`,
      text: `@toolset:${toolset.name}`,
    });
  }

  for (const skill of catalog.skills.filter((skill) => skill.enabled).slice(0, 80)) {
    items.push({
      display: skill.name
        .split(/[-_]/)
        .filter(Boolean)
        .map((part) => part.slice(0, 1).toUpperCase() + part.slice(1))
        .join(" "),
      group: "Skills",
      icon: Box,
      kind: "skill",
      meta: [skill.description, skill.category].filter(Boolean).join(" · "),
      text: `@skill:${skill.name}`,
    });
  }

  const filtered = items.filter((item) => matchesMention(item, query));
  const grouped = new Map<string, PickerItem[]>();
  for (const item of filtered) {
    const group = grouped.get(item.group) ?? [];
    if (group.length < MAX_GROUP_ITEMS) {
      group.push(item);
      grouped.set(item.group, group);
    }
  }

  return ["Agents", "Plugins", "Toolsets", "Skills"].flatMap(
    (group) => grouped.get(group) ?? [],
  );
}

function classifyPathItem(item: CompletionItem): PickerItem {
  const text = item.text || asPlainText(item.display);
  const isFolder = text.startsWith("@folder:") || text.endsWith("/");
  const isStatic = STATIC_CONTEXT_REFS.some((ref) => ref.text === text);
  return {
    display: asPlainText(item.display, String(text)),
    group: isStatic && !text.startsWith("@file") && !text.startsWith("@folder") ? "Context" : "Files",
    icon: isFolder ? Folder : text.startsWith("@url") ? Globe : text.startsWith("@git") ? GitBranch : FileText,
    kind: isStatic ? "context" : "file",
    meta: item.meta,
    text,
  };
}

function normalizeSlashItem(item: CompletionItem): PickerItem {
  const commandText = item.text.startsWith("/") ? item.text : `/${item.text}`;
  return {
    display: displayCommandLabel(item.display, commandText),
    group: "Commands",
    icon: commandIcon(commandText),
    kind: "slash",
    meta: item.meta,
    text: commandText,
  };
}

function shouldAppendSpace(item: PickerItem): boolean {
  if (item.kind === "slash") {
    return !item.text.endsWith(" ") && !item.text.endsWith(":");
  }
  return !item.text.endsWith(":") && !item.text.endsWith("/");
}

export const SlashPopover = forwardRef<SlashPopoverHandle, Props>(
  function SlashPopover({ agents, caretIndex, input, gw, onApply }, ref) {
    const trigger = useMemo(
      () => detectTrigger(input, caretIndex),
      [caretIndex, input],
    );
    const [items, setItems] = useState<PickerItem[]>([]);
    const [selected, setSelected] = useState(0);
    const [slashReplaceFrom, setSlashReplaceFrom] = useState(1);
    const [catalog, setCatalog] = useState<MentionCatalog>(EMPTY_CATALOG);
    const catalogLoadedRef = useRef(false);
    const requestKeyRef = useRef("");

    useEffect(() => {
      if (trigger?.mode !== "mention" || catalogLoadedRef.current) return;
      catalogLoadedRef.current = true;
      void Promise.allSettled([
        api.getSkills(),
        api.getToolsets(),
        api.getPlugins(),
      ]).then(([skills, toolsets, plugins]) => {
        setCatalog({
          plugins: plugins.status === "fulfilled" ? plugins.value : [],
          skills: skills.status === "fulfilled" ? skills.value : [],
          toolsets: toolsets.status === "fulfilled" ? toolsets.value : [],
        });
      });
    }, [trigger?.mode]);

    useEffect(() => {
      if (!trigger || !gw) {
        setItems([]);
        return;
      }

      const key =
        trigger.mode === "slash"
          ? `slash:${trigger.text}`
          : `mention:${trigger.word}:${catalog.skills.length}:${catalog.toolsets.length}:${catalog.plugins.length}:${agents.length}`;
      requestKeyRef.current = key;

      const timer = window.setTimeout(async () => {
        try {
          if (trigger.mode === "slash") {
            const response = await gw.request<CompletionResponse>("complete.slash", {
              text: trigger.text,
            });
            if (requestKeyRef.current !== key) return;
            setSlashReplaceFrom(response?.replace_from ?? 1);
            setItems((response?.items ?? []).map(normalizeSlashItem));
            setSelected(0);
            return;
          }

          const pathResponse = await gw.request<CompletionResponse>("complete.path", {
            word: trigger.word,
          });
          if (requestKeyRef.current !== key) return;

          const fileItems = (pathResponse?.items ?? []).map(classifyPathItem);
          const catalogItems = mentionCatalogItems(catalog, agents, trigger.query);
          const contextItems = STATIC_CONTEXT_REFS.filter((item) =>
            matchesMention(item, trigger.query),
          );
          const merged = [...catalogItems, ...contextItems, ...fileItems];
          const seen = new Set<string>();
          setItems(
            merged.filter((item) => {
              const dedupeKey = `${item.group}:${item.text}`;
              if (seen.has(dedupeKey)) return false;
              seen.add(dedupeKey);
              return true;
            }),
          );
          setSelected(0);
        } catch {
          if (requestKeyRef.current === key) {
            setItems([]);
          }
        }
      }, DEBOUNCE_MS);

      return () => window.clearTimeout(timer);
    }, [agents, catalog, gw, trigger]);

    const visible = Boolean(trigger && items.length > 0);

    const apply = useCallback(
      (item: PickerItem) => {
        if (!trigger) return;

        let replaceStart = trigger.start;
        let replacement = item.text;

        if (trigger.mode === "slash") {
          replaceStart = trigger.start + slashReplaceFrom;
          replacement = item.text.replace(/^\//, "");
        }

        if (shouldAppendSpace(item)) {
          replacement = replacement.endsWith(" ") ? replacement : `${replacement} `;
        }

        const nextInput = `${input.slice(0, replaceStart)}${replacement}${input.slice(trigger.end)}`;
        onApply(nextInput, replaceStart + replacement.length);
      },
      [input, onApply, slashReplaceFrom, trigger],
    );

    useImperativeHandle(
      ref,
      () => ({
        handleKey: (event) => {
          if (!visible) return false;

          switch (event.key) {
            case "ArrowDown":
              event.preventDefault();
              setSelected((value) => (value + 1) % items.length);
              return true;
            case "ArrowUp":
              event.preventDefault();
              setSelected((value) => (value - 1 + items.length) % items.length);
              return true;
            case "Enter":
            case "Tab": {
              event.preventDefault();
              const item = items[selected];
              if (item) apply(item);
              return true;
            }
            case "Escape":
              event.preventDefault();
              setItems([]);
              return true;
            default:
              return false;
          }
        },
      }),
      [apply, items, selected, visible],
    );

    if (!visible) return null;

    let lastGroup = "";

    return (
      <div
        className={cn(
          "absolute bottom-full left-0 right-0 z-40 mb-3 max-h-[24rem] overflow-y-auto rounded-[1.35rem] p-2",
          "bg-[color-mix(in_srgb,var(--chat-surface)_92%,black)] text-sm text-[var(--chat-text)]",
          "shadow-[0_28px_90px_rgba(0,0,0,0.42),inset_0_0_0_1px_var(--chat-border-strong)] backdrop-blur-xl",
        )}
        role="listbox"
      >
        {items.map((item, index) => {
          const active = index === selected;
          const Icon = item.icon;
          const showGroup = item.group !== lastGroup;
          lastGroup = item.group;

          return (
            <div key={`${item.group}-${item.text}-${index}`}>
              {showGroup && (
                <div className="px-3 pb-1 pt-2 text-xs font-medium text-[var(--chat-muted)]">
                  {item.group}
                </div>
              )}
              <button
                aria-selected={active}
                className={cn(
                  "grid min-h-10 w-full grid-cols-[1.75rem_minmax(0,auto)_minmax(0,1fr)_auto] items-center gap-2 rounded-xl px-2.5 py-1.5 text-left transition-colors",
                  active
                    ? "bg-[var(--chat-surface-strong)] text-[var(--chat-text)]"
                    : "text-[var(--chat-muted-strong)] hover:bg-[var(--chat-surface-soft)] hover:text-[var(--chat-text)]",
                )}
                onClick={() => apply(item)}
                onMouseEnter={() => setSelected(index)}
                role="option"
                type="button"
              >
                <Icon className="h-4 w-4 justify-self-center text-current opacity-90" />
                <span className="min-w-0 truncate text-[0.95rem] font-medium">
                  {item.display}
                </span>
                {item.meta && (
                  <span className="min-w-0 truncate text-[0.85rem] text-[var(--chat-muted)]">
                    {item.meta}
                  </span>
                )}
                {item.kind === "skill" && (
                  <span className="rounded-full px-2 py-0.5 text-[0.68rem] text-[var(--chat-muted)] shadow-[inset_0_0_0_1px_var(--chat-border)]">
                    Personal
                  </span>
                )}
              </button>
            </div>
          );
        })}
        {trigger?.mode === "mention" && trigger.query.length === 0 && (
          <div className="px-3 pb-2 pt-1 text-[0.82rem] text-[var(--chat-muted)]">
            Type to search for files, skills, agents, toolsets, or plugins.
          </div>
        )}
      </div>
    );
  },
);
