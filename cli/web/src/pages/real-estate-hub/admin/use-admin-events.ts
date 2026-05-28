import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { AdminUpcomingEvent } from "@/lib/api-types";
import type { AdminEvent } from "./compute-admin-events";
import { mapAdminUpcomingEvents } from "./compute-admin-events";

export interface UseAdminEventsResult {
  rawEvents: AdminUpcomingEvent[];
  events: AdminEvent[];
  loading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
}

function errMsg(e: unknown, fallback: string): string {
  if (e instanceof Error && e.message) return e.message;
  return fallback;
}

export function useAdminEvents(days = 21): UseAdminEventsResult {
  const [rawEvents, setRawEvents] = useState<AdminUpcomingEvent[]>([]);
  const [events, setEvents] = useState<AdminEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (signal?: { cancelled: boolean }) => {
    try {
      const response = await api.getAdminUpcomingEvents(days);
      if (signal?.cancelled) return;
      setRawEvents(response.items);
      setEvents(mapAdminUpcomingEvents(response.items));
      setError(null);
    } catch (e) {
      if (signal?.cancelled) return;
      setRawEvents([]);
      setEvents([]);
      setError(errMsg(e, "Admin events failed"));
    } finally {
      if (!signal?.cancelled) setLoading(false);
    }
  }, [days]);

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

  return { rawEvents, events, loading, error, refresh };
}
