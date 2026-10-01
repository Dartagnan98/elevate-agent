import { useEffect, useState } from "react";
import { Loader2, Search } from "lucide-react";

import { Input } from "@/components/ui/input";
import { api } from "@/lib/api";
import type { DripContact, DripSegment } from "@/lib/api";
import { errorMessage } from "../drips-helpers";
import { Note, SegmentChip } from "./shared";

export function ContactPicker({
  segments,
  onPick,
  autoFocus,
  placeholder = "Search by name, email or phone",
}: {
  segments: DripSegment[];
  onPick: (contact: DripContact) => void;
  autoFocus?: boolean;
  placeholder?: string;
}) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<DripContact[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const timer = setTimeout(() => {
      setBusy(true);
      api
        .searchDripContacts(query.trim(), { limit: 15 })
        .then((res) => {
          if (cancelled) return;
          setResults(res.contacts);
          setError(null);
        })
        .catch((err: unknown) => {
          if (!cancelled) setError(errorMessage(err, "Could not search contacts."));
        })
        .finally(() => {
          if (!cancelled) setBusy(false);
        });
    }, 220);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [query]);

  return (
    <div className="flex flex-col gap-2">
      <div className="relative">
        <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" aria-hidden="true" />
        <Input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder={placeholder}
          className="pl-8"
          autoFocus={autoFocus}
          aria-label="Search contacts"
        />
        {busy && <Loader2 className="absolute right-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 animate-spin text-muted-foreground" aria-hidden="true" />}
      </div>
      {error && <Note tone="error">{error}</Note>}
      <ul className="max-h-64 divide-y divide-border overflow-y-auto rounded-md border border-border">
        {results.length === 0 && !busy && (
          <li className="px-3 py-3 text-xs text-muted-foreground">No contacts match yet.</li>
        )}
        {results.map((contact) => {
          const segment = segments.find((s) => s.key === contact.segment) ?? null;
          return (
            <li key={contact.id}>
              <button
                type="button"
                onClick={() => onPick(contact)}
                className="flex w-full items-center justify-between gap-3 px-3 py-2 text-left hover:bg-foreground/5"
              >
                <span className="min-w-0">
                  <span className="block truncate text-sm font-medium text-foreground">{contact.name}</span>
                  <span className="block truncate text-[0.72rem] text-muted-foreground">
                    {[contact.email, contact.phone].filter(Boolean).join(" · ") || contact.type || ""}
                  </span>
                </span>
                {contact.segment && <SegmentChip segment={segment} label={segment?.label ?? contact.segment} />}
              </button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
