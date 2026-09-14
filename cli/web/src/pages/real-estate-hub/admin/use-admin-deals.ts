import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import type { AdminDeal } from "@/lib/api-types";
import { loadAllAdminDeals } from "./load-admin-deals";

export interface UseAdminDealsResult {
  deals: AdminDeal[];
  loading: boolean;
  error: string | null;
  refresh: (options?: { silent?: boolean }) => Promise<void>;
  moveDeal: (dealId: string, toStage: number) => Promise<void>;
}
function errMsg(e: unknown, fallback: string): string {
  return e instanceof Error && e.message ? e.message : fallback;
}
export function useAdminDeals(): UseAdminDealsResult {
  const [deals, setDeals] = useState<AdminDeal[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [moveError, setMoveError] = useState<string | null>(null);
  const current = useRef<AdminDeal[]>([]);
  const mounted = useRef(false);
  const request = useRef(0);
  const mutations = useRef(0);
  const pending = useRef(new Map<string, Promise<void>>());
  const publish = useCallback((next: AdminDeal[]) => {
    current.current = next;
    if (mounted.current) setDeals(next);
  }, []);

  const refresh = useCallback(async (options?: { silent?: boolean }) => {
    const id = ++request.current;
    if (!options?.silent && mounted.current) setLoading(true);
    await Promise.allSettled([...pending.current.values()]);
    if (!mounted.current || id !== request.current) return;
    const revision = mutations.current;
    try {
      const items = await loadAllAdminDeals(api.getAdminDeals);
      if (!mounted.current || id !== request.current || revision !== mutations.current) return;
      publish(items);
      setLoadError(null);
    } catch (e) {
      if (mounted.current && id === request.current && revision === mutations.current) {
        setLoadError(errMsg(e, "Could not refresh deals. Please retry."));
      }
    } finally {
      if (mounted.current && id === request.current) setLoading(false);
    }
  }, [publish]);

  // Serialize moves for each deal so an older response cannot undo a later move.
  const moveDeal = useCallback((dealId: string, toStage: number): Promise<void> => {
    const previous = pending.current.get(dealId) ?? Promise.resolve();
    const task = previous.then(async () => {
      if (!mounted.current) return;
      const before = current.current.find(d => d.id === dealId);
      if (!before || before.currentStage === toStage) return;
      mutations.current += 1;
      setMoveError(null);
      publish(current.current.map(d => d.id === dealId ? { ...d, currentStage: toStage } : d));
      try {
        const updated = await api.moveAdminDeal(dealId, toStage);
        publish(current.current.map(d => d.id === dealId ? updated : d));
      } catch (e) {
        publish(current.current.map(d => d.id === dealId ? { ...d, currentStage: before.currentStage } : d));
        if (mounted.current) setMoveError(errMsg(e, "Could not move the deal. Its previous stage has been restored."));
      } finally {
        mutations.current += 1;
      }
    });
    pending.current.set(dealId, task);
    void task.finally(() => { if (pending.current.get(dealId) === task) pending.current.delete(dealId); });
    return task;
  }, [publish]);

  useEffect(() => {
    mounted.current = true;
    void refresh();
    return () => { mounted.current = false; request.current += 1; };
  }, [refresh]);
  return { deals, loading, error: loadError || moveError, refresh, moveDeal };
}
