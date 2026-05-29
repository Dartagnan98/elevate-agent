import { useCallback, useId, useMemo, useRef, useState } from "react";
import type { CSSProperties } from "react";
import type { AgentHubMemoryEdge, AgentHubMemoryNode } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

type PositionedNode = {
  degree: number;
  groupKey: string;
  kind: NodeKind;
  node: AgentHubMemoryNode;
  x: number;
  y: number;
  r: number;
  opacity: number;
  rank: number;
};

type NodeKind =
  | "asset"
  | "chunk"
  | "community"
  | "document"
  | "entity"
  | "fact"
  | "general"
  | "plaud"
  | "project"
  | "tool"
  | "user_pref";

const WIDTH = 1280;
const HEIGHT = 780;
const VIEW_X = 120;
const VIEW_Y = 105;
const VIEW_WIDTH = 1080;
const VIEW_HEIGHT = 650;
const CENTER_X = WIDTH / 2;
const CENTER_Y = HEIGHT / 2 + 10;
const BOUNDS = {
  maxX: VIEW_X + VIEW_WIDTH - 72,
  maxY: VIEW_Y + VIEW_HEIGHT - 72,
  minX: VIEW_X + 72,
  minY: VIEW_Y + 72,
};

const KIND_ORDER: NodeKind[] = [
  "entity",
  "fact",
  "community",
  "project",
  "document",
  "chunk",
  "tool",
  "user_pref",
  "plaud",
  "asset",
  "general",
];

const NODE_TONE: Record<NodeKind, { accent: string; fill: string; halo: string; label: string }> = {
  asset: {
    accent: "var(--memory-node-asset)",
    fill: "var(--memory-node-asset-fill)",
    halo: "var(--memory-node-asset-halo)",
    label: "Asset",
  },
  chunk: {
    accent: "var(--memory-node-chunk)",
    fill: "var(--memory-node-chunk-fill)",
    halo: "var(--memory-node-chunk-halo)",
    label: "Chunk",
  },
  community: {
    accent: "var(--memory-node-community)",
    fill: "var(--memory-node-community-fill)",
    halo: "var(--memory-node-community-halo)",
    label: "Community",
  },
  document: {
    accent: "var(--memory-node-document)",
    fill: "var(--memory-node-document-fill)",
    halo: "var(--memory-node-document-halo)",
    label: "Document",
  },
  entity: {
    accent: "var(--memory-node-entity)",
    fill: "var(--memory-node-entity-fill)",
    halo: "var(--memory-node-entity-halo)",
    label: "Entity",
  },
  fact: {
    accent: "var(--memory-node-fact)",
    fill: "var(--memory-node-fact-fill)",
    halo: "var(--memory-node-fact-halo)",
    label: "Fact",
  },
  general: {
    accent: "var(--memory-node-general)",
    fill: "var(--memory-node-general-fill)",
    halo: "var(--memory-node-general-halo)",
    label: "General",
  },
  plaud: {
    accent: "var(--memory-node-plaud)",
    fill: "var(--memory-node-plaud-fill)",
    halo: "var(--memory-node-plaud-halo)",
    label: "Plaud",
  },
  project: {
    accent: "var(--memory-node-project)",
    fill: "var(--memory-node-project-fill)",
    halo: "var(--memory-node-project-halo)",
    label: "Project",
  },
  tool: {
    accent: "var(--memory-node-tool)",
    fill: "var(--memory-node-tool-fill)",
    halo: "var(--memory-node-tool-halo)",
    label: "Tool",
  },
  user_pref: {
    accent: "var(--memory-node-user)",
    fill: "var(--memory-node-user-fill)",
    halo: "var(--memory-node-user-halo)",
    label: "User preference",
  },
};

function hashString(value: string): number {
  let hash = 2166136261;
  for (let i = 0; i < value.length; i += 1) {
    hash ^= value.charCodeAt(i);
    hash = Math.imul(hash, 16777619);
  }
  return hash >>> 0;
}

function jitter(seed: string, amount: number): number {
  return ((hashString(seed) % 1000) / 1000 - 0.5) * amount;
}

function clamp(value: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, value));
}

function normalizeKey(value: string | undefined): string {
  return (value ?? "").trim().toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "");
}

