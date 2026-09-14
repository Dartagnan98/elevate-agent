import { useCallback, useRef, useState } from "react";
import { api } from "../../../../lib/api";

export async function kitRequest(url: string, init: RequestInit = {}) {
  const token = (window as unknown as { __ELEVATE_SESSION_TOKEN__?: string }).__ELEVATE_SESSION_TOKEN__ || "";
  const response = await fetch(url, { ...init, headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json", ...init.headers } });
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(body?.detail || `Request failed (${response.status})`);
  }
  return response;
}

// One ordered stream per wizard prevents whole-deal toggle writes racing each
// other. Failed writes remain retryable; flush never silently drops them.
export class KitSaveQueue {
  private tail: Promise<void> = Promise.resolve();
  private failed = new Map<string, () => Promise<unknown>>();
  private report: (error: string) => void;
  constructor(report: (error: string) => void) { this.report = report; }
  save(key: string, action: () => Promise<unknown>): Promise<void> {
    const result = this.tail.then(async () => {
      try {
        await action();
        this.failed.delete(key);
        if (!this.failed.size) this.report("");
      } catch (error) {
        this.failed.set(key, action);
        this.report(`Changes haven't saved: ${String(error)}. Retry before drafting or signing.`);
        throw error;
      }
    });
    this.tail = result.catch(() => {});
    return result;
  }
  async flush() {
    // Blur saves may enqueue while an earlier save is in flight.
    let pending;
    do { pending = this.tail; await pending; } while (pending !== this.tail);
    for (const [key, action] of Array.from(this.failed)) await this.save(key, action);
  }
}

export function useKitSaves(dealId: string, onUpdate?: () => void) {
  const [saveError, setSaveError] = useState("");
  const ref = useRef<{ id: string; queue: KitSaveQueue } | null>(null);
  if (!ref.current || ref.current.id !== dealId) ref.current = { id: dealId, queue: new KitSaveQueue(setSaveError) };
  const queue = ref.current.queue;
  const saveToggle = useCallback((key: string, value: any) => queue.save(key, async () => {
    await api.setAdminDealToggle(dealId, key, value);
    onUpdate?.();
  }), [dealId, queue, onUpdate]);
  const saveDocument = useCallback((url: string, key: string, value: string) => queue.save(`${url}:${key}`, async () => {
    await kitRequest(url, { method: "POST", body: JSON.stringify({ key, value }) });
    onUpdate?.();
  }), [queue, onUpdate]);
  const flushSaves = useCallback(() => queue.flush(), [queue]);
  return { saveToggle, saveDocument, flushSaves, saveError };
}
