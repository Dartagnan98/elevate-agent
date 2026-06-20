import type React from "react";
import {
  AlertTriangle,
  CheckCircle2,
  Circle,
  ExternalLink,
  Link as LinkIcon,
  Loader2,
  X,
} from "lucide-react";
import { Link } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { ListSkeleton } from "@/components/ui/skeleton";
import type { AdminSetupItemStatus, OutreachConnectorRef } from "@/lib/api-types";
import { cn } from "@/lib/utils";
import { StatusBadge } from "./onboarding-shell";

export type TemplateEditorState =
  | { mode: "create"; lane: string; name: string; body: string }
  | { mode: "edit"; id: string; lane: string; name: string; body: string };

export function TemplateEditorCard({
  editor,
  onChange,
  onSave,
  onCancel,
  busy,
}: {
  editor: TemplateEditorState;
  onChange: (patch: Partial<{ name: string; body: string }>) => void;
  onSave: () => void;
  onCancel: () => void;
  busy: boolean;
}) {
  return (
    <div className="flex flex-col gap-2 rounded-md border border-primary/40 bg-card/70 px-3 py-2.5 backdrop-blur-sm sm:col-span-2">
      <div className="flex items-center justify-between gap-2">
        <span className="font-mono-ui text-[10px] uppercase tracking-[0.12em] text-muted-foreground">
          {editor.mode === "create" ? "New template" : "Edit template"}
        </span>
        <button
          type="button"
          onClick={onCancel}
          aria-label="Cancel template edit"
          title="Cancel"
          className="rounded-sm p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
          disabled={busy}
        >
          <X className="h-3 w-3" aria-hidden="true" />
        </button>
      </div>
      <input
        type="text"
        value={editor.name}
        onChange={(e) => onChange({ name: e.target.value })}
        placeholder="Template name (e.g. Open house live)"
        className="w-full rounded-md border border-border bg-background/40 px-3 py-1.5 text-[12.5px] text-foreground outline-none focus:border-primary focus:ring-1 focus:ring-primary/30"
        disabled={busy}
      />
      <textarea
        value={editor.body}
        onChange={(e) => onChange({ body: e.target.value })}
        rows={4}
        placeholder="Body. Use {first_name}, {area}, {topic}, etc. Add [[gif:keyword]] to attach a GIF."
        className="min-h-24 w-full resize-y rounded-md border border-border bg-background/40 px-3 py-2 text-[12.5px] leading-5 text-foreground outline-none placeholder:text-muted-foreground/60 focus:border-primary focus:ring-1 focus:ring-primary/30"
        disabled={busy}
      />
      <div className="flex items-center justify-end gap-2">
        <button
          type="button"
          onClick={onCancel}
          className="rounded-md px-2 py-1 text-[11.5px] text-muted-foreground hover:text-foreground"
          disabled={busy}
        >
          Cancel
        </button>
        <Button size="sm" onClick={onSave} disabled={busy} className="h-7 px-3 text-[11.5px]">
          {busy ? <Loader2 className="h-3 w-3 animate-spin" /> : null}
          {editor.mode === "create" ? "Add template" : "Save changes"}
        </Button>
      </div>
    </div>
  );
}

export function WizardField({
  label,
  value,
  onChange,
  placeholder,
  type = "text",
  fullWidth = false,
  helper,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  type?: string;
  fullWidth?: boolean;
  helper?: React.ReactNode;
}) {
  return (
    <label className={cn("block min-w-0", fullWidth && "md:col-span-2")}>
      <span className="mb-1.5 block text-[12px] font-medium text-muted-foreground">{label}</span>
      <input
        type={type}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        autoComplete={type === "password" ? "new-password" : "off"}
        spellCheck={type === "password" || type === "email" ? false : undefined}
        className="h-9 w-full rounded-md border border-border bg-card/60 px-3 text-[13px] text-foreground outline-none backdrop-blur-sm transition-colors placeholder:text-muted-foreground/50 focus:border-primary focus:ring-1 focus:ring-primary/30"
      />
      {helper && (
        <span className="mt-1.5 block text-[11.5px] leading-5 text-muted-foreground/80">{helper}</span>
      )}
    </label>
  );
}

export function ItemCard({
  title,
  description,
  status,
  children,
}: {
  title: string;
  description: string;
  status: AdminSetupItemStatus;
  children?: React.ReactNode;
}) {
  return (
    <section className="rounded-md border border-border bg-card p-4">
      <header className="mb-2 flex items-start justify-between gap-3">
        <div>
          <h3 className="text-[13px] font-semibold text-foreground">{title}</h3>
          <p className="mt-0.5 text-[11.5px] text-muted-foreground">{description}</p>
        </div>
        <StatusBadge status={status} />
      </header>
      {children && <div className="mt-3 space-y-2">{children}</div>}
    </section>
  );
}

export function FieldRow({
  label,
  value,
  onChange,
  placeholder,
  type = "text",
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  type?: string;
}) {
  return (
    <label className="block text-[11.5px] text-muted-foreground">
      <span className="mb-0.5 block">{label}</span>
      <input
        type={type}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className="w-full rounded-md border border-border bg-background px-2 py-1.5 text-[12.5px] text-foreground outline-none focus:border-primary focus:ring-1 focus:ring-primary/30"
      />
    </label>
  );
}

export const OUTREACH_HINTS: Record<
  OutreachConnectorRef["id"],
  { tagline: string; routes: string }
