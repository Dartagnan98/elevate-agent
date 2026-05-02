import { useMemo } from "react";
import type { AgentHubMemoryEdge, AgentHubMemoryNode } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

type PositionedNode = {
  node: AgentHubMemoryNode;
  x: number;
  y: number;
  r: number;
  opacity: number;
};

const WIDTH = 1200;
const HEIGHT = 760;
const GOLDEN_ANGLE = Math.PI * (3 - Math.sqrt(5));

const CLUSTER_CENTERS = [
  { x: 650, y: 320 },
  { x: 850, y: 290 },
  { x: 470, y: 245 },
  { x: 560, y: 520 },
  { x: 300, y: 380 },
  { x: 960, y: 500 },
  { x: 760, y: 560 },
  { x: 355, y: 570 },
  { x: 1010, y: 260 },
  { x: 215, y: 255 },
];

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
  const layout = useMemo(() => {
    const degree = new Map<string, number>();
    for (const edge of edges) {
      degree.set(edge.source, (degree.get(edge.source) ?? 0) + 1);
      degree.set(edge.target, (degree.get(edge.target) ?? 0) + 1);
    }

    const grouped = new Map<string, AgentHubMemoryNode[]>();
    for (const node of nodes) {
      const key = clusterKey(node);
      grouped.set(key, [...(grouped.get(key) ?? []), node]);
    }

    const sortedGroups = [...grouped.entries()].sort((a, b) => b[1].length - a[1].length);
    const positioned: PositionedNode[] = [];

    sortedGroups.forEach(([key, group], groupIndex) => {
      const center = CLUSTER_CENTERS[groupIndex % CLUSTER_CENTERS.length];
      const spread = Math.min(178, 34 + Math.sqrt(group.length) * 24);
      const keyJitter = hashString(key);

      group
        .slice()
        .sort((a, b) => nodeWeight(b, degree.get(b.id) ?? 0) - nodeWeight(a, degree.get(a.id) ?? 0))
        .forEach((node, index) => {
          const angle = index * GOLDEN_ANGLE + (keyJitter % 628) / 100;
          const radius = index === 0 ? 0 : Math.sqrt(index) * (spread / Math.sqrt(Math.max(group.length, 2)));
          const weight = nodeWeight(node, degree.get(node.id) ?? 0);
          const r = Math.min(13, 2.8 + Math.sqrt(weight) * 1.55);
          positioned.push({
            node,
            opacity: Math.min(0.94, 0.58 + Math.min(weight, 12) * 0.035),
            r,
            x: center.x + Math.cos(angle) * radius + jitter(`${node.id}:x`, 20),
            y: center.y + Math.sin(angle) * radius + jitter(`${node.id}:y`, 20),
          });
        });
    });

    const byId = new Map(positioned.map((item) => [item.node.id, item]));
    return {
      byId,
      edges: buildVisualEdges(nodes, byId, edges),
      groups: sortedGroups.map(([name, group]) => ({ name, total: group.length })).slice(0, 8),
      positioned,
    };
  }, [edges, nodes]);

  if (!nodes.length) {
    return (
      <div
        className={cn(
          "flex min-h-[30rem] items-center justify-center rounded-[1.25rem] border border-dashed border-border bg-[#1d1d1c] text-sm text-zinc-400",
          className,
        )}
      >
        No memory graph nodes yet. Session facts and entities will appear after memory processing.
      </div>
    );
  }

  return (
    <div
      className={cn(
        "relative isolate min-h-[34rem] overflow-hidden rounded-[1.25rem] bg-[#1e1e1d] text-zinc-200",
        "shadow-[inset_0_0_0_1px_rgba(255,255,255,0.055),0_30px_90px_rgba(0,0,0,0.28)]",
        compact && "min-h-[18rem]",
        className,
      )}
    >
      <svg
        aria-label="Memory knowledge graph"
        className="absolute inset-0 h-full w-full"
        preserveAspectRatio="xMidYMid slice"
        role="img"
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
      >
        <rect width={WIDTH} height={HEIGHT} fill="#1e1e1d" />
        <g opacity="0.76">
          {layout.edges.map((edge, index) => {
            const source = layout.byId.get(edge.source);
            const target = layout.byId.get(edge.target);
            if (!source || !target) return null;
            const visual = edge.type === "visual-cluster";
            return (
              <line
                key={`${edge.source}-${edge.target}-${index}`}
                x1={source.x}
                x2={target.x}
                y1={source.y}
                y2={target.y}
                stroke={visual ? "rgba(184,184,180,0.18)" : "rgba(206,206,202,0.28)"}
                strokeWidth={visual ? 0.75 : 1}
              />
            );
          })}
        </g>
        <g>
          {layout.positioned.map(({ node, opacity, r, x, y }) => {
            const isEntity = node.type === "entity";
            return (
              <g key={node.id}>
                <circle
                  cx={x}
                  cy={y}
                  fill={isEntity ? "rgba(218,218,214,0.88)" : "rgba(185,185,181,0.82)"}
                  opacity={opacity}
                  r={isEntity ? r + 1.5 : r}
                />
                <circle
                  cx={x}
                  cy={y}
                  fill="none"
                  opacity={isEntity ? 0.16 : 0.08}
                  r={(isEntity ? r + 1.5 : r) * 3.2}
                  stroke="rgba(230,230,225,0.42)"
                  strokeWidth="0.65"
                />
                <title>{node.label}</title>
              </g>
            );
          })}
        </g>
      </svg>

      <div className="pointer-events-none absolute inset-x-0 top-0 flex items-start justify-between gap-4 p-4">
        <div>
          <div className="text-xs font-medium text-zinc-300">Knowledge graph</div>
          <div className="mt-1 text-[0.72rem] text-zinc-500">
            {nodes.length} nodes / {edges.length || layout.edges.length} links
          </div>
        </div>
        <div className="hidden max-w-[48%] flex-wrap justify-end gap-1.5 sm:flex">
          {layout.groups.map((group) => (
            <Badge
              key={group.name}
              variant="outline"
              className="border-white/10 bg-white/[0.035] text-[0.68rem] text-zinc-400"
            >
              {group.name} {group.total}
            </Badge>
          ))}
        </div>
      </div>
    </div>
  );
}
