import { useCallback, useEffect, useMemo, useState } from "react";
import { CalendarDays, Clock, Pause, Play, Plus, Trash2, Zap } from "lucide-react";
import { H2 } from "@nous-research/ui/ui/components/typography/h2";
import { api } from "@/lib/api";
import type { CronJob } from "@/lib/api";
import { DeleteConfirmDialog } from "@/components/DeleteConfirmDialog";
import { useToast } from "@/hooks/useToast";
import { useConfirmDelete } from "@/hooks/useConfirmDelete";
import { Toast } from "@/components/Toast";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectOption } from "@/components/ui/select";
import { Segmented } from "@/components/ui/segmented";
import { useI18n } from "@/i18n";

function formatTime(iso?: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleString();
}

const STATUS_VARIANT: Record<string, "success" | "warning" | "destructive"> = {
  enabled: "success",
  scheduled: "success",
  paused: "warning",
  error: "destructive",
  completed: "destructive",
};

type ScheduleMode = "daily" | "weekdays" | "weekly" | "biweekly" | "monthly" | "custom";

const SCHEDULE_OPTIONS: Array<{ label: string; value: ScheduleMode }> = [
  { label: "Daily", value: "daily" },
  { label: "Weekdays", value: "weekdays" },
  { label: "Weekly", value: "weekly" },
  { label: "Every 2 weeks", value: "biweekly" },
  { label: "Monthly", value: "monthly" },
  { label: "Custom", value: "custom" },
];

const WEEKDAYS = [
  { anchor: "Monday", cron: "1", label: "Monday", value: "monday" },
  { anchor: "Tuesday", cron: "2", label: "Tuesday", value: "tuesday" },
  { anchor: "Wednesday", cron: "3", label: "Wednesday", value: "wednesday" },
  { anchor: "Thursday", cron: "4", label: "Thursday", value: "thursday" },
  { anchor: "Friday", cron: "5", label: "Friday", value: "friday" },
  { anchor: "Saturday", cron: "6", label: "Saturday", value: "saturday" },
  { anchor: "Sunday", cron: "0", label: "Sunday", value: "sunday" },
];

const MONTH_DAYS = Array.from({ length: 31 }, (_, index) => {
  const value = String(index + 1);
  return { label: value, value };
});

function timeParts(time: string): { hour: string; minute: string } {
  const [hour = "9", minute = "0"] = time.split(":");
  return {
    hour: String(Math.max(0, Math.min(23, Number(hour) || 0))),
    minute: String(Math.max(0, Math.min(59, Number(minute) || 0))),
  };
}

function buildSchedule({
  customSchedule,
  dayOfMonth,
  dayOfWeek,
  mode,
  time,
}: {
  customSchedule: string;
  dayOfMonth: string;
  dayOfWeek: string;
  mode: ScheduleMode;
  time: string;
}): { description: string; expression: string; helper: string } {
  if (mode === "custom") {
    return {
      description: "Custom schedule",
      expression: customSchedule.trim(),
      helper: "Use cron, intervals like every 2h, or a one-time timestamp.",
    };
  }

  const { hour, minute } = timeParts(time);
  const weekday = WEEKDAYS.find((day) => day.value === dayOfWeek) ?? WEEKDAYS[0];
  const safeMonthDay = String(Math.max(1, Math.min(31, Number(dayOfMonth) || 1)));

  if (mode === "daily") {
    return {
      description: `Daily at ${time}`,
      expression: `${minute} ${hour} * * *`,
      helper: "Runs once every day at the selected time.",
    };
  }

  if (mode === "weekdays") {
    return {
      description: `Weekdays at ${time}`,
      expression: `${minute} ${hour} * * 1-5`,
      helper: "Runs Monday through Friday at the selected time.",
    };
  }

  if (mode === "weekly") {
    return {
      description: `Every ${weekday.label} at ${time}`,
      expression: `${minute} ${hour} * * ${weekday.cron}`,
      helper: "Runs once per week on the selected day.",
    };
  }

  if (mode === "biweekly") {
    return {
      description: `Every other ${weekday.label} at ${time}`,
      expression: `every 2w on ${weekday.anchor} at ${time}`,
      helper: "Anchors the first run to the next selected weekday and repeats every 14 days.",
    };
  }

  return {
    description: `Monthly on day ${safeMonthDay} at ${time}`,
    expression: `${minute} ${hour} ${safeMonthDay} * *`,
    helper: "Runs once per month on the selected calendar day.",
  };
}

