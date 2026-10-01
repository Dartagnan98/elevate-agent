import { useEffect, useState } from "react";
import { ExternalLink, Loader2 } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import type { DripSegment, DripTemplate } from "@/lib/api";
import { KIND_LABELS, describeDays, errorMessage } from "../drips-helpers";
import { Note, SegmentChip, Section } from "./shared";

export function TemplatesView({
  segments,
  onInstalled,
  onOpen,
}: {
  segments: DripSegment[];
  onInstalled: () => Promise<void> | void;
  onOpen: (campaignId: string) => void;
}) {
  const [templates, setTemplates] = useState<DripTemplate[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const load = async () => {
    try {
      const res = await api.getDripTemplates();
      setTemplates(res.templates);
      setError(null);
    } catch (err) {
      setError(errorMessage(err, "Could not load the template library."));
    }
  };

  useEffect(() => {
    void load();
  }, []);

  const install = async (slug: string, asCopy: boolean) => {
    setBusy(slug);
    setError(null);
    try {
      const res = await api.installDripTemplate(slug, asCopy);
      await load();
      await onInstalled();
      onOpen(res.campaign.id);
    } catch (err) {
      setError(errorMessage(err, "Could not install this template."));
    } finally {
      setBusy(null);
    }
  };

  return (
    <Section
      title="Elevation templates"
      hint="The campaigns, courses and playbooks from the Elevation program. Install one and it becomes yours to edit; add another copy to build a variation without touching the original."
    >
      {error && <Note tone="error" className="mb-3">{error}</Note>}
      {!templates && !error && (
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" /> Loading…
        </div>
      )}
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
        {templates?.map((t) => {
          const trigger = t.triggerSegment ? segments.find((s) => s.key === t.triggerSegment) ?? null : null;
          const installed = t.installed[0];
          return (
            <article key={t.slug} className="flex flex-col gap-3 rounded-md border border-border bg-card p-4">
              <header>
                <h3 className="text-sm font-semibold text-foreground">{t.name}</h3>
                <div className="mt-1 flex flex-wrap items-center gap-1.5">
                  <Badge variant="outline">{KIND_LABELS[t.kind]}</Badge>
                  {t.runOnce && <Badge variant="outline">Once per person</Badge>}
                  {installed && <Badge variant={installed.enabled ? "success" : "secondary"}>{installed.enabled ? "Installed · on" : "Installed · off"}</Badge>}
                </div>
              </header>
              {t.description && <p className="line-clamp-4 text-xs leading-5 text-muted-foreground">{t.description}</p>}
              <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-[0.72rem] leading-5">
                <dt className="text-muted-foreground">Starts</dt>
                <dd>
                  {trigger ? (
                    <span className="inline-flex flex-wrap items-center gap-1.5">when a contact becomes <SegmentChip segment={trigger} /></span>
                  ) : t.layerFlag ? (
                    `for every ${t.layerFlag === "buying" ? "buyer" : "seller"}`
                  ) : (
                    "by hand"
                  )}
                </dd>
                <dt className="text-muted-foreground">Schedule</dt>
                <dd className="font-mono-ui text-[0.7rem]">{describeDays(t.days.map((day) => ({ day, channel: "email" as const })))}</dd>
                <dt className="text-muted-foreground">Channels</dt>
                <dd>{t.channels.join(", ")}</dd>
              </dl>
              <footer className="mt-auto flex flex-wrap items-center justify-between gap-2 border-t border-border pt-3">
                {t.sourceUrl ? (
                  <a href={t.sourceUrl} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-[0.72rem] text-muted-foreground hover:text-foreground">
                    PDF <ExternalLink className="h-3 w-3" aria-hidden="true" />
                  </a>
                ) : (
                  <span />
                )}
                <div className="flex gap-1.5">
                  {installed ? (
                    <>
                      <Button variant="ghost" size="sm" onClick={() => onOpen(installed.id)}>
                        Open
                      </Button>
                      <Button variant="outline" size="sm" disabled={busy === t.slug} onClick={() => void install(t.slug, true)}>
                        {busy === t.slug ? "Adding…" : "Add a copy"}
                      </Button>
                    </>
                  ) : (
                    <Button size="sm" disabled={busy === t.slug} onClick={() => void install(t.slug, false)}>
                      {busy === t.slug ? "Installing…" : "Install"}
                    </Button>
                  )}
                </div>
              </footer>
            </article>
          );
        })}
      </div>
    </Section>
  );
}