function nodeKind(node: AgentHubMemoryNode): NodeKind {
  const category = normalizeKey(node.category);
  const type = normalizeKey(node.type);
  const key = category || type;

  if (key.includes("user_pref") || key.includes("preference")) return "user_pref";
  if (key.includes("community")) return "community";
  if (key.includes("project")) return "project";
  if (key.includes("tool")) return "tool";
  if (key.includes("plaud") || key.includes("transcript")) return "plaud";
  if (key.includes("document") || type === "document") return "document";
  if (key.includes("chunk") || type === "chunk") return "chunk";
  if (key.includes("asset") || type === "asset") return "asset";
  if (type === "entity") return "entity";
  if (type === "fact") return "fact";
  return "general";
}

function clusterKey(node: AgentHubMemoryNode): string {
  if (node.category) return node.category;
  if (node.type && node.type !== "fact") return node.type;
  const firstWord = node.label.trim().split(/\s+/)[0]?.toLowerCase();
  return firstWord || "memory";
}

function nodeWeight(node: AgentHubMemoryNode, degree: number): number {
  const raw = Number.isFinite(node.weight) ? Number(node.weight) : 1;
  return Math.max(raw, 1) + degree * 0.7;
}

function labelFor(node: AgentHubMemoryNode): string {
  return node.label.trim().replace(/\s+/g, " ");
}

function buildVisualEdges(
  nodes: AgentHubMemoryNode[],
  positions: Map<string, PositionedNode>,
  edges: AgentHubMemoryEdge[],
): AgentHubMemoryEdge[] {
  if (edges.length > 0) return edges;
  const grouped = new Map<string, AgentHubMemoryNode[]>();
  for (const node of nodes) {
    const key = clusterKey(node);
    grouped.set(key, [...(grouped.get(key) ?? []), node]);
  }
  const visualEdges: AgentHubMemoryEdge[] = [];
  for (const group of grouped.values()) {
    const sorted = [...group].sort((a, b) => {
      const pa = positions.get(a.id);
      const pb = positions.get(b.id);
      if (!pa || !pb) return 0;
      return pa.x - pb.x || pa.y - pb.y;
    });
    for (let i = 1; i < sorted.length; i += 1) {
      visualEdges.push({
        source: sorted[Math.max(0, i - 1)].id,
        target: sorted[i].id,
        type: "visual-cluster",
      });
    }
  }
  return visualEdges;
}

function relaxConstellation(nodes: PositionedNode[], edges: AgentHubMemoryEdge[], compact: boolean) {
  const byId = new Map(nodes.map((item) => [item.node.id, item]));
  const anchors = new Map(nodes.map((item) => [item.node.id, { x: item.x, y: item.y }]));
  const iterations = compact ? 46 : 76;
  const linkStrength = compact ? 0.01 : 0.011;
  const anchorStrength = compact ? 0.068 : 0.086;
  const collisionPad = compact ? 10 : 16;

  for (let iteration = 0; iteration < iterations; iteration += 1) {
    for (const item of nodes) {
      const anchor = anchors.get(item.node.id);
      if (!anchor) continue;
      item.x += (anchor.x - item.x) * anchorStrength;
      item.y += (anchor.y - item.y) * anchorStrength;
    }

    for (const edge of edges) {
      const source = byId.get(edge.source);
      const target = byId.get(edge.target);
      if (!source || !target) continue;
      const dx = target.x - source.x;
      const dy = target.y - source.y;
      const distance = Math.max(1, Math.hypot(dx, dy));
      const preferred = edge.type === "visual-cluster" ? (compact ? 108 : 154) : (compact ? 142 : 205);
      const pull = ((distance - preferred) / distance) * linkStrength;
      const fx = dx * pull;
      const fy = dy * pull;
      source.x += fx;
      source.y += fy;
      target.x -= fx;
      target.y -= fy;
    }

    for (let i = 0; i < nodes.length; i += 1) {
      for (let j = i + 1; j < nodes.length; j += 1) {
        const a = nodes[i];
        const b = nodes[j];
        const dx = b.x - a.x;
        const dy = b.y - a.y;
        const distance = Math.max(1, Math.hypot(dx, dy));
        const minDistance = a.r + b.r + collisionPad;
        if (distance >= minDistance) continue;
        const push = ((minDistance - distance) / distance) * 0.5;
        const fx = dx * push;
        const fy = dy * push;
        a.x -= fx;
        a.y -= fy;
        b.x += fx;
        b.y += fy;
      }
    }

    for (const item of nodes) {
      item.x = clamp(item.x, BOUNDS.minX, BOUNDS.maxX);
      item.y = clamp(item.y, BOUNDS.minY, BOUNDS.maxY);
    }
  }
}

