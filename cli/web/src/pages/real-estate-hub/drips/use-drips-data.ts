import { useCallback, useEffect, useRef, useState } from "react";

import { api } from "@/lib/api";
import type { DripBoard, DripOverview } from "@/lib/api";
import { errorMessage } from "./drips-helpers";

export interface DripsData {
  overview: DripOverview | null;
  board: DripBoard | null;
  loading: boolean;
  refreshing: boolean;
  error: string | null;
  refresh: () => Promise<void>;
}

export function useDripsData(): DripsData {
  const [overview, setOverview] = useState<DripOverview | null>(null);
  const [board, setBoard] = useState<DripBoard | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const seq = useRef(0);

  const refresh = useCallback(async () => {
    const id = ++seq.current;
    setRefreshing(true);
    try {
      const [nextOverview, nextBoard] = await Promise.all([
        api.getDripsOverview(),
        api.getDripsBoard({ horizon: 7 }),
      ]);
      if (id !== seq.current) return;
      setOverview(nextOverview);
      setBoard(nextBoard);
      setError(null);
    } catch (err) {
      if (id === seq.current) setError(errorMessage(err, "Could not load drip campaigns."));
    } finally {
      if (id === seq.current) {
        setLoading(false);
        setRefreshing(false);
      }
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  return { overview, board, loading, refreshing, error, refresh };
}
