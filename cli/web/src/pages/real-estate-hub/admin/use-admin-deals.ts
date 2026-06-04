import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { AdminDeal } from "@/lib/api-types";

export interface UseAdminDealsResult {
  deals: AdminDeal[];
  loading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
  moveDeal: (dealId: string, toStage: number) => Promise<void>;
}

function errMsg(e: unknown, fallback: string): string {
  if (e instanceof Error && e.message) return e.message;
  return fallback;
}

export function useAdminDeals(): UseAdminDealsResult {
  const [deals, setDeals] = useState<AdminDeal[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (signal?: { cancelled: boolean }) => {
    try {
      const response = await api.getAdminDeals({ status: null, limit: 200 });
      if (signal?.cancelled) return;
      setDeals(response.items);
      setError(null);
    } catch (e) {
      if (signal?.cancelled) return;
      setError(errMsg(e, "Admin deals failed"));
      setDeals([]);
    } finally {
      if (!signal?.cancelled) setLoading(false);
    }
  }, []);

  const refresh = useCallback(async () => {
    setLoading(true);
    await load();
  }, [load]);

  // Optimistic stage move (kanban drag-and-drop). Update currentStage locally so
  // the card jumps columns immediately, persist via the move endpoint, then
  // reconcile with the server row. Roll back on failure.
  const moveDeal = useCallback(async (dealId: string, toStage: number) => {
    let prevStage: number | undefined;
    setDeals((prev) =>
      prev.map((d) => {
        if (d.id !== dealId) return d;
        prevStage = d.currentStage;
        return { ...d, currentStage: toStage };
      }),
    );
    if (prevStage === toStage) return;
    try {
      const updated = await api.moveAdminDeal(dealId, toStage);
      setDeals((prev) => prev.map((d) => (d.id === dealId ? updated : d)));
    } catch (e) {
      setDeals((prev) =>
        prev.map((d) =>
          d.id === dealId && prevStage !== undefined ? { ...d, currentStage: prevStage } : d,
        ),
      );
      setError(errMsg(e, "Move deal failed"));
    }
  }, []);

  useEffect(() => {
    const signal = { cancelled: false };
    setLoading(true);
    void load(signal);
    return () => {
      signal.cancelled = true;
    };
  }, [load]);

  return { deals, loading, error, refresh, moveDeal };
}
