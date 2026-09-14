import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import type { AdminUpcomingEvent } from "@/lib/api-types";
import type { AdminEvent } from "./compute-admin-events";
import { mapAdminUpcomingEvents } from "./compute-admin-events";

export interface UseAdminEventsResult {
  rawEvents: AdminUpcomingEvent[];
  events: AdminEvent[];
  loading: boolean;
  error: string | null;
  refresh: (options?: { silent?: boolean }) => Promise<void>;
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
  const request = useRef(0);

  const load = useCallback(async (signal?: { cancelled: boolean }) => {
    const id = ++request.current;
    try {
      const response = await api.getAdminUpcomingEvents(days);
      if (signal?.cancelled || id !== request.current) return;
      setRawEvents(response.items);
      setEvents(mapAdminUpcomingEvents(response.items));
      setError(null);
    } catch (e) {
      if (signal?.cancelled || id !== request.current) return;
      setError(errMsg(e, "Admin events failed"));
    } finally {
      if (!signal?.cancelled && id === request.current) setLoading(false);
    }
  }, [days]);

  const refresh = useCallback(async (options?: { silent?: boolean }) => {
    if (!options?.silent) setLoading(true);
    await load();
  }, [load]);

  useEffect(() => {
    const signal = { cancelled: false };
    setLoading(true);
    void load(signal);
    return () => {
      signal.cancelled = true;
      request.current += 1;
    };
  }, [load]);

  return { rawEvents, events, loading, error, refresh };
}
