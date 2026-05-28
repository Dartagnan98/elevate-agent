import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { AdminDeal } from "@/lib/api-types";

export interface UseAdminDealsResult {
  deals: AdminDeal[];
  loading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
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
      const response = await api.getAdminDeals({ limit: 200 });
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

  useEffect(() => {
    const signal = { cancelled: false };
    setLoading(true);
    void load(signal);
    return () => {
      signal.cancelled = true;
    };
  }, [load]);

  return { deals, loading, error, refresh };
}