function convexHull(points: Array<{ x: number; y: number }>): Array<{ x: number; y: number }> {
  if (points.length < 3) return points;
  const sorted = [...points].sort((a, b) => a.x - b.x || a.y - b.y);
  const cross = (o: { x: number; y: number }, a: { x: number; y: number }, b: { x: number; y: number }) =>
    (a.x - o.x) * (b.y - o.y) - (a.y - o.y) * (b.x - o.x);
  const lower: Array<{ x: number; y: number }> = [];
  for (const p of sorted) {
    while (lower.length >= 2 && cross(lower[lower.length - 2], lower[lower.length - 1], p) <= 0) lower.pop();
    lower.push(p);
  }
  const upper: Array<{ x: number; y: number }> = [];
  for (let i = sorted.length - 1; i >= 0; i--) {
    const p = sorted[i];
    while (upper.length >= 2 && cross(upper[upper.length - 2], upper[upper.length - 1], p) <= 0) upper.pop();
    upper.push(p);
  }
  lower.pop();
  upper.pop();
  return lower.concat(upper);
}

function expandHull(hull: Array<{ x: number; y: number }>, pad: number): string {
  if (hull.length < 2) return "";
  const cx = hull.reduce((s, p) => s + p.x, 0) / hull.length;
  const cy = hull.reduce((s, p) => s + p.y, 0) / hull.length;
  return hull
    .map((p) => {
      const dx = p.x - cx;
      const dy = p.y - cy;
      const d = Math.max(1, Math.hypot(dx, dy));
      return `${p.x + (dx / d) * pad},${p.y + (dy / d) * pad}`;
    })
    .join(" ");
}

function isEdgeConnected(edge: AgentHubMemoryEdge, nodeId: string | null) {
  return Boolean(nodeId && (edge.source === nodeId || edge.target === nodeId));
}

