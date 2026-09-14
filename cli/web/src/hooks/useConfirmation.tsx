import { useCallback, useEffect, useRef, useState } from "react";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";

/** Await a decision without blocking the UI; unmounting cancels pending work. */
export function useConfirmation() {
  const [message, setMessage] = useState<string | null>(null);
  const pending = useRef<((confirmed: boolean) => void) | null>(null);
  const finish = useCallback((confirmed: boolean) => {
    const resolve = pending.current;
    pending.current = null;
    setMessage(null);
    resolve?.(confirmed);
  }, []);
  const confirm = useCallback((description: string): Promise<boolean> => {
    // Ignore repeated clicks while a decision is already pending.
    if (pending.current) return Promise.resolve(false);
    setMessage(description);
    return new Promise((resolve) => { pending.current = resolve; });
  }, []);
  useEffect(() => () => {
    pending.current?.(false);
    pending.current = null;
  }, []);

  return {
    confirm,
    dialog: <ConfirmDialog open={message !== null} title="Confirm action"
      overlayClassName="z-[1100]"
      description={message ?? undefined} onCancel={() => finish(false)}
      onConfirm={() => finish(true)} />,
  };
}
