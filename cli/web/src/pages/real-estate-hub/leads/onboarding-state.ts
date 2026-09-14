import { useCallback, useEffect, useState } from "react";
import type { LeadsSetupSnapshot } from "@/lib/api-types";
import {
  errorMessage,
  loadLeadsSetup,
  readCachedLeadsSetup,
  writeCachedLeadsSetup,
} from "./onboarding-data";

export function useLeadsSetup(): {
  loading: boolean;
  setup: LeadsSetupSnapshot | null;
  error: string | null;
  setSetup: (next: LeadsSetupSnapshot) => void;
  refresh: () => Promise<void>;
} {
  const initialCache = readCachedLeadsSetup();
  const [setup, setSetupState] = useState<LeadsSetupSnapshot | null>(() => initialCache?.setup ?? null);
  const [loading, setLoading] = useState(() => !initialCache);
  const [error, setError] = useState<string | null>(null);

  const setSetup = useCallback((next: LeadsSetupSnapshot) => {
    setSetupState(writeCachedLeadsSetup(next));
  }, []);

  const refresh = useCallback(async () => {
    if (!readCachedLeadsSetup()) setLoading(true);
    setError(null);
    try {
      const snap = await loadLeadsSetup();
      setSetupState(snap);
    } catch (err) {
      setError(errorMessage(err, "Could not load leads setup"));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  return { loading, setup, error, setSetup, refresh };
}
