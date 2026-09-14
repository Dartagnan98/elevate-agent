import React, { useCallback, useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { CheckCircle2, Circle, Sparkles } from "lucide-react";
import type { AdminSetupItemStatus } from "@/lib/api-types";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import {
  playOnboardingSwell,
  playOnboardingWhoosh,
} from "@/lib/onboarding-sounds";

export function StatusBadge({ status }: { status: AdminSetupItemStatus }) {
  if (status === "connected" || status === "configured") {
    return (
      <span className="inline-flex items-center gap-1 rounded-md bg-success/15 px-1.5 py-0.5 text-[10.5px] font-medium text-success">
        <CheckCircle2 className="h-3 w-3" /> Connected
      </span>
    );
  }
  if (status === "manual") {
    return (
      <span className="inline-flex items-center gap-1 rounded-md bg-muted px-1.5 py-0.5 text-[10.5px] font-medium text-muted-foreground">
        <CheckCircle2 className="h-3 w-3" /> Manual
      </span>
    );
  }
  if (status === "skipped") {
    return (
      <span className="inline-flex items-center gap-1 rounded-md bg-muted px-1.5 py-0.5 text-[10.5px] font-medium text-muted-foreground">
        Skipped
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 rounded-md border border-warning/40 bg-warning/10 px-1.5 py-0.5 text-[10.5px] font-medium text-warning">
      <Circle className="h-3 w-3" /> Missing
    </span>
  );
}

export function LeadsOnboardingGate({ onStart, onSkip }: { onStart: () => void; onSkip: () => void }) {
  return (
    <section className="onboarding-overlay fixed inset-0 z-[100] flex items-center justify-center overflow-hidden bg-background px-6 py-10">
      <div className="onboarding-aurora-bg pointer-events-none absolute inset-0" aria-hidden />
      <div className="relative flex max-w-md flex-col items-center text-center">
        <div className="onboarding-rise font-mono-ui text-[10px] uppercase tracking-[0.18em] text-muted-foreground">
          Leads · first run
        </div>
        <h1 className="onboarding-rise-delay-1 mt-3 text-[34px] font-medium leading-[1.05] tracking-tight text-foreground">
          Wire up Elevation Leads
        </h1>
        <p className="onboarding-rise-delay-2 mt-3 max-w-sm text-[13.5px] leading-6 text-muted-foreground">
          A short guided run sets your lead sources, outreach channels, and auto-reply policy. Two minutes, end-to-end.
        </p>
        <Button
          size="lg"
          onClick={onStart}
          className="onboarding-rise-delay-3 mt-7 h-12 min-w-[220px] px-6 text-[14px]"
        >
          <Sparkles className="h-4 w-4" />
          Run onboarding
        </Button>
        <button
          type="button"
          onClick={onSkip}
          className="onboarding-rise-delay-3 mt-4 text-[12px] text-muted-foreground underline-offset-2 hover:text-foreground hover:underline"
        >
          or skip to the full setup form
        </button>
      </div>
    </section>
  );
}

export function LeadsOnboardingWelcome({ onContinue }: { onContinue: () => void }) {
  const [exiting, setExiting] = useState(false);

  useEffect(() => {
    playOnboardingSwell();
  }, []);

  const handleStart = useCallback(() => {
    playOnboardingWhoosh();
    playOnboardingSwell();
    setExiting(true);
  }, []);

  const handleAnimationEnd = useCallback(
    (event: React.AnimationEvent<HTMLDivElement>) => {
      if (event.target !== event.currentTarget) return;
      if (exiting) onContinue();
    },
    [exiting, onContinue],
  );

  return createPortal(
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Welcome to Elevation Leads"
      className={cn(
        "onboarding-overlay fixed inset-0 z-[100] flex items-center justify-center overflow-hidden",
        exiting && "onboarding-exit",
      )}
      onAnimationEnd={handleAnimationEnd}
    >
      <div className="onboarding-aurora-bg pointer-events-none absolute inset-0" aria-hidden />
      <div className="relative flex max-w-xl flex-col items-center px-6 text-center">
        <div className="onboarding-rise font-mono-ui text-[10px] uppercase tracking-[0.2em] text-muted-foreground">
          Elevation · Leads
        </div>
        <h1 className="onboarding-rise-delay-1 mt-4 text-[52px] font-medium leading-[1.02] tracking-tight text-foreground">
          Welcome to Elevation Leads.
        </h1>
        <p className="onboarding-rise-delay-2 mt-4 max-w-lg text-[15px] leading-7 text-muted-foreground">
          A few quick questions and Leads starts catching, routing, and drafting replies the moment a lead lands.
        </p>
        <Button
          size="lg"
          onClick={handleStart}
          disabled={exiting}
          className="onboarding-rise-delay-3 mt-9 h-12 min-w-[240px] px-7 text-[14px]"
        >
          Let's get started
        </Button>
      </div>
    </div>,
    document.body,
  );
}
