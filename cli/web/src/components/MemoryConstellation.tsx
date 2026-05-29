// MemoryConstellation — LIVE force-simulated knowledge graph (Obsidian-style).
//
// Ported verbatim from the memory-design prototype's constellation: a centered,
// disc-clamped force field where nodes float and settle into a big circle,
// draggable with spring neighbours, a frozen nearest-neighbour web mesh, hub
// pulse and flowing edges. Positions are driven imperatively via refs in a rAF
// loop; React owns hover / select / pan / zoom. Fed by the REAL memory graph
// (AgentHubMemoryNode[] / AgentHubMemoryEdge[]) — no mock data.
import { useCallback, useEffect, useId, useMemo, useRef, useState } from "react";
import type { CSSProperties, PointerEvent as ReactPointerEvent, WheelEvent as ReactWheelEvent } from "react";
import type { AgentHubMemoryEdge, AgentHubMemoryNode } from "@/lib/api";
import { cn } from "@/lib/utils";

const WIDTH = 1280;
const HEIGHT = 800;
const CENTER_X = 640;
const CENTER_Y = 400;

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

type Tone = { accent: string; fill: string; halo: string; label: string };

const NODE_TONE: Record<NodeKind, Tone> = {
  asset: { accent: "var(--memory-node-asset)", fill: "var(--memory-node-asset-fill)", halo: "var(--memory-node-asset-halo)", label: "Asset" },
  chunk: { accent: "var(--memory-node-chunk)", fill: "var(--memory-node-chunk-fill)", halo: "var(--memory-node-chunk-halo)", label: "Chunk" },
  community: { accent: "var(--memory-node-community)", fill: "var(--memory-node-community-fill)", halo: "var(--memory-node-community-halo)", label: "Community" },
  document: { accent: "var(--memory-node-document)", fill: "var(--memory-node-document-fill)", halo: "var(--memory-node-document-halo)", label: "Document" },
  entity: { accent: "var(--memory-node-entity)", fill: "var(--memory-node-entity-fill)", halo: "var(--memory-node-entity-halo)", label: "Entity" },
  fact: { accent: "var(--memory-node-fact)", fill: "var(--memory-node-fact-fill)", halo: "var(--memory-node-fact-halo)", label: "Fact" },
  general: { accent: "var(--memory-node-general)", fill: "var(--memory-node-general-fill)", halo: "var(--memory-node-general-halo)", label: "General" },
  plaud: { accent: "var(--memory-node-plaud)", fill: "var(--memory-node-plaud-fill)", halo: "var(--memory-node-plaud-halo)", label: "Plaud" },
  project: { accent: "var(--memory-node-project)", fill: "var(--memory-node-project-fill)", halo: "var(--memory-node-project-halo)", label: "Project" },
  tool: { accent: "var(--memory-node-tool)", fill: "var(--memory-node-tool-fill)", halo: "var(--memory-node-tool-halo)", label: "Tool" },
  user_pref: { accent: "var(--memory-node-user)", fill: "var(--memory-node-user-fill)", halo: "var(--memory-node-user-halo)", label: "User preference" },
};

type SimEdge = AgentHubMemoryEdge & { visual: boolean };

type NodeMeta = {
  node: AgentHubMemoryNode;
  kind: NodeKind;
  r: number;
  degree: number;
  weight: number;
  tone: Tone;
  cluster: string;
  rank: number;
};

type Vec = { x: number; y: number };

