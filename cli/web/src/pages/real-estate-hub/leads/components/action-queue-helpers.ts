import type { LeadsDraft } from "../leads-data";

export function matchesLeadsSourceFilter(
  item: { source?: string; sourceId?: string },
  sourceFilter: string,
): boolean {
  if (!sourceFilter || sourceFilter === "all") return true;
  if (item.sourceId === sourceFilter) return true;
  const source = (item.source || "").toLowerCase();
  if (sourceFilter === "lofty") return source === "lofty crm";
  if (sourceFilter === "composio-insta") {
    return source.includes("composio") || source.includes("instagram");
  }
  return false;
}

export function nextDraftQueueSelection(
  current: ReadonlySet<string>,
  drafts: Array<Pick<LeadsDraft, "id">>,
): Set<string> {
  const ids = drafts.map((draft) => draft.id).filter(Boolean);
  const allSelected = ids.length > 0 && ids.every((id) => current.has(id));
  const next = new Set(current);
  for (const id of ids) {
    if (allSelected) next.delete(id);
    else next.add(id);
  }
  return next;
}
