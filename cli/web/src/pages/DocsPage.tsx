import { useLayoutEffect } from "react";
import { BookOpen, ExternalLink, FileText, Settings, ShieldCheck } from "lucide-react";
import { useI18n } from "@/i18n";
import { usePageHeader } from "@/contexts/usePageHeader";
import { buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export const ELEVATE_DOCS_URL = "https://github.com/Dartagnan98/elevate-agent#readme";

const DOC_SECTIONS = [
  {
    title: "Install and desktop setup",
    body: "Open the README for the current install flow, local dashboard notes, and desktop setup path.",
    icon: Settings,
  },
  {
    title: "Connectors and access",
    body: "Review provider keys, OAuth setup, source inboxes, and the permissions each workflow needs.",
    icon: ShieldCheck,
  },
  {
    title: "Operations runbooks",
    body: "Use the repository docs for release checks, rollback steps, and recovery procedures.",
    icon: FileText,
  },
];

export default function DocsPage() {
  const { t } = useI18n();
  const { setEnd } = usePageHeader();

  useLayoutEffect(() => {
    setEnd(
      <a
        href={ELEVATE_DOCS_URL}
        target="_blank"
        rel="noopener noreferrer"
        className={cn(
          buttonVariants({ variant: "outline", size: "sm" }),
          "h-7 text-xs",
        )}
      >
        <ExternalLink className="mr-1.5 h-3 w-3" />
        {t.app.openDocumentation}
      </a>,
    );
    return () => {
      setEnd(null);
    };
  }, [setEnd, t]);

  return (
    <div className="flex min-h-0 w-full min-w-0 flex-1 flex-col gap-4 pt-1 sm:pt-2">
      <section className="rounded-lg border border-border bg-card p-4 sm:p-5">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
          <div className="flex min-w-0 gap-3">
            <span className="mt-0.5 inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
              <BookOpen className="h-4 w-4" />
            </span>
            <div className="min-w-0">
              <h1 className="text-lg font-semibold leading-tight text-foreground">
                {t.app.nav.documentation}
              </h1>
              <p className="mt-1 max-w-2xl text-sm leading-6 text-muted-foreground">
                The canonical setup, operator, and release notes live in the
                repository README and linked docs.
              </p>
            </div>
          </div>
          <a
            href={ELEVATE_DOCS_URL}
            target="_blank"
            rel="noopener noreferrer"
            className={cn(
              buttonVariants({ variant: "default", size: "sm" }),
              "w-full shrink-0 sm:w-auto",
            )}
          >
            <ExternalLink className="mr-1.5 h-3.5 w-3.5" />
            {t.app.openDocumentation}
          </a>
        </div>
      </section>

      <div className="grid gap-3 md:grid-cols-3">
        {DOC_SECTIONS.map(({ title, body, icon: Icon }) => (
          <section
            key={title}
            className="rounded-lg border border-border bg-card/80 p-4"
          >
            <Icon className="mb-3 h-4 w-4 text-primary" />
            <h2 className="text-sm font-semibold text-foreground">{title}</h2>
            <p className="mt-2 text-sm leading-6 text-muted-foreground">{body}</p>
          </section>
        ))}
      </div>
    </div>
  );
}
