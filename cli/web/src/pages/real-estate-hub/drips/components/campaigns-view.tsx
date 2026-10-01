import { Plus, Sparkles } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import type { DripCampaign, DripSegment } from "@/lib/api";
import {
  GROUP_TITLES,
  KIND_LABELS,
  campaignGroup,
  describeDays,
  type CampaignGroup,
} from "../drips-helpers";
import { EmptyState, SegmentChip, Section } from "./shared";

const GROUP_ORDER: CampaignGroup[] = ["primary", "layer", "playbook"];

export function CampaignsView({
  campaigns,
  segments,
  busyId,
  onOpen,
  onToggle,
  onEnroll,
  onCreate,
  onBrowseTemplates,
}: {
  campaigns: DripCampaign[];
  segments: DripSegment[];
  busyId: string | null;
  onOpen: (id: string) => void;
  onToggle: (campaign: DripCampaign, enabled: boolean) => void | Promise<void>;
  onEnroll: (campaign: DripCampaign) => void;
  onCreate: () => void;
  onBrowseTemplates: () => void;
}) {
  const groups = GROUP_ORDER.map((group) => ({
    group,
    items: campaigns.filter((c) => campaignGroup(c) === group),
  }));

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-xs leading-5 text-muted-foreground">
          Switch a campaign off and nobody on it hears from it until it is back on. Open one to change the copy, the days or who it starts for.
        </p>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" onClick={onBrowseTemplates}>
            <Sparkles className="h-3.5 w-3.5" aria-hidden="true" />
            Elevation templates
          </Button>
          <Button size="sm" onClick={onCreate}>
            <Plus className="h-3.5 w-3.5" aria-hidden="true" />
            New campaign
          </Button>
        </div>
      </div>

      {campaigns.length === 0 && (
        <EmptyState
          title="No campaigns yet"
          hint="Install the Elevation set from the templates tab, or build your own from scratch."
          action={
            <Button size="sm" onClick={onBrowseTemplates}>
              Browse templates
            </Button>
          }
        />
      )}

      {groups.map(({ group, items }) =>
        items.length === 0 ? null : (
          <Section key={group} title={GROUP_TITLES[group].title} hint={GROUP_TITLES[group].hint}>
            <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
              {items.map((campaign) => (
                <CampaignCard
                  key={campaign.id}
                  campaign={campaign}
                  segments={segments}
                  busy={busyId === campaign.id}
                  onOpen={() => onOpen(campaign.id)}
                  onToggle={(enabled) => void onToggle(campaign, enabled)}
                  onEnroll={() => onEnroll(campaign)}
                />
              ))}
            </div>
          </Section>
        ),
      )}
    </div>
  );
}

function CampaignCard({
  campaign,
  segments,
  busy,
  onOpen,
  onToggle,
  onEnroll,
}: {
  campaign: DripCampaign;
  segments: DripSegment[];
  busy: boolean;
  onOpen: () => void;
  onToggle: (enabled: boolean) => void;
  onEnroll: () => void;
}) {
  const trigger = campaign.triggerSegment ? segments.find((s) => s.key === campaign.triggerSegment) ?? null : null;
  const days = campaign.days.map((day) => ({ day, channel: "email" as const }));
  const live = campaign.activeEnrollments + campaign.pausedEnrollments;

  return (
    <article
      className={`flex flex-col gap-3 rounded-md border border-border bg-card p-4 transition-opacity ${campaign.enabled ? "" : "opacity-70"}`}
    >
      <header className="flex items-start justify-between gap-3">
        <button type="button" onClick={onOpen} className="min-w-0 text-left">
          <h3 className="truncate text-sm font-semibold text-foreground hover:underline">{campaign.name}</h3>
          <div className="mt-1 flex flex-wrap items-center gap-1.5">
            <Badge variant={campaign.enabled ? "success" : "secondary"}>{campaign.enabled ? "On" : "Off"}</Badge>
            <Badge variant="outline">{KIND_LABELS[campaign.kind]}</Badge>
            {campaign.runOnce && <Badge variant="outline">Once per person</Badge>}
            {campaign.templateSlug && <Badge variant="outline">Elevation</Badge>}
          </div>
        </button>
        <Switch
          checked={campaign.enabled}
          onCheckedChange={onToggle}
          disabled={busy}
          aria-label={`${campaign.enabled ? "Switch off" : "Switch on"} ${campaign.name}`}
          title={campaign.enabled ? "Switch off" : "Switch on"}
        />
      </header>

      {campaign.description && (
        <p className="line-clamp-3 text-xs leading-5 text-muted-foreground">{campaign.description}</p>
      )}

      <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-[0.72rem] leading-5">
        <dt className="text-muted-foreground">Starts</dt>
        <dd className="min-w-0">
          {trigger ? (
            <span className="inline-flex flex-wrap items-center gap-1.5">
              when a contact becomes <SegmentChip segment={trigger} />
            </span>
          ) : campaign.layerFlag ? (
            <span>for every {campaign.layerFlag === "buying" ? "buyer" : "seller"}, on top of their nurture campaign</span>
          ) : (
            <span>by hand only</span>
          )}
        </dd>
        <dt className="text-muted-foreground">Schedule</dt>
        <dd className="font-mono-ui text-[0.7rem]">{describeDays(days)}</dd>
        {campaign.exitDay && (
          <>
            <dt className="text-muted-foreground">Day {campaign.exitDay}</dt>
            <dd className="line-clamp-2">{campaign.exitRule || "Route them"}</dd>
          </>
        )}
      </dl>

      <footer className="mt-auto flex flex-wrap items-center justify-between gap-2 border-t border-border pt-3">
        <span className="font-mono-ui text-[0.7rem] text-muted-foreground">
          {live} on it{campaign.completedEnrollments ? ` · ${campaign.completedEnrollments} finished` : ""}
        </span>
        <div className="flex gap-1.5">
          <Button variant="outline" size="sm" onClick={onEnroll} disabled={!campaign.enabled || busy}>
            Add a contact
          </Button>
          <Button variant="ghost" size="sm" onClick={onOpen}>
            Open
          </Button>
        </div>
      </footer>
    </article>
  );
}