export function MemoryConstellation({
  className,
  compact = false,
  edges,
  nodes,
}: {
  className?: string;
  compact?: boolean;
  edges: AgentHubMemoryEdge[];
  nodes: AgentHubMemoryNode[];
}) {
  const [hoveredNodeId, setHoveredNodeId] = useState<string | null>(null);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const rawId = useId().replace(/:/g, "");
  const gridId = `memory-grid-${rawId}`;
  const glowId = `memory-glow-${rawId}`;
  const summaryId = `memory-summary-${rawId}`;

  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const panRef = useRef(pan);
  panRef.current = pan;
  const zoomRef = useRef(zoom);
  zoomRef.current = zoom;
  const dragRef = useRef<{ startX: number; startY: number; panX: number; panY: number } | null>(null);
  const svgRef = useRef<SVGSVGElement>(null);

  const handleWheel = useCallback((e: React.WheelEvent) => {
    e.preventDefault();
    const delta = e.deltaY > 0 ? 1.08 : 0.93;
    setZoom((z) => clamp(z * delta, 0.4, 3));
  }, []);

  const handlePointerDown = useCallback((e: React.PointerEvent) => {
    if (e.button !== 0) return;
    const target = e.target as Element;
    if (target.closest(".memory-constellation-node")) return;
    (e.currentTarget as Element).setPointerCapture(e.pointerId);
    dragRef.current = { startX: e.clientX, startY: e.clientY, panX: panRef.current.x, panY: panRef.current.y };
  }, []);

  const handlePointerMove = useCallback((e: React.PointerEvent) => {
    if (!dragRef.current) return;
    const svg = svgRef.current;
    if (!svg) return;
    const rect = svg.getBoundingClientRect();
    const z = zoomRef.current;
    const scaleX = (VIEW_WIDTH * z) / rect.width;
    const scaleY = (VIEW_HEIGHT * z) / rect.height;
    setPan({
      x: dragRef.current.panX - (e.clientX - dragRef.current.startX) * scaleX,
      y: dragRef.current.panY - (e.clientY - dragRef.current.startY) * scaleY,
    });
  }, []);

  const handlePointerUp = useCallback(() => {
    dragRef.current = null;
  }, []);

  const layout = useMemo(() => {
    const degree = new Map<string, number>();
    for (const edge of edges) {
      degree.set(edge.source, (degree.get(edge.source) ?? 0) + 1);
      degree.set(edge.target, (degree.get(edge.target) ?? 0) + 1);
    }
    const isolatedNodes = nodes
      .filter((node) => (degree.get(node.id) ?? 0) === 0)
      .sort((a, b) => nodeKind(a).localeCompare(nodeKind(b)) || labelFor(a).localeCompare(labelFor(b)));
    const isolatedRank = new Map(isolatedNodes.map((node, index) => [node.id, index]));

    const grouped = new Map<NodeKind, AgentHubMemoryNode[]>();
    for (const node of nodes) {
      const key = nodeKind(node);
      grouped.set(key, [...(grouped.get(key) ?? []), node]);
    }

    const sortedGroups = [...grouped.entries()].sort((a, b) => {
      const orderA = KIND_ORDER.indexOf(a[0]);
      const orderB = KIND_ORDER.indexOf(b[0]);
      return orderA - orderB || b[1].length - a[1].length;
    });
    const activeKinds = sortedGroups.map(([kind]) => kind);
    const kindAngles = new Map<NodeKind, number>();
    activeKinds.forEach((kind, index) => {
      kindAngles.set(kind, -0.18 + (index / Math.max(activeKinds.length, 1)) * Math.PI * 2);
    });

    const positioned: PositionedNode[] = [];

    sortedGroups.forEach(([kind, group]) => {
      const angleBase = kindAngles.get(kind) ?? 0;
      const angleBand = clamp((Math.PI * 2) / Math.max(activeKinds.length, 1) * 0.68, 0.42, 1.04);

      group
        .slice()
        .sort((a, b) => nodeWeight(b, degree.get(b.id) ?? 0) - nodeWeight(a, degree.get(a.id) ?? 0))
        .forEach((node, index) => {
          const nodeDegree = degree.get(node.id) ?? 0;
          const weight = nodeWeight(node, nodeDegree);
          const r = Math.min(compact ? 10 : 12, (compact ? 2.8 : 3) + Math.sqrt(weight) * (compact ? 1.1 : 1.2));
          const isolatedIndex = isolatedRank.get(node.id);
          const isolated = isolatedIndex !== undefined;
          const ratio = isolated
            ? isolatedIndex / Math.max(isolatedNodes.length, 1)
            : group.length <= 1
              ? 0.5
              : index / (group.length - 1);
          const angle = isolated
            ? -Math.PI / 2 + ratio * Math.PI * 2 + jitter(`${node.id}:isolated-angle`, 0.08)
            : angleBase +
              (ratio - 0.5) * angleBand +
              (index % 2 === 0 ? 1 : -1) * (0.06 + (hashString(node.id) % 9) / 180);
          const ring = isolated ? isolatedIndex % 3 : index % (compact ? 3 : 4);
          const orbit = isolated
            ? (compact ? 180 : 280) + ring * (compact ? 16 : 24)
            : (compact ? 120 : 190) + ring * (compact ? 34 : 50) + Math.floor(index / (compact ? 3 : 4)) * (compact ? 10 : 14);
          const weightedOrbit = isolated ? orbit : orbit - Math.min(weight, 18) * (compact ? 1.2 : 1.65);
          positioned.push({
            degree: nodeDegree,
            groupKey: kind,
            kind,
            node,
            opacity: Math.min(0.98, 0.62 + Math.min(weight, 12) * 0.032),
            r,
            x: clamp(
              CENTER_X + Math.cos(angle) * weightedOrbit * (compact ? 1.04 : 1.18) + jitter(`${node.id}:x`, compact ? 10 : 18),
              BOUNDS.minX,
              BOUNDS.maxX,
            ),
            y: clamp(
              CENTER_Y + Math.sin(angle) * weightedOrbit * (compact ? 0.82 : 0.8) + jitter(`${node.id}:y`, compact ? 10 : 18),
              BOUNDS.minY,
              BOUNDS.maxY,
            ),
            rank: 0,
          });
        });
    });

    const ranked = [...positioned].sort((a, b) => {
      const aw = nodeWeight(a.node, a.degree);
      const bw = nodeWeight(b.node, b.degree);
      return bw - aw || b.degree - a.degree || labelFor(a.node).localeCompare(labelFor(b.node));
    });
    ranked.forEach((item, rank) => {
      item.rank = rank;
    });

    const initialById = new Map(positioned.map((item) => [item.node.id, item]));
    const visualEdges = buildVisualEdges(nodes, initialById, edges);
    relaxConstellation(positioned, visualEdges, compact);

    const byId = new Map(positioned.map((item) => [item.node.id, item]));
    const kinds = new Map<NodeKind, number>();
    for (const item of positioned) {
      kinds.set(item.kind, (kinds.get(item.kind) ?? 0) + 1);
    }

    const clusterGroups = new Map<string, PositionedNode[]>();
    for (const item of positioned) {
      const key = clusterKey(item.node);
      clusterGroups.set(key, [...(clusterGroups.get(key) ?? []), item]);
    }
    const hulls: Array<{ key: string; kind: NodeKind; path: string }> = [];
    for (const [key, members] of clusterGroups) {
      if (members.length < 3) continue;
      const hull = convexHull(members.map((m) => ({ x: m.x, y: m.y })));
      if (hull.length < 3) continue;
      hulls.push({ key, kind: members[0].kind, path: expandHull(hull, 28) });
    }

    return {
      byId,
      edges: visualEdges,
      groups: [...kinds.entries()]
        .sort((a, b) => b[1] - a[1])
        .map(([kind, total]) => ({ kind, name: NODE_TONE[kind].label, total }))
        .slice(0, compact ? 5 : 9),
      hulls,
      positioned: [...positioned].sort((a, b) => a.r - b.r),
      ranked,
    };
  }, [compact, edges, nodes]);

  const activeNodeId = hoveredNodeId ?? selectedNodeId;
  const activeConnections = useMemo(() => {
    const connected = new Set<string>();
    if (!activeNodeId) return connected;
    connected.add(activeNodeId);
    for (const edge of layout.edges) {
      if (edge.source === activeNodeId) connected.add(edge.target);
      if (edge.target === activeNodeId) connected.add(edge.source);
    }
    return connected;
  }, [activeNodeId, layout.edges]);
  const activeNode = activeNodeId ? layout.byId.get(activeNodeId) ?? null : null;
  const activeEdgeTypes = useMemo(() => {
    if (!activeNodeId) return [] as Array<{ type: string; count: number }>;
    const counts = new Map<string, number>();
    for (const edge of layout.edges) {
      if (!isEdgeConnected(edge, activeNodeId)) continue;
      const label = edge.type === "visual-cluster" ? "visual" : edge.type.replace(/_/g, " ");
      counts.set(label, (counts.get(label) ?? 0) + 1);
    }
    return [...counts.entries()]
      .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
      .slice(0, 4)
      .map(([type, count]) => ({ type, count }));
  }, [activeNodeId, layout.edges]);
  const focusNode = activeNode ?? layout.ranked[0] ?? null;
  const displayedLinks = activeNode
    ? layout.edges.filter((edge) => isEdgeConnected(edge, activeNode.node.id)).length
    : layout.edges.length;
  const realLinks = edges.length || layout.edges.length;
  const graphStyle = {
    "--memory-bg": "color-mix(in srgb, var(--background-base) 92%, var(--midground-base))",
    "--memory-panel": "color-mix(in srgb, var(--midground-base) 6%, var(--background-base))",
    "--memory-panel-strong": "color-mix(in srgb, var(--midground-base) 10%, var(--background-base))",
    "--memory-grid": "color-mix(in srgb, var(--midground-base) 8%, transparent)",
    "--memory-edge": "color-mix(in srgb, var(--midground-base) 26%, transparent)",
    "--memory-edge-soft": "color-mix(in srgb, var(--midground-base) 14%, transparent)",
    "--memory-edge-active": "color-mix(in srgb, var(--color-primary) 72%, var(--midground-base))",
    "--memory-node-entity": "color-mix(in srgb, var(--color-primary) 82%, var(--midground-base))",
    "--memory-node-entity-fill": "color-mix(in srgb, var(--color-primary) 74%, var(--midground-base))",
    "--memory-node-entity-halo": "color-mix(in srgb, var(--color-primary) 25%, transparent)",
    "--memory-node-fact": "color-mix(in srgb, var(--color-success) 84%, var(--midground-base))",
    "--memory-node-fact-fill": "color-mix(in srgb, var(--color-success) 66%, var(--midground-base))",
    "--memory-node-fact-halo": "color-mix(in srgb, var(--color-success) 22%, transparent)",
    "--memory-node-document": "color-mix(in srgb, var(--color-warning) 82%, var(--midground-base))",
    "--memory-node-document-fill": "color-mix(in srgb, var(--color-warning) 66%, var(--midground-base))",
    "--memory-node-document-halo": "color-mix(in srgb, var(--color-warning) 23%, transparent)",
    "--memory-node-chunk": "color-mix(in srgb, var(--midground-base) 78%, var(--background-base))",
    "--memory-node-chunk-fill": "color-mix(in srgb, var(--midground-base) 62%, var(--background-base))",
    "--memory-node-chunk-halo": "color-mix(in srgb, var(--midground-base) 14%, transparent)",
    "--memory-node-community": "color-mix(in srgb, var(--color-primary) 48%, var(--color-success) 44%)",
    "--memory-node-community-fill": "color-mix(in srgb, var(--color-primary) 35%, var(--color-success) 38%)",
    "--memory-node-community-halo": "color-mix(in srgb, var(--color-primary) 20%, transparent)",
    "--memory-node-project": "color-mix(in srgb, var(--color-primary) 60%, var(--color-warning) 34%)",
    "--memory-node-project-fill": "color-mix(in srgb, var(--color-primary) 48%, var(--color-warning) 26%)",
    "--memory-node-project-halo": "color-mix(in srgb, var(--color-warning) 24%, transparent)",
    "--memory-node-user": "color-mix(in srgb, var(--color-warning) 72%, var(--color-success) 20%)",
    "--memory-node-user-fill": "color-mix(in srgb, var(--color-warning) 56%, var(--color-success) 18%)",
    "--memory-node-user-halo": "color-mix(in srgb, var(--color-warning) 22%, transparent)",
    "--memory-node-tool": "color-mix(in srgb, var(--color-success) 72%, var(--color-primary) 22%)",
    "--memory-node-tool-fill": "color-mix(in srgb, var(--color-success) 54%, var(--color-primary) 18%)",
    "--memory-node-tool-halo": "color-mix(in srgb, var(--color-success) 24%, transparent)",
    "--memory-node-plaud": "color-mix(in srgb, var(--color-primary) 45%, var(--midground-base))",
    "--memory-node-plaud-fill": "color-mix(in srgb, var(--color-primary) 34%, var(--midground-base))",
    "--memory-node-plaud-halo": "color-mix(in srgb, var(--color-primary) 18%, transparent)",
    "--memory-node-asset": "color-mix(in srgb, var(--color-destructive) 64%, var(--midground-base))",
    "--memory-node-asset-fill": "color-mix(in srgb, var(--color-destructive) 50%, var(--midground-base))",
    "--memory-node-asset-halo": "color-mix(in srgb, var(--color-destructive) 20%, transparent)",
    "--memory-node-general": "color-mix(in srgb, var(--midground-base) 86%, var(--color-primary) 12%)",
    "--memory-node-general-fill": "color-mix(in srgb, var(--midground-base) 68%, var(--color-primary) 10%)",
    "--memory-node-general-halo": "color-mix(in srgb, var(--midground-base) 16%, transparent)",
  } as CSSProperties;

  if (!nodes.length) {
    return (
      <div
        className={cn(
          "flex min-h-[30rem] items-center justify-center rounded-lg border border-dashed border-border bg-background/30 px-6 text-center text-sm text-muted-foreground",
          className,
        )}
      >
        No memory graph nodes yet. Session facts and entities will appear after memory processing.
      </div>
    );
  }

  return (
    <div
      style={graphStyle}
      onClick={() => setSelectedNodeId(null)}
      className={cn(
        "memory-constellation relative isolate min-h-[34rem] overflow-hidden rounded-md border border-[var(--page-border)] bg-[var(--memory-bg)] text-foreground",
        compact && "min-h-[18rem]",
        className,
      )}
    >
      <p id={summaryId} className="sr-only">
        Memory knowledge graph with {nodes.length} nodes and {realLinks} links. Use Tab to inspect prominent nodes.
        Press Enter to pin a node and reveal its connected memories.
      </p>
      <svg
        ref={svgRef}
        aria-label="Memory knowledge graph"
        aria-describedby={summaryId}
        className="absolute inset-0 h-full w-full cursor-grab active:cursor-grabbing"
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={handlePointerUp}
        onWheel={handleWheel}
        preserveAspectRatio="xMidYMid meet"
        role="img"
        viewBox={(() => {
          const baseW = VIEW_WIDTH + Math.max(0, Math.sqrt(nodes.length) - 8) * 18;
          const baseH = VIEW_HEIGHT + Math.max(0, Math.sqrt(nodes.length) - 8) * 12;
          const w = baseW * zoom;
          const h = baseH * zoom;
          const cx = VIEW_X + baseW / 2 + pan.x;
          const cy = VIEW_Y + baseH / 2 + pan.y;
          return `${cx - w / 2} ${cy - h / 2} ${w} ${h}`;
        })()}
      >
        <defs>
          <pattern id={gridId} width="48" height="48" patternUnits="userSpaceOnUse">
            <path d="M 48 0 L 0 0 0 48" fill="none" stroke="var(--memory-grid)" strokeWidth="0.8" />
          </pattern>
          <radialGradient id={glowId} cx="50%" cy="44%" r="62%">
            <stop offset="0%" stopColor="var(--memory-panel-strong)" />
            <stop offset="58%" stopColor="var(--memory-panel)" />
            <stop offset="100%" stopColor="var(--memory-bg)" />
          </radialGradient>
        </defs>
        <rect x="-40" y="-40" width={WIDTH + 80} height={HEIGHT + 80} fill={`url(#${glowId})`} />
        <rect x="-40" y="-40" width={WIDTH + 80} height={HEIGHT + 80} fill={`url(#${gridId})`} opacity="0.3" />
        {!compact && (
          <g className="memory-constellation-hulls">
            {layout.hulls.map((hull) => (
              <polygon
                key={hull.key}
                points={hull.path}
                fill={NODE_TONE[hull.kind].halo}
                stroke={NODE_TONE[hull.kind].accent}
                strokeWidth="0.8"
                strokeDasharray="4 3"
                opacity="0.18"
              />
            ))}
          </g>
        )}
        <g>
          {layout.edges.map((edge, index) => {
            const source = layout.byId.get(edge.source);
            const target = layout.byId.get(edge.target);
            if (!source || !target) return null;
            const visual = edge.type === "visual-cluster";
            const connected = isEdgeConnected(edge, activeNodeId);
            const dormant = Boolean(activeNodeId && !connected);
            const prominent = !activeNodeId && !visual && index < 8;
            return (
              <g key={`${edge.source}-${edge.target}-${index}`}>
                <line
                  className={cn(
                    "memory-constellation-edge",
                    prominent && "memory-constellation-edge-flow",
                    connected && "memory-constellation-edge-active",
                  )}
                  x1={source.x}
                  x2={target.x}
                  y1={source.y}
                  y2={target.y}
                  opacity={dormant ? 0.06 : connected ? 0.9 : visual ? 0.14 : 0.38}
                  stroke={connected ? "var(--memory-edge-active)" : visual ? "var(--memory-edge-soft)" : "var(--memory-edge)"}
                  strokeLinecap="round"
                  strokeWidth={connected ? 1.8 : visual ? 0.6 : 0.9}
                  style={{ "--memory-edge-delay": `${index * 46}ms` } as CSSProperties}
                />
                {connected && edge.type !== "visual-cluster" && (
                  <text
                    x={(source.x + target.x) / 2}
                    y={(source.y + target.y) / 2 - 5}
                    className="memory-constellation-edge-label"
                    fill="var(--memory-edge-active)"
                    textAnchor="middle"
                  >
                    {edge.type.replace(/_/g, " ")}
                  </text>
                )}
              </g>
            );
          })}
        </g>
        <g>
          {layout.positioned.map((item, index) => {
            const { degree, kind, node, opacity, r, rank, x, y } = item;
            const tone = NODE_TONE[kind];
            const active = activeNodeId === node.id;
            const connected = activeConnections.has(node.id);
            const linked = Boolean(activeNodeId && connected && !active);
            const muted = Boolean(activeNodeId && !connected);
            const label = labelFor(node);
            const showLabel = !compact && (active || linked || rank < 18 || (kind === "community" && rank < 24));
            const labelLeft = x > WIDTH - 240;
            return (
              <g
                key={node.id}
                aria-label={`${tone.label}: ${label}. ${degree} link${degree === 1 ? "" : "s"}.`}
                aria-pressed={selectedNodeId === node.id}
                className={cn(
                  "memory-constellation-node",
                  active && "is-active",
                  linked && "is-linked",
                  selectedNodeId === node.id && "is-pinned",
                  muted && "is-muted",
                )}
                focusable="true"
                onBlur={() => setHoveredNodeId(null)}
                onClick={(event) => {
                  event.stopPropagation();
                  setSelectedNodeId((current) => (current === node.id ? null : node.id));
                }}
                onFocus={() => setHoveredNodeId(node.id)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" || event.key === " ") {
                    event.preventDefault();
                    setSelectedNodeId((current) => (current === node.id ? null : node.id));
                  }
                  if (event.key === "Escape") {
                    setSelectedNodeId(null);
                    setHoveredNodeId(null);
                  }
                }}
                onMouseEnter={() => setHoveredNodeId(node.id)}
                onMouseLeave={() => setHoveredNodeId(null)}
                role="button"
                style={{ "--memory-node-delay": `${Math.min(index, 30) * 32}ms` } as CSSProperties}
                tabIndex={0}
              >
                <circle
                  cx={x}
                  cy={y}
                  className="memory-constellation-halo"
                  fill={tone.halo}
                  r={r * (active ? 2.2 : linked ? 1.9 : 1.6)}
                />
                <circle
                  cx={x}
                  cy={y}
                  className="memory-constellation-ring"
                  fill="none"
                  r={r * 1.2}
                  stroke={tone.accent}
                  strokeWidth={active ? 1.8 : 0.85}
                />
                <circle
                  cx={x}
                  cy={y}
                  className="memory-constellation-core"
                  fill={tone.fill}
                  opacity={muted ? 0.42 : opacity}
                  r={active ? r + 1.5 : r}
                  stroke={tone.accent}
                  strokeWidth={active ? 2 : 1}
                />
                {showLabel && (
                  <text
                    x={labelLeft ? x - r - 7 : x + r + 7}
                    y={y + 4}
                    className="memory-constellation-label"
                    fill="var(--midground)"
                    textAnchor={labelLeft ? "end" : "start"}
                  >
                    {label.length > 26 ? `${label.slice(0, 26)}...` : label}
                  </text>
                )}
                <title>{node.label}</title>
              </g>
            );
          })}
        </g>
      </svg>

      <div className="pointer-events-none absolute inset-x-0 top-0 flex items-start justify-between gap-4 p-4">
        <div className="rounded-lg border border-border/60 bg-background/95 px-3 py-2 shadow-sm">
          <div className="text-xs font-semibold text-foreground">Knowledge graph</div>
          <div className="mt-1 text-[0.72rem] text-muted-foreground">
            {nodes.length} nodes / {displayedLinks} {activeNode ? "related" : "links"}
          </div>
        </div>
        <div className="hidden max-w-[54%] flex-wrap justify-end gap-1.5 sm:flex">
          {layout.groups.map((group) => (
            <Badge
              key={group.kind}
              variant="outline"
              className="border-border/60 bg-background/95 text-[0.68rem] text-muted-foreground shadow-sm"
            >
              <span
                aria-hidden="true"
                className="mr-1.5 inline-block h-1.5 w-1.5 rounded-full"
                style={{ background: NODE_TONE[group.kind].accent }}
              />
              {group.name} {group.total}
            </Badge>
          ))}
        </div>
      </div>

      {focusNode && (
        <div className="pointer-events-none absolute inset-x-4 bottom-4 flex flex-col gap-2 sm:max-w-[28rem]">
          <div className="w-fit rounded border border-border/60 bg-background/95 px-2 py-0.5 font-mono-ui text-[0.68rem] uppercase tracking-[0.06em] text-muted-foreground shadow-sm">
            {activeNode && selectedNodeId === activeNode.node.id ? "Pinned" : activeNode ? "Inspecting" : "Strongest signal"}
          </div>
          <div className="rounded-lg border border-border/70 bg-background/95 p-3 shadow-sm">
            <div className="flex items-center gap-2">
              <span
                aria-hidden="true"
                className="h-2.5 w-2.5 shrink-0 rounded-full"
                style={{ background: NODE_TONE[focusNode.kind].accent }}
              />
              <span className="text-xs font-semibold text-foreground">
                {NODE_TONE[focusNode.kind].label}
              </span>
              <span className="text-[0.7rem] text-muted-foreground">
                {focusNode.degree} link{focusNode.degree === 1 ? "" : "s"}
              </span>
            </div>
            <div className="mt-1 line-clamp-2 text-sm leading-5 text-foreground">
              {labelFor(focusNode.node)}
            </div>
            {activeEdgeTypes.length > 0 && (
              <div className="mt-2 flex flex-wrap gap-1.5">
                {activeEdgeTypes.map((edge) => (
                  <span
                    key={edge.type}
                    className="rounded-full border border-border/60 bg-background/60 px-2 py-0.5 text-[0.66rem] text-muted-foreground"
                  >
                    {edge.type} {edge.count}
                  </span>
                ))}
              </div>
            )}
          </div>
        </div>
      )}

      <div className="font-mono-ui pointer-events-none absolute bottom-4 right-4 hidden text-[0.62rem] tracking-[0.04em] text-muted-foreground/60 sm:block">
        scroll to zoom · drag canvas to pan
      </div>
    </div>
  );
}