function hashString(value: string): number {
  let h = 2166136261;
  for (let i = 0; i < value.length; i += 1) {
    h ^= value.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}
function rand01(seed: string): number {
  return (hashString(seed) % 100000) / 100000;
}
function clamp(v: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, v));
}
function normalizeKey(value: string | undefined): string {
  return (value ?? "").trim().toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "");
}
function nodeKind(node: AgentHubMemoryNode): NodeKind {
  const key = normalizeKey(node.category) || normalizeKey(node.type);
  const type = normalizeKey(node.type);
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
  return node.label.trim().split(/\s+/)[0]?.toLowerCase() || "memory";
}
function nodeWeight(node: AgentHubMemoryNode, degree: number): number {
  const raw = Number.isFinite(node.weight) ? Number(node.weight) : 1;
  return Math.max(raw, 1) + degree * 0.7;
}
function labelFor(node: AgentHubMemoryNode): string {
  return node.label.trim().replace(/\s+/g, " ");
}
function convexHull(points: Vec[]): Vec[] {
  if (points.length < 3) return points;
  const sorted = [...points].sort((a, b) => a.x - b.x || a.y - b.y);
  const cross = (o: Vec, a: Vec, b: Vec) => (a.x - o.x) * (b.y - o.y) - (a.y - o.y) * (b.x - o.x);
  const lower: Vec[] = [];
  for (const p of sorted) {
    while (lower.length >= 2 && cross(lower[lower.length - 2], lower[lower.length - 1], p) <= 0) lower.pop();
    lower.push(p);
  }
  const upper: Vec[] = [];
  for (let i = sorted.length - 1; i >= 0; i--) {
    const p = sorted[i];
    while (upper.length >= 2 && cross(upper[upper.length - 2], upper[upper.length - 1], p) <= 0) upper.pop();
    upper.push(p);
  }
  lower.pop();
  upper.pop();
  return lower.concat(upper);
}
function expandHull(hull: Vec[], pad: number): string {
  if (hull.length < 2) return "";
  const cx0 = hull.reduce((s, p) => s + p.x, 0) / hull.length;
  const cy0 = hull.reduce((s, p) => s + p.y, 0) / hull.length;
  return hull
    .map((p) => {
      const dx = p.x - cx0;
      const dy = p.y - cy0;
      const d = Math.max(1, Math.hypot(dx, dy));
      return `${(p.x + (dx / d) * pad).toFixed(1)},${(p.y + (dy / d) * pad).toFixed(1)}`;
    })
    .join(" ");
}
function isEdgeConnected(edge: AgentHubMemoryEdge, id: string | null): boolean {
  return Boolean(id && (edge.source === id || edge.target === id));
}
function linkPref(edge: SimEdge, compact: boolean): number {
  if (edge.type === "part_of") return compact ? 46 : 72; // airy chunk starbursts
  if (edge.visual) return compact ? 110 : 170;
  if (edge.type === "member_of") return compact ? 150 : 230;
  return compact ? 185 : 285;
}