> = {
  "apple-messages": {
    tagline: "iMessage from your Mac. Auto-picks blue-bubble route for iPhone leads.",
    routes: "Pairs with Messages.app via the existing local bridge — already syncing 237k+ records on this Mac.",
  },
  "sms-provider": {
    tagline: "Business SMS line (Twilio, Sinch, MessageBird, etc.) for non-iPhone leads.",
    routes: "Two-way SMS over a webhook/API. Use for green-bubble Android leads.",
  },
  "android-device": {
    tagline: "Personal Android device SMS via export or helper.",
    routes: "Backup/export route — does not claim live sync unless a helper is wired.",
  },
  "rcs": {
    tagline: "Rich messaging (read receipts, media, typing) for Android leads.",
    routes: "Business RCS provider or Twilio RCS. Personal-device RCS is import-only.",
  },
};

function ConnectorStatusBadge({ connector }: { connector: OutreachConnectorRef }) {
  if (connector.connected) {
    return (
      <span className="inline-flex items-center gap-1 rounded-md bg-success/15 px-1.5 py-0.5 text-[10.5px] font-medium text-success">
        <CheckCircle2 className="h-3 w-3" /> Connected
      </span>
    );
  }
  if (connector.importOnly) {
    return (
      <span className="inline-flex items-center gap-1 rounded-md bg-muted px-1.5 py-0.5 text-[10.5px] font-medium text-muted-foreground">
        <CheckCircle2 className="h-3 w-3" /> Import only
      </span>
    );
  }
  if (connector.blocked) {
    return (
      <span className="inline-flex items-center gap-1 rounded-md border border-destructive/40 bg-destructive/10 px-1.5 py-0.5 text-[10.5px] font-medium text-destructive">
        <AlertTriangle className="h-3 w-3" /> Blocked
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 rounded-md border border-warning/40 bg-warning/10 px-1.5 py-0.5 text-[10.5px] font-medium text-warning">
      <Circle className="h-3 w-3" /> Not configured
    </span>
  );
}

export function OutreachConnectorsCard({
  connectors,
  outreachReady,
  crmStatus,
  crmProvider,
}: {
  connectors: OutreachConnectorRef[];
  outreachReady: boolean;
  crmStatus: AdminSetupItemStatus;
  crmProvider: string;
}) {
  return (
    <section className="rounded-md border border-border bg-card p-4">
      <header className="mb-3 flex items-start justify-between gap-3">
        <div>
          <h3 className="text-[13px] font-semibold text-foreground">Outreach channels</h3>
          <p className="mt-0.5 text-[11.5px] text-muted-foreground">
            iMessage, SMS, and RCS aren't configured here — they live as Source Connectors so the same wiring
            powers ingestion (read-only message index) and outbound. Elevation auto-routes: iPhone leads get
            iMessage, Android leads fall through to SMS / RCS.
          </p>
        </div>
        {outreachReady ? (
          <span className="inline-flex shrink-0 items-center gap-1 rounded-md bg-success/15 px-1.5 py-0.5 text-[10.5px] font-medium text-success">
            <CheckCircle2 className="h-3 w-3" /> Ready
            {crmStatus === "connected" && crmProvider ? ` (via ${crmProvider})` : ""}
          </span>
        ) : (
          <span className="inline-flex shrink-0 items-center gap-1 rounded-md border border-warning/40 bg-warning/10 px-1.5 py-0.5 text-[10.5px] font-medium text-warning">
            <Circle className="h-3 w-3" /> None active
          </span>
        )}
      </header>

      <div className="mb-3 flex flex-wrap items-center gap-2">
        <Link
          to="/config#connectors"
          className="inline-flex items-center gap-1 rounded-md border border-border bg-background px-2 py-1 text-[11.5px] font-medium text-foreground hover:bg-muted"
        >
          <LinkIcon className="h-3 w-3" />
          Open Source Connectors
        </Link>
        <span className="text-[10.5px] text-muted-foreground">
          Config → Source connectors. Each row below opens its setup task.
        </span>
      </div>

      <div className="space-y-1.5">
        {connectors.length === 0 ? (
          <ListSkeleton rows={3} />
        ) : (
          connectors.map((connector) => {
            const hint = OUTREACH_HINTS[connector.id];
            return (
              <div
                key={connector.id}
                className="flex items-start justify-between gap-3 rounded-md border border-border/60 bg-muted/15 px-3 py-2"
              >
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className="text-[12.5px] font-medium text-foreground">{connector.label}</span>
                    <ConnectorStatusBadge connector={connector} />
                    {connector.totalRecords > 0 && (
                      <span className="text-[10.5px] text-muted-foreground">
                        {connector.totalRecords.toLocaleString()} records
                      </span>
                    )}
                  </div>
                  <p className="mt-0.5 truncate text-[11px] text-muted-foreground">{hint?.tagline}</p>
                  {connector.nextOperatorStep && !connector.connected && (
                    <p className="mt-1 text-[10.5px] text-muted-foreground/80">
                      Next: {connector.nextOperatorStep}
                    </p>
                  )}
                  {connector.lastError && (
                    <p className="mt-1 text-[10.5px] text-destructive/80">{connector.lastError}</p>
                  )}
                </div>
                <Link
                  to="/config#connectors"
                  className="inline-flex shrink-0 items-center gap-1 text-[11px] text-primary underline-offset-2 hover:underline"
                >
                  Configure <ExternalLink className="h-3 w-3" />
                </Link>
              </div>
            );
          })
        )}
      </div>
    </section>
  );
}
