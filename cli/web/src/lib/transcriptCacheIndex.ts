/**
 * LRU prune for the per-session transcript cache index (sessionId -> updatedAt).
 *
 * The cache stores each session's messages under its own localStorage key plus
 * this small index. On each write we record the session's timestamp and decide
 * which data keys to keep vs evict, capped at `max`. Because the just-written
 * session always carries the newest timestamp, it can never be evicted — this
 * helper isolates that (footgun-prone) ordering so it's unit-tested.
 */
export function pruneTranscriptIndex(
  index: Record<string, number>,
  sessionId: string,
  updatedAt: number,
  max: number,
): { keep: [string, number][]; evict: string[] } {
  const merged = { ...index, [sessionId]: updatedAt };
  const ordered = Object.entries(merged).sort(([, a], [, b]) => (b || 0) - (a || 0));
  return {
    keep: ordered.slice(0, max),
    evict: ordered.slice(max).map(([id]) => id),
  };
}
