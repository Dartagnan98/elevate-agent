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
  insertText?: string;
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
  onSubmit?(nextInput: string): void;
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
// The slash menu is the primary way to reach skills, so it shows the full
// catalog (the popover itself scrolls) instead of the 12-item @-mention cap.
const MAX_SLASH_GROUP_ITEMS = 100;
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

function displaySkillName(name: string): string {
  return name
    .split(/[-_]/)
    .filter(Boolean)
    .map((part) => part.slice(0, 1).toUpperCase() + part.slice(1))
    .join(" ");
}

function skillCommandText(name: string): string {
  const slug = name
    .toLowerCase()
    .replace(/[ _]+/g, "-")
    .replace(/[^a-z0-9-]/g, "")
    .replace(/-{2,}/g, "-")
    .replace(/^-+|-+$/g, "");
  return slug ? `/${slug}` : "";
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

function matchesSlash(item: Pick<PickerItem, "display" | "meta" | "text">, query: string): boolean {
  const q = query.toLowerCase();
  if (!q) return true;
  return [
    asPlainText(item.display),
    item.text.replace(/^\//, ""),
    item.text,
    item.meta ?? "",
  ]
    .join(" ")
    .toLowerCase()
    .includes(q);
}

function slashCommandQuery(text: string): string | null {
  const body = text.replace(/^\/+/, "");
  if (/\s/.test(body)) return null;
  return body.toLowerCase();
}

function mentionCatalogItems(
  catalog: MentionCatalog,
  agents: CompletionAgent[],
  query: string,
): PickerItem[] {
  const items: PickerItem[] = [];

  for (const agent of agents.filter((agent) => agent.enabled)) {
    items.push({
      display: agent.name,
      group: "Agents",
      icon: Bot,
      kind: "agent",
      meta: agent.role || agent.description || agent.status,
      text: `@agent:${agent.id}`,
    });
  }

  for (const plugin of catalog.plugins) {
    items.push({
      display: plugin.label || plugin.name,
      group: "Plugins",
      icon: Plug,
      kind: "plugin",
      meta: plugin.description || plugin.source || "Dashboard plugin",
      text: `@plugin:${plugin.name}`,
    });
  }

  for (const toolset of catalog.toolsets.filter((toolset) => toolset.enabled)) {
    items.push({
      display: toolset.label || toolset.name,
      group: "Toolsets",
      icon: Hammer,
      kind: "toolset",
      meta: toolset.description || `${toolset.tools.length} tools`,
      text: `@toolset:${toolset.name}`,
    });
  }

  for (const skill of catalog.skills.filter((skill) => skill.enabled)) {
    items.push({
      display: displaySkillName(skill.name),
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

function slashSkillItems(catalog: MentionCatalog, query: string | null): PickerItem[] {
  if (query === null) return [];
  return catalog.skills
    .filter((skill) => skill.enabled)
    .map((skill) => {
      const commandText = skillCommandText(skill.name);
      return {
        display: displaySkillName(skill.name),
        group: "Skills",
        icon: Sparkles,
        kind: "skill" as const,
        meta: [skill.description, skill.category].filter(Boolean).join(" · "),
        text: commandText,
      };
    })
    .filter((item) => item.text && matchesSlash(item, query))
    .slice(0, MAX_SLASH_GROUP_ITEMS);
}

function skillCommandMap(catalog: MentionCatalog): Map<string, SkillInfo> {
  const mapped = new Map<string, SkillInfo>();
  for (const skill of catalog.skills.filter((candidate) => candidate.enabled)) {
    const commandText = skillCommandText(skill.name);
    if (commandText) mapped.set(commandText.toLowerCase(), skill);
  }
  return mapped;
}

function normalizeSlashItem(
  item: CompletionItem,
  skillsByCommand: Map<string, SkillInfo>,
): PickerItem {
  const rawText = item.text || asPlainText(item.display);
  const insertText = rawText.startsWith("/") ? rawText : `/${rawText}`;
  const commandText = insertText.trimEnd();
  const skill = skillsByCommand.get(commandText.toLowerCase());
  return {
    display: skill ? displaySkillName(skill.name) : displayCommandLabel(item.display, commandText),
    group: skill ? "Skills" : "Commands",
    icon: skill ? Sparkles : commandIcon(commandText),
    insertText: skill ? commandText : insertText,
    kind: skill ? "skill" : "slash",
    meta: skill ? [skill.description, skill.category].filter(Boolean).join(" · ") : item.meta,
    text: commandText,
  };
}

function shouldShowSlashCommandItem(item: PickerItem, query: string | null, hasSkillMatches: boolean): boolean {
  if (!hasSkillMatches || query === null) return true;
  if (query === "skills") return true;
  return item.text.toLowerCase() !== "/skills";
}

function slashGroupOrder(
  query: string | null,
  slashText: string,
  hasSkillMatches: boolean,
): string[] {
  const normalized =
    query ??
    slashText
      .replace(/^\/+/, "")
      .trim()
      .toLowerCase()
      .split(/\s+/)[0] ??
    "";
  if (hasSkillMatches && normalized && normalized !== "skills") {
    return ["Skills", "Commands"];
  }
  return ["Commands", "Skills"];
}

function orderGroupedItems(
  items: PickerItem[],
  groupOrder: string[],
  maxPerGroup: number = MAX_GROUP_ITEMS,
): PickerItem[] {
  const seen = new Set<string>();
  const grouped = new Map<string, PickerItem[]>();
  for (const item of items) {
    const dedupeKey = `${item.group}:${item.text}`;
    if (seen.has(dedupeKey)) continue;
    seen.add(dedupeKey);

    const group = grouped.get(item.group) ?? [];
    if (group.length < maxPerGroup) {
      group.push(item);
      grouped.set(item.group, group);
    }
  }
  return groupOrder.flatMap((group) => grouped.get(group) ?? []);
}

function shouldAppendSpace(item: PickerItem): boolean {
  // Skills almost always take arguments (an address, a name, "pick up from
  // step X"). Leave a trailing space after the command so the user can type
  // them immediately instead of the command firing bare.
  if (item.kind === "skill") return true;
  if (item.kind === "slash" || item.text.startsWith("/")) {
    return false;
  }
  return !item.text.endsWith(":") && !item.text.endsWith("/");
}

export const SlashPopover = forwardRef<SlashPopoverHandle, Props>(
  function SlashPopover({ agents, caretIndex, input, gw, onApply, onSubmit }, ref) {
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
      if (!trigger || catalogLoadedRef.current) return;
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
    }, [trigger]);

    useEffect(() => {
      if (!trigger || !gw) {
        setItems([]);
        return;
      }

      const key =
        trigger.mode === "slash"
          ? `slash:${trigger.text}:${catalog.skills.length}`
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
            const query = slashCommandQuery(trigger.text);
            const skillsByCommand = skillCommandMap(catalog);
            const commandItems = (response?.items ?? [])
              .map((item) => normalizeSlashItem(item, skillsByCommand))
              .filter((item) => query === null || matchesSlash(item, query));
            const skillItems = slashSkillItems(catalog, query);
            const hasSkillMatches =
              skillItems.length > 0 || commandItems.some((item) => item.kind === "skill");
            setItems(
              orderGroupedItems(
                [
                  ...skillItems,
                  ...commandItems.filter((item) =>
                    shouldShowSlashCommandItem(item, query, hasSkillMatches),
                  ),
                ],
                slashGroupOrder(query, trigger.text, hasSkillMatches),
                MAX_SLASH_GROUP_ITEMS,
              ),
            );
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
          setItems(orderGroupedItems(merged, ["Agents", "Plugins", "Toolsets", "Skills", "Context", "Files"]));
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

    const inputForItem = useCallback(
      (item: PickerItem): { nextCaret: number; nextInput: string } | null => {
        if (!trigger) return null;

        let replaceStart = trigger.start;
        let replacement = item.insertText ?? item.text;

        if (trigger.mode === "slash") {
          replaceStart = trigger.start + slashReplaceFrom;
          replacement = replacement.replace(/^\//, "");
        }

        if (shouldAppendSpace(item)) {
          replacement = replacement.endsWith(" ") ? replacement : `${replacement} `;
        }

        const nextInput = `${input.slice(0, replaceStart)}${replacement}${input.slice(trigger.end)}`;
        return {
          nextCaret: replaceStart + replacement.length,
          nextInput,
        };
      },
      [input, slashReplaceFrom, trigger],
    );

    const apply = useCallback(
      (item: PickerItem, options?: { submit?: boolean }) => {
        const next = inputForItem(item);
        if (!next) return;
        setItems([]);
        if (options?.submit && onSubmit) {
          onSubmit(next.nextInput);
          return;
        }
        onApply(next.nextInput, next.nextCaret);
      },
      [inputForItem, onApply, onSubmit],
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
              if (item) {
                const next = inputForItem(item);
                // Only fire on Enter when the typed text already IS the full
                // command (user typed it out, no list-pick). Picking a skill
                // from the list loads it (with a space for args) instead of
                // firing it bare — matching the click behavior.
                const shouldSubmit =
                  event.key === "Enter" &&
                  trigger?.mode === "slash" &&
                  Boolean(onSubmit) &&
                  next?.nextInput.trim() === input.trim();
                apply(item, { submit: shouldSubmit });
              }
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
      [apply, input, inputForItem, items, onSubmit, selected, trigger?.mode, visible],
    );

    // Keep the keyboard-selected row inside the scrollable popover viewport.
    useEffect(() => {
      if (!visible) return;
      const el = document.getElementById(`slash-item-${selected}`);
      el?.scrollIntoView({ block: "nearest" });
    }, [selected, visible]);

    if (!visible) return null;

    let lastGroup = "";

    const listboxId = "slash-popover-listbox";
    const activeItemId = items[selected] ? `slash-item-${selected}` : undefined;

    return (
      <div
        aria-activedescendant={activeItemId}
        className="slash-popover"
        id={listboxId}
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
                <div className="slash-group">
                  {item.group}
                </div>
              )}
              <button
                aria-selected={active}
                className={cn("slash-row", active && "active")}
                id={`slash-item-${index}`}
                onClick={() =>
                  // Load the command into the composer (with a trailing space
                  // for skills) so the user can add arguments, then Enter to
                  // run — instead of firing it bare on click, which left
                  // arg-taking skills doing nothing.
                  apply(item)
                }
                onMouseEnter={() => setSelected(index)}
                role="option"
                type="button"
              >
                <Icon />
                <span className="slash-name">
                  {item.display}
                </span>
                {item.meta && (
                  <span className="slash-desc">
                    {item.meta}
                  </span>
                )}
                {item.kind === "skill" && (
                  <span className="slash-kind">
                    Personal
                  </span>
                )}
              </button>
            </div>
          );
        })}
        {trigger?.mode === "mention" && trigger.query.length === 0 && (
          <div className="px-2.5 pb-1.5 pt-1 text-[11.5px] text-[var(--fg-faint)]">
            Type to search for files, skills, agents, toolsets, or plugins.
          </div>
        )}
      </div>
    );
  },
);