// Cluster nodes that have no real edges into visual-cluster links so isolated
// nodes still settle near their kin instead of stacking dead-centre.
function buildVisualEdges(nodes: AgentHubMemoryNode[], edges: AgentHubMemoryEdge[]): AgentHubMemoryEdge[] {
  if (edges.length > 0) return edges;
  const grouped = new Map<string, AgentHubMemoryNode[]>();
  for (const node of nodes) {
    const key = clusterKey(node);
    grouped.set(key, [...(grouped.get(key) ?? []), node]);
  }
  const visual: AgentHubMemoryEdge[] = [];
  for (const group of grouped.values()) {
    for (let i = 1; i < group.length; i += 1) {
      visual.push({ source: group[i - 1].id, target: group[i].id, type: "visual-cluster" });
    }
  }
  return visual;
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
  const [pan, setPan] = useState<Vec>({ x: 0, y: 0 });
  const panRef = useRef(pan);
  panRef.current = pan;
  const zoomRef = useRef(zoom);
  zoomRef.current = zoom;
  const viewBoxRef = useRef({ x: 0, y: 0, w: WIDTH, h: HEIGHT });
  const svgRef = useRef<SVGSVGElement>(null);
  const panDragRef = useRef<{ startX: number; startY: number; panX: number; panY: number } | null>(null);

  // ── static layout meta ──
  const base = useMemo(() => {
    const realEdges = buildVisualEdges(nodes, edges);
    const n = nodes.length;
    const R = clamp(300 + Math.sqrt(n) * 40, 420, 1150);
    const degree = new Map<string, number>();
    for (const e of realEdges) {
      degree.set(e.source, (degree.get(e.source) ?? 0) + 1);
      degree.set(e.target, (degree.get(e.target) ?? 0) + 1);
    }

    const meta = new Map<string, NodeMeta>();
    const seeds = new Map<string, Vec>();
    for (const node of nodes) {
      const d = degree.get(node.id) ?? 0;
      const w = nodeWeight(node, d);
      const kind = nodeKind(node);
      // Real memory graphs are mostly low-degree leaf nodes (chunks/facts/docs),
      // so the prototype's small base radius rendered them as near-invisible
      // specks. Bump the base + minimum so every node is a clearly visible dot
      // (the design's mock data was fat/high-degree and didn't hit this floor).
      const r = clamp(
        (compact ? 5 : 7) + Math.sqrt(d) * (compact ? 1.8 : 3) + Math.sqrt(Number.isFinite(node.weight) ? node.weight : 1) * 0.8,
        compact ? 5 : 10,
        compact ? 14 : 26,
      );
      const a = rand01(`${node.id}:a`) * Math.PI * 2;
      const pullIn = clamp(1 - Math.min(w, 16) / 40, 0.55, 1);
      const rr = (0.4 + Math.sqrt(rand01(`${node.id}:r`)) * 0.58) * R * pullIn;
      seeds.set(node.id, { x: CENTER_X + Math.cos(a) * rr, y: CENTER_Y + Math.sin(a) * rr });
      meta.set(node.id, { node, kind, r, degree: d, weight: w, tone: NODE_TONE[kind], cluster: clusterKey(node), rank: 0 });
    }

    const ranked = [...meta.values()].sort(
      (a, b) => b.weight - a.weight || b.degree - a.degree || labelFor(a.node).localeCompare(labelFor(b.node)),
    );
    ranked.forEach((m, i) => {
      m.rank = i;
    });

    const simEdges: SimEdge[] = realEdges.map((e) => ({ ...e, visual: e.type === "visual-cluster" }));

    const kindsCount = new Map<NodeKind, number>();
    for (const m of meta.values()) kindsCount.set(m.kind, (kindsCount.get(m.kind) ?? 0) + 1);
    const groups = [...kindsCount.entries()]
      .sort((a, b) => b[1] - a[1])
      .map(([kind, total]) => ({ kind, name: NODE_TONE[kind].label, total }))
      .slice(0, compact ? 5 : 9);

    let hulls: Array<{ key: string; kind: NodeKind; ids: string[] }> = [];
    if (!compact && n <= 90) {
      const cm = new Map<string, string[]>();
      for (const m of meta.values()) cm.set(m.cluster, [...(cm.get(m.cluster) ?? []), m.node.id]);
      hulls = [...cm.entries()]
        .filter(([, ids]) => ids.length >= 3)
        .map(([key, ids]) => ({ key, kind: meta.get(ids[0])!.kind, ids }));
    }

    return { meta, seeds, ranked, edges: simEdges, hulls, groups, order: [...meta.keys()], R };
  }, [compact, edges, nodes]);

  const simRef = useRef<{ pos: Map<string, Vec>; vel: Map<string, Vec>; alpha: number } | null>(null);
  const meshPoolRef = useRef<Array<SVGLineElement | null>>([]);
  const meshPairsRef = useRef<Array<[number, number]>>([]);
  const frameRef = useRef(0);
  const activeIdRef = useRef<string | null>(null);
  const nodeElRef = useRef(new Map<string, SVGGElement>());
  const labelElRef = useRef(new Map<string, SVGTextElement>());
  const edgeElRef = useRef(new Map<number, SVGLineElement>());
  const edgeLabelElRef = useRef(new Map<number, SVGTextElement>());
  const hullElRef = useRef(new Map<string, SVGPolygonElement>());
  const edgesGroupRef = useRef<SVGGElement>(null);
  const dragNodeRef = useRef<{ id: string; x: number; y: number } | null>(null);
  const growRef = useRef({ start: 0, dur: 520, stagger: 700 });

  useEffect(() => {
    const pos = new Map<string, Vec>();
    const vel = new Map<string, Vec>();
    for (const id of base.order) {
      const s = base.seeds.get(id)!;
      pos.set(id, { x: s.x, y: s.y });
      vel.set(id, { x: 0, y: 0 });
    }
    simRef.current = { pos, vel, alpha: 1 };
    growRef.current = { start: performance.now(), dur: 520, stagger: 700 }; // fast populate on load
  }, [base]);

  const replay = useCallback(() => {
    const sim = simRef.current;
    if (!sim) return;
    for (const id of base.order) {
      const s = base.seeds.get(id)!;
      sim.pos.set(id, { x: s.x, y: s.y });
      sim.vel.set(id, { x: 0, y: 0 });
    }
    sim.alpha = 1;
    growRef.current = { start: performance.now(), dur: 1500, stagger: 2400 }; // slower, invokable
  }, [base]);

  useEffect(() => {
    let raf = 0;
    const ids = base.order;
    const metaArr = ids.map((id) => base.meta.get(id)!);
    const R = base.R;

    function step() {
      const sim = simRef.current;
      if (!sim) {
        raf = requestAnimationFrame(step);
        return;
      }
      const { pos, vel } = sim;
      const now = performance.now();
      const grow = growRef.current;
      const globalGrow = clamp((now - grow.start) / (grow.dur + grow.stagger), 0, 1);
      if (edgesGroupRef.current) edgesGroupRef.current.setAttribute("opacity", globalGrow.toFixed(3));
      const alpha = Math.max(sim.alpha, dragNodeRef.current ? 0.6 : 0);

      // Once the graph has settled and finished growing (and nothing is being
      // dragged), STOP running the O(n^2) physics every frame — it was the main
      // source of the "glitchy"/janky feel. Positions are static; hover/select
      // highlighting is pure CSS, and pan/zoom re-render via React, so none of
      // that needs the sim. Drag and Replay re-arm alpha and resume the loop.
      if (alpha === 0 && globalGrow >= 1) {
        raf = requestAnimationFrame(step);
        return;
      }

      // link springs
      for (const e of base.edges) {
        const a = pos.get(e.source);
        const b = pos.get(e.target);
        if (!a || !b) continue;
        const dx = b.x - a.x;
        const dy = b.y - a.y;
        const dist = Math.max(1, Math.hypot(dx, dy));
        const pref = linkPref(e, compact);
        const k = (e.type === "part_of" ? 0.03 : e.visual ? 0.01 : 0.015) * alpha;
        const f = ((dist - pref) / dist) * k;
        const fx = dx * f;
        const fy = dy * f;
        const va = vel.get(e.source)!;
        const vb = vel.get(e.target)!;
        va.x += fx;
        va.y += fy;
        vb.x -= fx;
        vb.y -= fy;
      }
      // charge repulsion + collision
      for (let i = 0; i < ids.length; i += 1) {
        const A = pos.get(ids[i])!;
        const ra = metaArr[i].r;
        for (let j = i + 1; j < ids.length; j += 1) {
          const B = pos.get(ids[j])!;
          let dx = B.x - A.x;
          let dy = B.y - A.y;
          let dist = Math.hypot(dx, dy);
          if (dist > 420) continue;
          if (dist < 0.01) {
            dx = 0.6;
            dy = rand01(ids[i] + ids[j]) - 0.5;
            dist = 0.7;
          }
          const ux = dx / dist;
          const uy = dy / dist;
          const rep = (6200 / (dist * dist)) * alpha;
          const va = vel.get(ids[i])!;
          const vb = vel.get(ids[j])!;
          va.x -= ux * rep;
          va.y -= uy * rep;
          vb.x += ux * rep;
          vb.y += uy * rep;
          const minD = ra + metaArr[j].r + 18;
          if (dist < minD) {
            const push = (minD - dist) * 0.22 * Math.max(alpha, 0.12);
            va.x -= ux * push;
            va.y -= uy * push;
            vb.x += ux * push;
            vb.y += uy * push;
          }
        }
      }
      // centre gravity (keeps the disc) — fades with alpha so the graph SETTLES
      const g = 0.0009 * alpha;
      for (let i = 0; i < ids.length; i += 1) {
        const v = vel.get(ids[i])!;
        const p = pos.get(ids[i])!;
        v.x += (CENTER_X - p.x) * g;
        v.y += (CENTER_Y - p.y) * g;
      }
      // integrate + radial disc clamp
      const drag = dragNodeRef.current;
      for (let i = 0; i < ids.length; i += 1) {
        const id = ids[i];
        const p = pos.get(id)!;
        const v = vel.get(id)!;
        if (drag && drag.id === id) {
          p.x = drag.x;
          p.y = drag.y;
          v.x = 0;
          v.y = 0;
          continue;
        }
        v.x *= 0.88;
        v.y *= 0.88;
        const sp = Math.hypot(v.x, v.y);
        if (sp > 12) {
          v.x = (v.x / sp) * 12;
          v.y = (v.y / sp) * 12;
        }
        p.x += v.x;
        p.y += v.y;
        const dx = p.x - CENTER_X;
        const dy = p.y - CENTER_Y;
        const d = Math.hypot(dx, dy);
        if (d > R) {
          p.x = CENTER_X + (dx / d) * R;
          p.y = CENTER_Y + (dy / d) * R;
          v.x *= 0.5;
          v.y *= 0.5;
        }
      }
      sim.alpha = sim.alpha * 0.965; // settle quickly (was 0.992 → ~12s of motion)
      if (sim.alpha < 0.02) sim.alpha = 0;

      // ── web mesh: connect each node to its nearest neighbours (frozen once settled) ──
      frameRef.current += 1;
      const meshLive = sim.alpha > 0.05 || meshPairsRef.current.length === 0;
      if (meshLive && frameRef.current % 6 === 0) {
        const K = 10;
        const MAXD = 400;
        const seen = new Set<string>();
        const out: Array<[number, number]> = [];
        for (let i = 0; i < ids.length; i += 1) {
          const A = pos.get(ids[i])!;
          const best: Array<{ j: number; d: number }> = [];
          for (let j = 0; j < ids.length; j += 1) {
            if (i === j) continue;
            const B = pos.get(ids[j])!;
            const d = Math.hypot(B.x - A.x, B.y - A.y);
            if (d > MAXD) continue;
            if (best.length < K) {
              best.push({ j, d });
              best.sort((a, b) => a.d - b.d);
            } else if (d < best[K - 1].d) {
              best[K - 1] = { j, d };
              best.sort((a, b) => a.d - b.d);
            }
          }
          for (const b of best) {
            const key = i < b.j ? `${i}_${b.j}` : `${b.j}_${i}`;
            if (!seen.has(key)) {
              seen.add(key);
              out.push([i, b.j]);
            }
          }
        }
        out.sort((p, q) => p[0] - q[0] || p[1] - q[1]); // stable slot ordering → no teleport flicker
        meshPairsRef.current = out.slice(0, meshPoolRef.current.length);
      }
      {
        const pairs = meshPairsRef.current;
        const pool = meshPoolRef.current;
        const dim = activeIdRef.current ? 0.06 : 1;
        for (let i = 0; i < pool.length; i += 1) {
          const ln = pool[i];
          if (!ln) continue;
          const pair = pairs[i];
          if (!pair) {
            ln.setAttribute("opacity", "0");
            continue;
          }
          const A = pos.get(ids[pair[0]]);
          const B = pos.get(ids[pair[1]]);
          if (!A || !B) {
            ln.setAttribute("opacity", "0");
            continue;
          }
          ln.setAttribute("x1", A.x.toFixed(2));
          ln.setAttribute("y1", A.y.toFixed(2));
          ln.setAttribute("x2", B.x.toFixed(2));
          ln.setAttribute("y2", B.y.toFixed(2));
          const d = Math.hypot(B.x - A.x, B.y - A.y);
          const fade = clamp(1 - d / 400, 0, 1);
          ln.setAttribute("opacity", (globalGrow * (0.6 + fade * 0.4) * dim).toFixed(3));
        }
      }

      // ── paint ──
      for (let i = 0; i < ids.length; i += 1) {
        const id = ids[i];
        const p = pos.get(id)!;
        const m = metaArr[i];
        const gEl = nodeElRef.current.get(id);
        if (gEl) {
          const delay = (m.rank / ids.length) * grow.stagger;
          const gt = clamp((now - grow.start - delay) / grow.dur, 0, 1);
          const sc = 0.02 + (1 - Math.pow(1 - gt, 3)) * 0.98;
          gEl.setAttribute("transform", `translate(${p.x.toFixed(2)} ${p.y.toFixed(2)}) scale(${sc.toFixed(3)})`);
        }
        const lab = labelElRef.current.get(id);
        if (lab) {
          const left = p.x > CENTER_X + R * 0.55;
          lab.setAttribute("x", (left ? -(m.r + 7) : m.r + 7).toFixed(1));
          lab.setAttribute("text-anchor", left ? "end" : "start");
        }
      }
      for (const [idx, line] of edgeElRef.current) {
        const e = base.edges[idx];
        if (!e || !line) continue;
        const a = pos.get(e.source);
        const b = pos.get(e.target);
        if (!a || !b) continue;
        line.setAttribute("x1", a.x.toFixed(2));
        line.setAttribute("y1", a.y.toFixed(2));
        line.setAttribute("x2", b.x.toFixed(2));
        line.setAttribute("y2", b.y.toFixed(2));
        const tx = edgeLabelElRef.current.get(idx);
        if (tx) {
          tx.setAttribute("x", ((a.x + b.x) / 2).toFixed(1));
          tx.setAttribute("y", ((a.y + b.y) / 2 - 5).toFixed(1));
        }
      }
      for (const h of base.hulls) {
        const poly = hullElRef.current.get(h.key);
        if (!poly) continue;
        const pts = h.ids.map((id) => pos.get(id)).filter((p): p is Vec => Boolean(p));
        if (pts.length >= 3) poly.setAttribute("points", expandHull(convexHull(pts.map((p) => ({ x: p.x, y: p.y }))), 28));
      }
      raf = requestAnimationFrame(step);
    }
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, [base, compact]);

  const activeNodeId = hoveredNodeId ?? selectedNodeId;
  activeIdRef.current = activeNodeId;
  const activeConnections = useMemo(() => {
    const c = new Set<string>();
    if (!activeNodeId) return c;
    c.add(activeNodeId);
    for (const e of base.edges) {
      if (e.source === activeNodeId) c.add(e.target);
      if (e.target === activeNodeId) c.add(e.source);
    }
    return c;
  }, [activeNodeId, base.edges]);
  const activeMeta = activeNodeId ? base.meta.get(activeNodeId) ?? null : null;
  const activeEdgeTypes = useMemo(() => {
    if (!activeNodeId) return [] as Array<{ type: string; count: number }>;
    const counts = new Map<string, number>();
    for (const e of base.edges) {
      if (!isEdgeConnected(e, activeNodeId)) continue;
      const l = e.visual ? "visual" : e.type.replace(/_/g, " ");
      counts.set(l, (counts.get(l) ?? 0) + 1);
    }
    return [...counts.entries()]
      .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
      .slice(0, 4)
      .map(([type, count]) => ({ type, count }));
  }, [activeNodeId, base.edges]);
  const focusMeta = activeMeta ?? base.ranked[0] ?? null;
  const realLinks = edges.length;
  const displayedLinks = activeMeta ? base.edges.filter((e) => isEdgeConnected(e, activeNodeId)).length : realLinks;

  const handleWheel = useCallback((e: ReactWheelEvent) => {
    const d = e.deltaY > 0 ? 1.08 : 0.93;
    setZoom((z) => clamp(z * d, 0.35, 3.5));
  }, []);
  const clientToWorld = useCallback((clientX: number, clientY: number): Vec => {
    const svg = svgRef.current;
    if (!svg) return { x: 0, y: 0 };
    const rect = svg.getBoundingClientRect();
    const vb = viewBoxRef.current;
    const scale = Math.min(rect.width / vb.w, rect.height / vb.h);
    const offX = (rect.width - vb.w * scale) / 2;
    const offY = (rect.height - vb.h * scale) / 2;
    return { x: vb.x + (clientX - rect.left - offX) / scale, y: vb.y + (clientY - rect.top - offY) / scale };
  }, []);
  const handlePointerDown = useCallback((e: ReactPointerEvent) => {
    if (e.button !== 0) return;
    const target = e.target as Element;
    if (target.closest && target.closest(".memory-constellation-node")) return;
    (e.currentTarget as Element).setPointerCapture(e.pointerId);
    panDragRef.current = { startX: e.clientX, startY: e.clientY, panX: panRef.current.x, panY: panRef.current.y };
  }, []);
  const handlePointerMove = useCallback(
    (e: ReactPointerEvent) => {
      if (dragNodeRef.current) {
        const w = clientToWorld(e.clientX, e.clientY);
        dragNodeRef.current.x = w.x;
        dragNodeRef.current.y = w.y;
        return;
      }
      if (!panDragRef.current) return;
      const svg = svgRef.current;
      if (!svg) return;
      const rect = svg.getBoundingClientRect();
      const vb = viewBoxRef.current;
      const sx = vb.w / rect.width;
      const sy = vb.h / rect.height;
      setPan({
        x: panDragRef.current.panX - (e.clientX - panDragRef.current.startX) * sx,
        y: panDragRef.current.panY - (e.clientY - panDragRef.current.startY) * sy,
      });
    },
    [clientToWorld],
  );
  const handlePointerUp = useCallback(() => {
    panDragRef.current = null;
    if (dragNodeRef.current) {
      if (simRef.current) simRef.current.alpha = 0.5;
      dragNodeRef.current = null;
    }
  }, []);
  const startNodeDrag = useCallback((e: ReactPointerEvent, id: string) => {
    e.stopPropagation();
    const sim = simRef.current;
    if (!sim) return;
    const p = sim.pos.get(id);
    if (!p) return;
    dragNodeRef.current = { id, x: p.x, y: p.y };
    if (svgRef.current) svgRef.current.setPointerCapture(e.pointerId);
  }, []);

  const graphStyle = {
    "--memory-bg": "color-mix(in srgb, var(--background-base) 92%, var(--midground-base))",
    "--memory-panel": "color-mix(in srgb, var(--midground-base) 6%, var(--background-base))",
    "--memory-panel-strong": "color-mix(in srgb, var(--midground-base) 10%, var(--background-base))",
    "--memory-grid": "color-mix(in srgb, var(--midground-base) 8%, transparent)",
    "--memory-edge": "color-mix(in srgb, var(--midground-base) 26%, transparent)",
    "--memory-edge-soft": "color-mix(in srgb, var(--midground-base) 12%, transparent)",
    "--memory-edge-active": "color-mix(in srgb, #D8DBE2 80%, var(--midground-base))",
    // Node tones are the design prototype's exact cool-silver palette — a
    // uniform constellation, NOT hue-tinted. (Earlier builds keyed entity/
    // community/project/plaud off --color-primary for a hue swatch; that made
    // entities render blue and diverged from the design, so it's reverted.)
    "--memory-node-entity": "#CBD0DE",
    "--memory-node-entity-fill": "#9AA0AE",
    "--memory-node-entity-halo": "color-mix(in srgb, var(--midground-base) 22%, transparent)",
    "--memory-node-fact": "#C2C7D2",
    "--memory-node-fact-fill": "#9096A2",
    "--memory-node-fact-halo": "color-mix(in srgb, var(--midground-base) 20%, transparent)",
    "--memory-node-document": "#CBD0DE",
    "--memory-node-document-fill": "#9AA0AE",
    "--memory-node-document-halo": "color-mix(in srgb, var(--midground-base) 22%, transparent)",
    "--memory-node-chunk": "color-mix(in srgb, var(--midground-base) 78%, var(--background-base))",
    "--memory-node-chunk-fill": "color-mix(in srgb, var(--midground-base) 60%, var(--background-base))",
    "--memory-node-chunk-halo": "color-mix(in srgb, var(--midground-base) 13%, transparent)",
    "--memory-node-community": "#D8DBE2",
    "--memory-node-community-fill": "#A6ABB8",
    "--memory-node-community-halo": "color-mix(in srgb, var(--midground-base) 24%, transparent)",
    "--memory-node-project": "#CBD0DE",
    "--memory-node-project-fill": "#9AA0AE",
    "--memory-node-project-halo": "color-mix(in srgb, var(--midground-base) 22%, transparent)",
    "--memory-node-user": "#C2C7D2",
    "--memory-node-user-fill": "#9096A2",
    "--memory-node-user-halo": "color-mix(in srgb, var(--midground-base) 20%, transparent)",
    "--memory-node-tool": "#C2C7D2",
    "--memory-node-tool-fill": "#9096A2",
    "--memory-node-tool-halo": "color-mix(in srgb, var(--midground-base) 20%, transparent)",
    "--memory-node-plaud": "color-mix(in srgb, var(--midground-base) 80%, var(--background-base))",
    "--memory-node-plaud-fill": "color-mix(in srgb, var(--midground-base) 62%, var(--background-base))",
    "--memory-node-plaud-halo": "color-mix(in srgb, var(--midground-base) 14%, transparent)",
    "--memory-node-asset": "#C2C7D2",
    "--memory-node-asset-fill": "#9096A2",
    "--memory-node-asset-halo": "color-mix(in srgb, var(--midground-base) 20%, transparent)",
    "--memory-node-general": "color-mix(in srgb, var(--midground-base) 86%, #fff 6%)",
    "--memory-node-general-fill": "color-mix(in srgb, var(--midground-base) 66%, var(--background-base))",
    "--memory-node-general-halo": "color-mix(in srgb, var(--midground-base) 16%, transparent)",
  } as CSSProperties;

  const side = 2 * (base.R + 60);
  const meshMax = Math.min(base.order.length * 10, 3000);
  const meshLines = useMemo(
    () =>
      Array.from({ length: meshMax }).map((_, i) => (
        <line
          key={i}
          ref={(el) => {
            if (el) meshPoolRef.current[i] = el;
          }}
          className="memory-constellation-mesh-line"
          opacity="0"
        />
      )),
    [meshMax],
  );
  const vbW = side * zoom;
  const vbH = side * zoom;
  const vbX = CENTER_X + pan.x - vbW / 2;
  const vbY = CENTER_Y + pan.y - vbH / 2;
  viewBoxRef.current = { x: vbX, y: vbY, w: vbW, h: vbH };

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
    <div style={graphStyle} onClick={() => setSelectedNodeId(null)} className={cn("memory-constellation", className)}>
      <p id={summaryId} className="sr-only">
        Memory knowledge graph with {nodes.length} nodes and {realLinks} links. Drag nodes to reposition, scroll to zoom,
        drag the canvas to pan.
      </p>
      <svg
        ref={svgRef}
        aria-label="Memory knowledge graph"
        aria-describedby={summaryId}
        className="memory-svg"
        role="img"
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={handlePointerUp}
        onWheel={handleWheel}
        preserveAspectRatio="xMidYMid meet"
        viewBox={`${vbX} ${vbY} ${vbW} ${vbH}`}
      >
        <defs>
          <pattern id={gridId} width="48" height="48" patternUnits="userSpaceOnUse">
            <path d="M 48 0 L 0 0 0 48" fill="none" stroke="var(--memory-grid)" strokeWidth="0.8" />
          </pattern>
          <radialGradient id={glowId} cx="50%" cy="50%" r="62%">
            <stop offset="0%" stopColor="var(--memory-panel-strong)" />
            <stop offset="58%" stopColor="var(--memory-panel)" />
            <stop offset="100%" stopColor="var(--memory-bg)" />
          </radialGradient>
        </defs>
        <rect x={CENTER_X - side} y={CENTER_Y - side} width={side * 2} height={side * 2} fill={`url(#${glowId})`} />
        <rect x={CENTER_X - side} y={CENTER_Y - side} width={side * 2} height={side * 2} fill={`url(#${gridId})`} opacity="0.25" />

        <g className="memory-constellation-mesh">{meshLines}</g>

        {base.hulls.length > 0 && (
          <g className="memory-constellation-hulls">
            {base.hulls.map((h) => (
              <polygon
                key={h.key}
                ref={(el) => {
                  if (el) hullElRef.current.set(h.key, el);
                }}
                fill={NODE_TONE[h.kind].halo}
                stroke={NODE_TONE[h.kind].accent}
                strokeWidth="0.8"
                strokeDasharray="4 3"
                opacity="0.16"
              />
            ))}
          </g>
        )}

        <g ref={edgesGroupRef}>
          {base.edges.map((edge, index) => {
            const connected = isEdgeConnected(edge, activeNodeId);
            const dormant = Boolean(activeNodeId && !connected);
            const prominent = !activeNodeId && !edge.visual && index < 14;
            return (
              <g key={`${edge.source}-${edge.target}-${index}`}>
                <line
                  ref={(el) => {
                    if (el) edgeElRef.current.set(index, el);
                  }}
                  className={cn(
                    "memory-constellation-edge",
                    prominent && "memory-constellation-edge-flow",
                    connected && "memory-constellation-edge-active",
                  )}
                  opacity={dormant ? 0.04 : connected ? 0.95 : edge.visual ? 0.1 : 0.3}
                  stroke={connected ? "var(--memory-edge-active)" : edge.visual ? "var(--memory-edge-soft)" : "var(--memory-edge)"}
                  strokeLinecap="round"
                  strokeWidth={connected ? 1.9 : edge.visual ? 0.6 : 0.8}
                  style={{ "--memory-edge-delay": `${index * 30}ms` } as CSSProperties}
                />
                {connected && !edge.visual && (
                  <text
                    ref={(el) => {
                      if (el) edgeLabelElRef.current.set(index, el);
                    }}
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
          {base.ranked.map((m) => {
            const { node, r, degree, tone } = m;
            const active = activeNodeId === node.id;
            const connected = activeConnections.has(node.id);
            const linked = Boolean(activeNodeId && connected && !active);
            const muted = Boolean(activeNodeId && !connected);
            const label = labelFor(node);
            const showLabel = active || linked;
            const opacity = Math.min(0.98, 0.6 + Math.min(m.weight, 12) * 0.034);
            return (
              <g
                key={node.id}
                ref={(el) => {
                  if (el) nodeElRef.current.set(node.id, el);
                }}
                className={cn(
                  "memory-constellation-node",
                  active && "is-active",
                  linked && "is-linked",
                  selectedNodeId === node.id && "is-pinned",
                  muted && "is-muted",
                )}
                role="button"
                tabIndex={0}
                aria-label={`${tone.label}: ${label}. ${degree} link${degree === 1 ? "" : "s"}.`}
                onPointerDown={(e) => startNodeDrag(e, node.id)}
                onMouseEnter={() => setHoveredNodeId(node.id)}
                onMouseLeave={() => setHoveredNodeId(null)}
                onFocus={() => setHoveredNodeId(node.id)}
                onBlur={() => setHoveredNodeId(null)}
                onClick={(e) => {
                  e.stopPropagation();
                  setSelectedNodeId((c) => (c === node.id ? null : node.id));
                }}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    setSelectedNodeId((c) => (c === node.id ? null : node.id));
                  }
                  if (e.key === "Escape") {
                    setSelectedNodeId(null);
                    setHoveredNodeId(null);
                  }
                }}
              >
                <circle className="memory-constellation-halo" cx="0" cy="0" fill={tone.halo} r={r * (active ? 2.4 : linked ? 2.0 : 1.6)} />
                <circle className="memory-constellation-ring" cx="0" cy="0" fill="none" r={r * 1.2} stroke={tone.accent} strokeWidth={active ? 1.8 : 0.85} />
                <circle
                  className="memory-constellation-core"
                  cx="0"
                  cy="0"
                  fill={tone.fill}
                  opacity={muted ? 0.35 : opacity}
                  r={active ? r + 1.5 : r}
                  stroke={tone.accent}
                  strokeWidth={active ? 2 : 1}
                />
                {showLabel && (
                  <text
                    ref={(el) => {
                      if (el) labelElRef.current.set(node.id, el);
                    }}
                    className="memory-constellation-label"
                    y="4"
                    fill="var(--fg)"
                    textAnchor="start"
                  >
                    {label.length > 28 ? `${label.slice(0, 28)}...` : label}
                  </text>
                )}
                <title>{node.label}</title>
              </g>
            );
          })}
        </g>
      </svg>

      <div className="memory-overlay-top">
        <div className="memory-count-box">
          <div className="memory-count-title">Knowledge graph</div>
          <div className="memory-count-sub mono">
            {nodes.length} nodes / {displayedLinks} {activeMeta ? "related" : "links"}
          </div>
        </div>
        <div className="memory-legend">
          {base.groups.map((group) => (
            <span key={group.kind} className="memory-legend-chip mono">
              <span className="memory-legend-dot" style={{ background: NODE_TONE[group.kind].accent }} />
              {group.name} {group.total}
            </span>
          ))}
        </div>
      </div>

      {focusMeta && (
        <div className="memory-signal">
          <div className="memory-signal-tag mono">
            {activeMeta && selectedNodeId === activeNodeId ? "Pinned" : activeMeta ? "Inspecting" : "Strongest signal"}
          </div>
          <div className="memory-signal-card">
            <div className="memory-signal-head">
              <span className="memory-signal-dot" style={{ background: NODE_TONE[focusMeta.kind].accent }} />
              <span className="memory-signal-kind">{NODE_TONE[focusMeta.kind].label}</span>
              <span className="memory-signal-links">
                {focusMeta.degree} link{focusMeta.degree === 1 ? "" : "s"}
              </span>
            </div>
            <div className="memory-signal-label">{labelFor(focusMeta.node)}</div>
            {activeEdgeTypes.length > 0 && (
              <div className="memory-signal-edges">
                {activeEdgeTypes.map((e) => (
                  <span key={e.type} className="memory-signal-edge">
                    {e.type} {e.count}
                  </span>
                ))}
              </div>
            )}
          </div>
        </div>
      )}

      <button
        type="button"
        className="memory-replay mono"
        onClick={(e) => {
          e.stopPropagation();
          replay();
        }}
        title="Replay grow animation"
      >
        ↻ Replay
      </button>
      <div className="memory-hint mono">drag nodes · scroll to zoom · drag canvas to pan</div>
    </div>
  );
}
