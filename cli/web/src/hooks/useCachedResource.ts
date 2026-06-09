import { useCallback, useEffect, useRef, useState } from "react";

/**
 * Stale-while-revalidate cache for page data, scoped to the renderer process.
 *
 * Why this exists: the dashboard routes are unmounted on every tab switch
 * (React Router) and each page fetches on mount with `loading=true`. So
 * revisiting a tab you saw seconds ago re-runs the network round trip and
 * re-flashes the skeleton. This hook keeps the last response in a
 * module-level cache that survives unmount, and reads it *synchronously* on
 * first render — so a revisited tab paints instantly, then revalidates in
 * the background. No new dependency, drop-in for the useEffect+fetch pattern.
 *
 * Usage:
 *   const { data, loading, error, refresh } = useCachedResource(
 *     "surface-tasks",
 *     () => api.listSurfaceTasks(),
 *     { ttl: 5000 },
 *   );
 *
 * - First-ever visit: loading=true, fetches, fills cache.
 * - Revisit within ttl: data served from cache, loading=false, NO refetch.
 * - Revisit after ttl: cached data shown immediately (loading=false), a
 *   background revalidate runs and swaps in fresh data when it lands.
 * - Mutations call refresh() to force a revalidate and update the cache.
 */

interface CacheEntry<T> {
  data: T;
  fetchedAt: number;
  // de-dupes concurrent revalidations of the same key across pages
  inflight?: Promise<T> | null;
}

const _cache = new Map<string, CacheEntry<unknown>>();

function _now(): number {
  return Date.now();
}

export interface UseCachedResourceOptions {
  /** Milliseconds a cached value is considered fresh. Default 5000. */
  ttl?: number;
  /** Skip fetching entirely while false (e.g. waiting on a prerequisite). */
  enabled?: boolean;
}

export interface CachedResource<T> {
  data: T | undefined;
  loading: boolean;
  error: unknown;
  /** Force a revalidate now (e.g. after a create/delete). */
  refresh: () => Promise<void>;
  /** Optimistically replace the cached value without a fetch. */
  mutate: (next: T) => void;
}

/** Read-only peek used by the synchronous useState initializer. */
function _peek<T>(key: string): CacheEntry<T> | undefined {
  return _cache.get(key) as CacheEntry<T> | undefined;
}

export function useCachedResource<T>(
  key: string,
  fetcher: () => Promise<T>,
  options: UseCachedResourceOptions = {},
): CachedResource<T> {
  const { ttl = 5000, enabled = true } = options;

  // Synchronous first-render read: if we have a cached value, the page paints
  // with it immediately and loading starts false (no skeleton flash).
  const initial = _peek<T>(key);
  const [data, setData] = useState<T | undefined>(initial?.data);
  const [loading, setLoading] = useState<boolean>(!initial && enabled);
  const [error, setError] = useState<unknown>(null);

  // Keep the latest fetcher without retriggering the effect every render.
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;

  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  const revalidate = useCallback(async (): Promise<void> => {
    const entry = _peek<T>(key);
    // De-dupe: if another page already kicked off a fetch for this key, await it.
    if (entry?.inflight) {
      try {
        const shared = await entry.inflight;
        if (mounted.current) {
          setData(shared);
          setError(null);
        }
      } catch (e) {
        if (mounted.current) setError(e);
      }
      return;
    }

    if (!entry) setLoading(true);
    const p = fetcherRef.current();
    _cache.set(key, {
      data: (entry?.data as T) ?? (undefined as unknown as T),
      fetchedAt: entry?.fetchedAt ?? 0,
      inflight: p,
    });
    try {
      const result = await p;
      _cache.set(key, { data: result, fetchedAt: _now(), inflight: null });
      if (mounted.current) {
        setData(result);
        setError(null);
      }
    } catch (e) {
      const prev = _peek<T>(key);
      if (prev) _cache.set(key, { ...prev, inflight: null });
      else _cache.delete(key);
      if (mounted.current) setError(e);
    } finally {
      if (mounted.current) setLoading(false);
    }
  }, [key]);

  useEffect(() => {
    if (!enabled) return;
    const entry = _peek<T>(key);
    const fresh = entry && _now() - entry.fetchedAt < ttl;
    if (fresh) {
      // Cache hit within ttl: serve it, no fetch.
      if (mounted.current) {
        setData(entry.data);
        setLoading(false);
      }
      return;
    }
    // Stale or missing: revalidate (cached data, if any, is already shown).
    void revalidate();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, enabled, ttl]);

  const mutate = useCallback(
    (next: T) => {
      _cache.set(key, { data: next, fetchedAt: _now(), inflight: null });
      if (mounted.current) setData(next);
    },
    [key],
  );

  return { data, loading, error, refresh: revalidate, mutate };
}

/** Drop a key (or everything) from the cache — e.g. on logout/account switch. */
export function invalidateCachedResource(key?: string): void {
  if (key === undefined) _cache.clear();
  else _cache.delete(key);
}