export default function CronPage() {
  const [jobs, setJobs] = useState<CronJob[]>([]);
  const [loading, setLoading] = useState(true);
  const { toast, showToast } = useToast();
  const { t } = useI18n();

  // New job form state
  const [prompt, setPrompt] = useState("");
  const [scheduleMode, setScheduleMode] = useState<ScheduleMode>("daily");
  const [time, setTime] = useState("09:00");
  const [dayOfWeek, setDayOfWeek] = useState("monday");
  const [dayOfMonth, setDayOfMonth] = useState("1");
  const [customSchedule, setCustomSchedule] = useState("0 9 * * *");
  const [name, setName] = useState("");
  const [deliver, setDeliver] = useState("local");
  const [creating, setCreating] = useState(false);
  const schedule = useMemo(
    () =>
      buildSchedule({
        customSchedule,
        dayOfMonth,
        dayOfWeek,
        mode: scheduleMode,
        time,
      }),
    [customSchedule, dayOfMonth, dayOfWeek, scheduleMode, time],
  );

  const loadJobs = useCallback(() => {
    api
      .getCronJobs()
      .then(setJobs)
      .catch(() => showToast(t.common.loading, "error"))
      .finally(() => setLoading(false));
  }, [showToast, t.common.loading]);

  useEffect(() => {
    loadJobs();
  }, [loadJobs]);

  const handleCreate = async () => {
    if (!prompt.trim() || !schedule.expression.trim()) {
      showToast(`${t.cron.prompt} & ${t.cron.schedule} required`, "error");
      return;
    }
    setCreating(true);
    try {
      await api.createCronJob({
        prompt: prompt.trim(),
        schedule: schedule.expression.trim(),
        name: name.trim() || undefined,
        deliver,
      });
      showToast(t.common.create + " ✓", "success");
      setPrompt("");
      setScheduleMode("daily");
      setTime("09:00");
      setDayOfWeek("monday");
      setDayOfMonth("1");
      setCustomSchedule("0 9 * * *");
      setName("");
      setDeliver("local");
      loadJobs();
    } catch (e) {
      showToast(`${t.config.failedToSave}: ${e}`, "error");
    } finally {
      setCreating(false);
    }
  };

  const handlePauseResume = async (job: CronJob) => {
    try {
      const isPaused = job.state === "paused";
      if (isPaused) {
        await api.resumeCronJob(job.id);
        showToast(
          `${t.cron.resume}: "${job.name || job.prompt.slice(0, 30)}"`,
          "success",
        );
      } else {
        await api.pauseCronJob(job.id);
        showToast(
          `${t.cron.pause}: "${job.name || job.prompt.slice(0, 30)}"`,
          "success",
        );
      }
      loadJobs();
    } catch (e) {
      showToast(`${t.status.error}: ${e}`, "error");
    }
  };

  const handleTrigger = async (job: CronJob) => {
    try {
      await api.triggerCronJob(job.id);
      showToast(
        `${t.cron.triggerNow}: "${job.name || job.prompt.slice(0, 30)}"`,
        "success",
      );
      loadJobs();
    } catch (e) {
      showToast(`${t.status.error}: ${e}`, "error");
    }
  };

  const jobDelete = useConfirmDelete({
    onDelete: useCallback(
      async (id: string) => {
        const job = jobs.find((j) => j.id === id);
        try {
          await api.deleteCronJob(id);
          showToast(
            `${t.common.delete}: "${job?.name || (job?.prompt ?? "").slice(0, 30) || id}"`,
            "success",
          );
          loadJobs();
        } catch (e) {
          showToast(`${t.status.error}: ${e}`, "error");
          throw e;
        }
      },
      [jobs, loadJobs, showToast, t.common.delete, t.status.error],
    ),
  });

  if (loading) {
    return (
      <div className="flex items-center justify-center py-24">
        <div className="h-6 w-6 animate-spin rounded-full border-2 border-primary border-t-transparent" />
      </div>
    );
  }

  const pendingJob = jobDelete.pendingId
    ? jobs.find((j) => j.id === jobDelete.pendingId)
    : null;

  return (
    <div className="flex flex-col gap-6">
      <Toast toast={toast} />

      <DeleteConfirmDialog
        open={jobDelete.isOpen}
        onCancel={jobDelete.cancel}
        onConfirm={jobDelete.confirm}
        title={t.cron.confirmDeleteTitle}
        description={
          pendingJob
            ? `"${pendingJob.name || pendingJob.prompt.slice(0, 40)}" — ${t.cron.confirmDeleteMessage}`
            : t.cron.confirmDeleteMessage
        }
        loading={jobDelete.isDeleting}
      />

      {/* Create new job form */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <Plus className="h-4 w-4" />
            {t.cron.newJob}
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid gap-4">
            <div className="grid gap-2">
              <Label htmlFor="cron-name">{t.cron.nameOptional}</Label>
              <Input
                id="cron-name"
                placeholder={t.cron.namePlaceholder}
                value={name}
                onChange={(e) => setName(e.target.value)}
              />
            </div>

            <div className="grid gap-2">
              <Label htmlFor="cron-prompt">{t.cron.prompt}</Label>
              <textarea
                id="cron-prompt"
                className="flex min-h-[80px] w-full rounded-xl border border-input bg-card/55 px-3 py-2 text-sm shadow-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                placeholder={t.cron.promptPlaceholder}
                value={prompt}
                onChange={(e) => setPrompt(e.target.value)}
              />
            </div>

            <div className="grid gap-3 rounded-2xl border border-border/70 bg-card/35 p-3">
              <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
                <div className="min-w-0">
                  <Label htmlFor="cron-schedule-mode">{t.cron.schedule}</Label>
                  <div className="mt-1 flex items-center gap-2 text-xs text-muted-foreground">
                    <CalendarDays className="h-3.5 w-3.5" />
                    <span>{schedule.description}</span>
                  </div>
                </div>
                <Segmented
                  className="flex flex-wrap justify-start rounded-2xl bg-background/40 p-1"
                  onChange={(value) => setScheduleMode(value)}
                  options={SCHEDULE_OPTIONS}
                  size="sm"
                  value={scheduleMode}
                />
              </div>

              {scheduleMode === "custom" ? (
                <div className="grid gap-2">
                  <Label htmlFor="cron-schedule">{t.cron.schedulePlaceholder}</Label>
                  <Input
                    id="cron-schedule"
                    placeholder="0 9 * * *"
                    value={customSchedule}
                    onChange={(e) => setCustomSchedule(e.target.value)}
                  />
                </div>
              ) : (
                <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
                  <div className="grid gap-2">
                    <Label htmlFor="cron-time">Time</Label>
                    <Input
                      id="cron-time"
                      type="time"
                      value={time}
                      onChange={(e) => setTime(e.target.value || "09:00")}
                    />
                  </div>

                  {(scheduleMode === "weekly" || scheduleMode === "biweekly") && (
                    <div className="grid gap-2">
                      <Label htmlFor="cron-weekday">Day</Label>
                      <Select
                        id="cron-weekday"
                        value={dayOfWeek}
                        onValueChange={setDayOfWeek}
                      >
                        {WEEKDAYS.map((day) => (
                          <SelectOption key={day.value} value={day.value}>
                            {day.label}
                          </SelectOption>
                        ))}
                      </Select>
                    </div>
                  )}

                  {scheduleMode === "monthly" && (
                    <div className="grid gap-2">
                      <Label htmlFor="cron-month-day">Day of month</Label>
                      <Select
                        id="cron-month-day"
                        value={dayOfMonth}
                        onValueChange={setDayOfMonth}
                      >
                        {MONTH_DAYS.map((day) => (
                          <SelectOption key={day.value} value={day.value}>
                            {day.label}
                          </SelectOption>
                        ))}
                      </Select>
                    </div>
                  )}
                </div>
              )}

              <div className="flex flex-col gap-2 rounded-xl bg-background/45 px-3 py-2 text-xs text-muted-foreground sm:flex-row sm:items-center sm:justify-between">
                <span>{schedule.helper}</span>
                <code className="w-fit rounded-lg bg-foreground/10 px-2 py-1 font-mono text-[0.72rem] text-foreground">
                  {schedule.expression || "schedule required"}
                </code>
              </div>
            </div>

            <div className="grid grid-cols-1 gap-4 sm:grid-cols-[minmax(0,1fr)_minmax(12rem,0.5fr)]">
              <div className="grid gap-2">
                <Label htmlFor="cron-deliver">{t.cron.deliverTo}</Label>
                <Select
                  id="cron-deliver"
                  value={deliver}
                  onValueChange={(v) => setDeliver(v)}
                >
                  <SelectOption value="local">
                    {t.cron.delivery.local}
                  </SelectOption>
                  <SelectOption value="telegram">
                    {t.cron.delivery.telegram}
                  </SelectOption>
                  <SelectOption value="discord">
                    {t.cron.delivery.discord}
                  </SelectOption>
                  <SelectOption value="slack">
                    {t.cron.delivery.slack}
                  </SelectOption>
                  <SelectOption value="email">
                    {t.cron.delivery.email}
                  </SelectOption>
                </Select>
              </div>

              <div className="flex items-end">
                <Button
                  onClick={handleCreate}
                  disabled={creating}
                  className="w-full"
                >
                  <Plus className="h-3 w-3" />
                  {creating ? t.common.creating : t.common.create}
                </Button>
              </div>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Jobs list */}
      <div className="flex flex-col gap-3">
        <H2
          variant="sm"
          className="flex items-center gap-2 text-muted-foreground"
        >
          <Clock className="h-4 w-4" />
          {t.cron.scheduledJobs} ({jobs.length})
        </H2>

        {jobs.length === 0 && (
          <Card>
            <CardContent className="py-8 text-center text-sm text-muted-foreground">
              {t.cron.noJobs}
            </CardContent>
          </Card>
        )}

        {jobs.map((job) => (
          <Card key={job.id}>
            <CardContent className="flex items-center gap-4 py-4">
              {/* Info */}
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 mb-1">
                  <span className="font-medium text-sm truncate">
                    {job.name ||
                      job.prompt.slice(0, 60) +
                        (job.prompt.length > 60 ? "..." : "")}
                  </span>
                  <Badge variant={STATUS_VARIANT[job.state] ?? "secondary"}>
                    {job.state}
                  </Badge>
                  {job.deliver && job.deliver !== "local" && (
                    <Badge variant="outline">{job.deliver}</Badge>
                  )}
                </div>
                {job.name && (
                  <p className="text-xs text-muted-foreground truncate mb-1">
                    {job.prompt.slice(0, 100)}
                    {job.prompt.length > 100 ? "..." : ""}
                  </p>
                )}
                <div className="flex items-center gap-4 text-xs text-muted-foreground">
                  <span className="font-mono">{job.schedule_display}</span>
                  <span>
                    {t.cron.last}: {formatTime(job.last_run_at)}
                  </span>
                  <span>
                    {t.cron.next}: {formatTime(job.next_run_at)}
                  </span>
                </div>
                {job.last_error && (
                  <p className="text-xs text-destructive mt-1">
                    {job.last_error}
                  </p>
                )}
              </div>

              {/* Actions */}
              <div className="flex items-center gap-1 shrink-0">
                <Button
                  variant="ghost"
                  size="icon"
                  title={job.state === "paused" ? t.cron.resume : t.cron.pause}
                  aria-label={
                    job.state === "paused" ? t.cron.resume : t.cron.pause
                  }
                  onClick={() => handlePauseResume(job)}
                >
                  {job.state === "paused" ? (
                    <Play className="h-4 w-4 text-success" />
                  ) : (
                    <Pause className="h-4 w-4 text-warning" />
                  )}
                </Button>

                <Button
                  variant="ghost"
                  size="icon"
                  title={t.cron.triggerNow}
                  aria-label={t.cron.triggerNow}
                  onClick={() => handleTrigger(job)}
                >
                  <Zap className="h-4 w-4" />
                </Button>

                <Button
                  variant="ghost"
                  size="icon"
                  title={t.common.delete}
                  aria-label={t.common.delete}
                  onClick={() => jobDelete.requestDelete(job.id)}
                >
                  <Trash2 className="h-4 w-4 text-destructive" />
                </Button>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  );
}
