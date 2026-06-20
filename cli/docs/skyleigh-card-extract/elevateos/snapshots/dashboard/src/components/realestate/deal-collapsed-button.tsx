'use client';

import { useState, useTransition } from 'react';
import { useRouter } from 'next/navigation';
import { Button } from '@/components/ui/button';

export function DealCollapsedButton({
  dealId,
  dealTitle,
  side,
}: {
  dealId: string;
  dealTitle: string;
  side: string;
}) {
  const router = useRouter();
  const [isPending, startTransition] = useTransition();
  const [error, setError] = useState<string | null>(null);

  const label = isPending ? 'Collapsing...' : 'Deal collapsed';

  async function handleClick() {
    const target = side === 'buyer' ? 'Top 25 and clear the property details' : 'Listing Live and clear the buyer memory';
    const confirmed = window.confirm(
      `Mark ${dealTitle} as collapsed? This will move it back to ${target}.`,
    );
    if (!confirmed) return;

    setError(null);
    startTransition(async () => {
      try {
        const response = await fetch(`/api/realestate/deals/${encodeURIComponent(dealId)}/collapse`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ side }),
        });
        const body = await response.json().catch(() => ({}));
        if (!response.ok) {
          const message = typeof body?.error === 'string' ? body.error : `HTTP ${response.status}`;
          throw new Error(message);
        }
        router.refresh();
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Could not collapse deal.');
      }
    });
  }

  return (
    <div className="grid gap-1">
      <Button
        type="button"
        variant="destructive"
        size="sm"
        className="h-8 rounded-md px-2 text-xs"
        disabled={isPending}
        onClick={handleClick}
      >
        {label}
      </Button>
      {error && <p className="text-[11px] text-destructive">{error}</p>}
    </div>
  );
}
