import { useCallback, useEffect, useRef, useState } from "react";
import { fetchJSON } from "@/lib/api";

/** Preserve the last successful desk snapshot and distinguish unavailable from empty. */
export function useDeskResource<T extends { ok: boolean }>(path: string, refreshKey?: unknown) {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const revision = useRef(0);
  const load = useCallback(async () => {
    const id = ++revision.current;
    setLoading(true);
    try {
      const response = await fetchJSON<T>(path);
      if (!response.ok) throw new Error("The desk could not refresh. Please retry.");
      if (id !== revision.current) return;
      setData(response); setError(null);
    } catch (e) {
      if (id === revision.current) setError(e instanceof Error ? e.message : "Could not refresh. Please retry.");
    } finally {
      if (id === revision.current) setLoading(false);
    }
  }, [path]);
  useEffect(() => { void load(); return () => { revision.current += 1; }; }, [load, refreshKey]);
  return { data, loading, error, load };
}
