import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useState,
} from "react";
import { useRefreshOnAgentTurn } from "@/lib/useRefreshOnAgentTurn";
import { useSearchParams } from "react-router-dom";
import {
  AlertCircle,
  CalendarDays,
  Check,
  ChevronRight,
  Clock,
  MessageSquare,
  Pause,
  Pencil,
  Play,
  Plus,
  Search,
  Send,
  Trash2,
  X,
  Zap,
} from "lucide-react";
import { api } from "@/lib/api";
import type { CronJob } from "@/lib/api";
import { DeleteConfirmDialog } from "@/components/DeleteConfirmDialog";
import { useToast } from "@/hooks/useToast";
import { useConfirmDelete } from "@/hooks/useConfirmDelete";
import { Toast } from "@/components/Toast";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectOption } from "@/components/ui/select";
import { Segmented } from "@/components/ui/segmented";
import { RouteSkeleton } from "@/components/route-skeletons";
import { useI18n } from "@/i18n";
import { usePageHeader } from "@/contexts/usePageHeader";
import type { AgentHubAgent } from "@/lib/api-types";

/* ------------------------------------------------------------------ */
/*  Schedule helpers (unchanged from previous version)                 */
/* ------------------------------------------------------------------ */

function formatTime(iso?: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleString();
}

function formatRelative(iso?: string | null): string {
  if (!iso) return "never";
  const d = new Date(iso);
  const diff = d.getTime() - Date.now();
  const abs = Math.abs(diff);
  const m = Math.round(abs / 60000);
  if (m < 1) return diff > 0 ? "moments away" : "just now";
  if (m < 60) return diff > 0 ? `in ${m}m` : `${m}m ago`;
  const h = Math.round(m / 60);
  if (h < 24) return diff > 0 ? `in ${h}h` : `${h}h ago`;
  const days = Math.round(h / 24);
  return diff > 0 ? `in ${days}d` : `${days}d ago`;
}

const STATUS_VARIANT: Record<string, "success" | "warning" | "destructive"> = {
  enabled: "success",
  scheduled: "success",
  paused: "warning",
  error: "destructive",
  completed: "destructive",
};

type JobKindFilter = "all" | "automations" | "heartbeats";
type CreateJobKind = "automation" | "heartbeat";
type ReportMode = "quiet" | "notify";

const HEARTBEAT_ORIGIN_TYPES = new Set([
  "heartbeat",
  "surface-heartbeat",
  "cortext-native-loop",
]);

const JOB_KIND_OPTIONS: Array<{ label: string; value: JobKindFilter }> = [
  { label: "All", value: "all" },
  { label: "Automations", value: "automations" },
  { label: "Heartbeats", value: "heartbeats" },
];

const CREATE_KIND_OPTIONS: Array<{ label: string; value: CreateJobKind }> = [
  { label: "Automation", value: "automation" },
  { label: "Heartbeat", value: "heartbeat" },
];

const REPORT_MODE_OPTIONS: Array<{ label: string; value: ReportMode }> = [
  { label: "Only important changes", value: "quiet" },
  { label: "Every run", value: "notify" },
];

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function cronOriginType(job: CronJob): string {
  return String(job.origin?.type || "");
}

function isHeartbeatJob(job: CronJob): boolean {
  return HEARTBEAT_ORIGIN_TYPES.has(cronOriginType(job));
}

function normalizeJobKindFilter(value: unknown): JobKindFilter {
  const raw = String(value || "").trim().toLowerCase();
  if (raw === "heartbeat" || raw === "heartbeats") return "heartbeats";
  if (raw === "automation" || raw === "automations") return "automations";
  return "all";
}

function normalizeReportMode(value: unknown): ReportMode {
  const raw = String(value || "").trim().toLowerCase().replace(/_/g, "-");
  if (["notify", "notifying", "always", "always-notify", "every-run", "report"].includes(raw)) {
    return "notify";
  }
  return "quiet";
}

function heartbeatReportMode(job: CronJob): ReportMode {
  const metadata = asRecord(job.metadata);
  const origin = asRecord(job.origin);
  return normalizeReportMode(
    metadata.heartbeat_report_mode ||
      metadata.report_mode ||
      metadata.notification_mode ||
      origin.heartbeat_report_mode ||
      origin.report_mode ||
      origin.notification_mode ||
      "quiet",
  );
}

function withHeartbeatReportMode(
  metadata: Record<string, unknown> | undefined,
  mode: ReportMode,
): Record<string, unknown> {
  return { ...(metadata || {}), heartbeat_report_mode: mode };
}

function jobKindLabel(job: CronJob): string {
  return isHeartbeatJob(job) ? "Heartbeat" : "Automation";
}

function notifyCronSidebarChanged(): void {
  if (typeof window === "undefined") return;
  const emit = () => window.dispatchEvent(new CustomEvent("elevate:cron-jobs-changed"));
  emit();
  window.setTimeout(emit, 1500);
  window.setTimeout(emit, 5000);
}

type ScheduleMode =
  | "daily"
  | "weekdays"
  | "weekly"
  | "biweekly"
  | "monthly"
  | "custom";

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
      helper:
        "Anchors the first run to the next selected weekday and repeats every 14 days.",
    };
  }

  return {
    description: `Monthly on day ${safeMonthDay} at ${time}`,
    expression: `${minute} ${hour} ${safeMonthDay} * *`,
    helper: "Runs once per month on the selected calendar day.",
  };
}

function inferScheduleMode(expr: string): {
  mode: ScheduleMode;
  time: string;
  dayOfWeek: string;
  dayOfMonth: string;
  customSchedule: string;
} {
  const fallback = {
    mode: "custom" as ScheduleMode,
    time: "09:00",
    dayOfWeek: "monday",
    dayOfMonth: "1",
    customSchedule: expr,
  };
  if (!expr) return fallback;
  const trimmed = expr.trim();
  const biweeklyMatch = trimmed.match(
    /^every\s+2w\s+on\s+(\w+)\s+at\s+(\d{1,2}):(\d{2})$/i,
  );
  if (biweeklyMatch) {
    const anchor = biweeklyMatch[1].toLowerCase();
    const weekday = WEEKDAYS.find((day) => day.value === anchor) ?? WEEKDAYS[0];
    return {
      mode: "biweekly",
      time: `${biweeklyMatch[2].padStart(2, "0")}:${biweeklyMatch[3]}`,
      dayOfWeek: weekday.value,
      dayOfMonth: "1",
      customSchedule: trimmed,
    };
  }
  const cronMatch = trimmed.match(/^(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)$/);
  if (!cronMatch) return fallback;
  const [, minute, hour, dom, month, dow] = cronMatch;
  const minuteNum = Number(minute);
  const hourNum = Number(hour);
  if (
    !Number.isFinite(minuteNum) ||
    minuteNum < 0 ||
    minuteNum > 59 ||
    !Number.isFinite(hourNum) ||
    hourNum < 0 ||
    hourNum > 23 ||
    month !== "*"
  ) {
    return fallback;
  }
  const time = `${String(hourNum).padStart(2, "0")}:${String(minuteNum).padStart(2, "0")}`;
  if (dom === "*" && dow === "*") {
    return { ...fallback, mode: "daily", time };
  }
  if (dom === "*" && dow === "1-5") {
    return { ...fallback, mode: "weekdays", time };
  }
  if (dom === "*") {
    const weekday = WEEKDAYS.find((day) => day.cron === dow);
    if (weekday) {
      return { ...fallback, mode: "weekly", time, dayOfWeek: weekday.value };
    }
  }
  if (dow === "*") {
    const day = Number(dom);
    if (Number.isFinite(day) && day >= 1 && day <= 31) {
      return { ...fallback, mode: "monthly", time, dayOfMonth: String(day) };
    }
  }
  return fallback;
}

function ScheduleFields({
  customSchedule,
  dayOfMonth,
  dayOfWeek,
  idPrefix,
  scheduleMode,
  setCustomSchedule,
  setDayOfMonth,
  setDayOfWeek,
  setScheduleMode,
  setTime,
  time,
}: {
  customSchedule: string;
  dayOfMonth: string;
  dayOfWeek: string;
  idPrefix: string;
  scheduleMode: ScheduleMode;
  setCustomSchedule: (v: string) => void;
  setDayOfMonth: (v: string) => void;
  setDayOfWeek: (v: string) => void;
  setScheduleMode: (v: ScheduleMode) => void;
  setTime: (v: string) => void;
  time: string;
}) {
  const { t } = useI18n();
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
  return (
    <div className="grid gap-3 rounded-md border border-border bg-card p-3">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
        <div className="min-w-0">
          <Label htmlFor={`${idPrefix}-schedule-mode`}>{t.cron.schedule}</Label>
          <div className="mt-1 flex items-center gap-2 text-xs text-muted-foreground">
            <CalendarDays className="h-3.5 w-3.5" />
            <span>{schedule.description}</span>
          </div>
        </div>
        <Segmented
          className="flex flex-wrap justify-start rounded-md bg-card p-1"
          onChange={(value) => setScheduleMode(value)}
          options={SCHEDULE_OPTIONS}
          size="sm"
          value={scheduleMode}
        />
      </div>

      {scheduleMode === "custom" ? (
        <div className="grid gap-2">
          <Label htmlFor={`${idPrefix}-schedule`}>
            {t.cron.schedulePlaceholder}
          </Label>
          <Input
            id={`${idPrefix}-schedule`}
            placeholder="0 9 * * *"
            value={customSchedule}
            onChange={(e) => setCustomSchedule(e.target.value)}
          />
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          <div className="grid gap-2">
            <Label htmlFor={`${idPrefix}-time`}>Time</Label>
            <Input
              id={`${idPrefix}-time`}
              type="time"
              value={time}
              onChange={(e) => setTime(e.target.value || "09:00")}
            />
          </div>

          {(scheduleMode === "weekly" || scheduleMode === "biweekly") && (
            <div className="grid gap-2">
              <Label htmlFor={`${idPrefix}-weekday`}>Day</Label>
              <Select
                id={`${idPrefix}-weekday`}
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
              <Label htmlFor={`${idPrefix}-month-day`}>Day of month</Label>
              <Select
                id={`${idPrefix}-month-day`}
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

      <div className="flex flex-col gap-2 rounded-md bg-card px-3 py-2 text-xs text-muted-foreground sm:flex-row sm:items-center sm:justify-between">
        <span>{schedule.helper}</span>
        <code className="w-fit rounded-lg bg-foreground/10 px-2 py-1 font-mono text-[0.72rem] text-foreground">
          {schedule.expression || "schedule required"}
        </code>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Inline edit form                                                   */
/* ------------------------------------------------------------------ */

function EditJobForm({
  agents,
  job,
  onCancel,
  onSaved,
}: {
  agents: AgentHubAgent[];
  job: CronJob;
  onCancel: () => void;
  onSaved: () => void;
}) {
  const { t } = useI18n();
  const { showToast } = useToast();
  const initial = useMemo(
    () =>
      inferScheduleMode(
        (job.schedule?.expr as string) || job.schedule_display || "",
      ),
    [job.id, job.schedule_display],
  );
  const [name, setName] = useState(job.name ?? "");
  const [prompt, setPrompt] = useState(job.prompt ?? "");
  const [deliver, setDeliver] = useState(job.deliver ?? "local");
  const [agent, setAgent] = useState(job.agent ?? "");
  const isHeartbeat = isHeartbeatJob(job);
  const [reportMode, setReportMode] = useState<ReportMode>(heartbeatReportMode(job));
  const [scheduleMode, setScheduleMode] = useState<ScheduleMode>(initial.mode);
  const [time, setTime] = useState(initial.time);
  const [dayOfWeek, setDayOfWeek] = useState(initial.dayOfWeek);
  const [dayOfMonth, setDayOfMonth] = useState(initial.dayOfMonth);
  const [customSchedule, setCustomSchedule] = useState(initial.customSchedule);
  const [saving, setSaving] = useState(false);
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

  const handleSave = async () => {
    if (!prompt.trim() || !schedule.expression.trim()) {
      showToast(`${t.cron.prompt} & ${t.cron.schedule} required`, "error");
      return;
    }
    setSaving(true);
    try {
      const updates: Record<string, unknown> = {
        name: name.trim(),
        prompt: prompt.trim(),
        schedule: schedule.expression.trim(),
        deliver,
        agent: agent || null,
      };
      if (isHeartbeat) {
        updates.metadata = withHeartbeatReportMode(asRecord(job.metadata), reportMode);
      }
      await api.updateCronJob(job.id, updates);
      showToast(`Saved "${name.trim() || prompt.trim().slice(0, 30)}"`, "success");
      onSaved();
    } catch (e) {
      showToast(`${t.config.failedToSave}: ${e}`, "error");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="grid gap-4">
      {isHeartbeat && (
        <div className="grid gap-2">
          <Label htmlFor={`edit-${job.id}-report-mode`}>Report mode</Label>
          <Select
            id={`edit-${job.id}-report-mode`}
            value={reportMode}
            onValueChange={(v) => setReportMode(normalizeReportMode(v))}
          >
            {REPORT_MODE_OPTIONS.map((option) => (
              <SelectOption key={option.value} value={option.value}>
                {option.label}
              </SelectOption>
            ))}
          </Select>
        </div>
      )}

      <div className="grid gap-2">
        <Label htmlFor={`edit-${job.id}-name`}>{t.cron.nameOptional}</Label>
        <Input
          id={`edit-${job.id}-name`}
          placeholder={t.cron.namePlaceholder}
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
      </div>
      <div className="grid gap-2">
        <Label htmlFor={`edit-${job.id}-prompt`}>{t.cron.prompt}</Label>
        <textarea
          id={`edit-${job.id}-prompt`}
          className="flex min-h-[140px] w-full rounded-md border border-input bg-card px-3 py-2 text-sm shadow-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
        />
      </div>
      <ScheduleFields
        customSchedule={customSchedule}
        dayOfMonth={dayOfMonth}
        dayOfWeek={dayOfWeek}
        idPrefix={`edit-${job.id}`}
        scheduleMode={scheduleMode}
        setCustomSchedule={setCustomSchedule}
        setDayOfMonth={setDayOfMonth}
        setDayOfWeek={setDayOfWeek}
        setScheduleMode={setScheduleMode}
        setTime={setTime}
        time={time}
      />
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <div className="grid gap-2">
          <Label htmlFor={`edit-${job.id}-deliver`}>{t.cron.deliverTo}</Label>
          <Select
            id={`edit-${job.id}-deliver`}
            value={deliver}
            onValueChange={(v) => setDeliver(v)}
          >
            <SelectOption value="local">{t.cron.delivery.local}</SelectOption>
            <SelectOption value="telegram">
              {t.cron.delivery.telegram}
            </SelectOption>
            <SelectOption value="discord">
              {t.cron.delivery.discord}
            </SelectOption>
            <SelectOption value="slack">{t.cron.delivery.slack}</SelectOption>
            <SelectOption value="email">{t.cron.delivery.email}</SelectOption>
          </Select>
        </div>
        <div className="grid gap-2">
          <Label htmlFor={`edit-${job.id}-agent`}>Run as agent</Label>
          <Select
            id={`edit-${job.id}-agent`}
            value={agent}
            onValueChange={(v) => setAgent(v)}
          >
            <SelectOption value="">Default agent</SelectOption>
            {agents
              .filter((a) => a.enabled)
              .map((a) => (
                <SelectOption key={a.id} value={a.id}>
                  {a.name}
                </SelectOption>
              ))}
          </Select>
        </div>
      </div>
      <div className="flex justify-end gap-2">
        <div className="flex items-end gap-2">
          <Button variant="ghost" onClick={onCancel} disabled={saving}>
            <X className="h-3.5 w-3.5" />
            {t.common.cancel}
          </Button>
          <Button onClick={handleSave} disabled={saving}>
            <Check className="h-3.5 w-3.5" />
            {saving ? t.common.saving : t.common.save}
          </Button>
        </div>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Create new job form                                                */
/* ------------------------------------------------------------------ */

function NewJobForm({
  agents,
  defaultKind,
  onCancel,
  onCreated,
}: {
  agents: AgentHubAgent[];
  defaultKind: CreateJobKind;
  onCancel: () => void;
  onCreated: () => void;
}) {
  const { t } = useI18n();
  const { showToast } = useToast();
  const [prompt, setPrompt] = useState("");
  const [scheduleMode, setScheduleMode] = useState<ScheduleMode>("daily");
  const [time, setTime] = useState("09:00");
  const [dayOfWeek, setDayOfWeek] = useState("monday");
  const [dayOfMonth, setDayOfMonth] = useState("1");
  const [customSchedule, setCustomSchedule] = useState("0 9 * * *");
  const [name, setName] = useState("");
  const [deliver, setDeliver] = useState("local");
  const [agent, setAgent] = useState("");
  const [kind, setKind] = useState<CreateJobKind>(defaultKind);
  const [reportMode, setReportMode] = useState<ReportMode>("quiet");
  const [creating, setCreating] = useState(false);

  useEffect(() => {
    setKind(defaultKind);
  }, [defaultKind]);

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
        agent: agent || undefined,
        metadata:
          kind === "heartbeat"
            ? withHeartbeatReportMode(undefined, reportMode)
            : undefined,
        origin:
          kind === "heartbeat"
            ? { type: "heartbeat", source: "automations-page" }
            : undefined,
      });
      showToast(t.common.create + " ✓", "success");
      onCreated();
    } catch (e) {
      showToast(`${t.config.failedToSave}: ${e}`, "error");
    } finally {
      setCreating(false);
    }
  };

  return (
    <div className="grid gap-4">
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <div className="grid gap-2">
          <Label htmlFor="cron-kind">Type</Label>
          <Select
            id="cron-kind"
            value={kind}
            onValueChange={(v) => setKind(v === "heartbeat" ? "heartbeat" : "automation")}
          >
            {CREATE_KIND_OPTIONS.map((option) => (
              <SelectOption key={option.value} value={option.value}>
                {option.label}
              </SelectOption>
            ))}
          </Select>
        </div>
        {kind === "heartbeat" && (
          <div className="grid gap-2">
            <Label htmlFor="cron-report-mode">Report mode</Label>
            <Select
              id="cron-report-mode"
              value={reportMode}
              onValueChange={(v) => setReportMode(normalizeReportMode(v))}
            >
              {REPORT_MODE_OPTIONS.map((option) => (
                <SelectOption key={option.value} value={option.value}>
                  {option.label}
                </SelectOption>
              ))}
            </Select>
          </div>
        )}
      </div>

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
          className="flex min-h-[120px] w-full rounded-md border border-input bg-card px-3 py-2 text-sm shadow-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
          placeholder={t.cron.promptPlaceholder}
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
        />
      </div>

      <ScheduleFields
        customSchedule={customSchedule}
        dayOfMonth={dayOfMonth}
        dayOfWeek={dayOfWeek}
        idPrefix="cron"
        scheduleMode={scheduleMode}
        setCustomSchedule={setCustomSchedule}
        setDayOfMonth={setDayOfMonth}
        setDayOfWeek={setDayOfWeek}
        setScheduleMode={setScheduleMode}
        setTime={setTime}
        time={time}
      />

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <div className="grid gap-2">
          <Label htmlFor="cron-deliver">{t.cron.deliverTo}</Label>
          <Select
            id="cron-deliver"
            value={deliver}
            onValueChange={(v) => setDeliver(v)}
          >
            <SelectOption value="local">{t.cron.delivery.local}</SelectOption>
            <SelectOption value="telegram">
              {t.cron.delivery.telegram}
            </SelectOption>
            <SelectOption value="discord">
              {t.cron.delivery.discord}
            </SelectOption>
            <SelectOption value="slack">{t.cron.delivery.slack}</SelectOption>
            <SelectOption value="email">{t.cron.delivery.email}</SelectOption>
          </Select>
        </div>
        <div className="grid gap-2">
          <Label htmlFor="cron-agent">Run as agent</Label>
          <Select
            id="cron-agent"
            value={agent}
            onValueChange={(v) => setAgent(v)}
          >
            <SelectOption value="">Default agent</SelectOption>
            {agents
              .filter((a) => a.enabled)
              .map((a) => (
                <SelectOption key={a.id} value={a.id}>
                  {a.name}
                </SelectOption>
              ))}
          </Select>
        </div>
      </div>
      <div className="flex justify-end gap-2">
        <div className="flex items-end gap-2">
          <Button variant="ghost" onClick={onCancel} disabled={creating}>
            <X className="h-3.5 w-3.5" />
            {t.common.cancel}
          </Button>
          <Button onClick={handleCreate} disabled={creating}>
            <Plus className="h-3.5 w-3.5" />
            {creating ? t.common.creating : t.common.create}
          </Button>
        </div>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Left rail: job row                                                 */
/* ------------------------------------------------------------------ */

function JobRailRow({
  job,
  selected,
  onSelect,
}: {
  job: CronJob;
  selected: boolean;
  onSelect: () => void;
}) {
  const isPaused = job.state === "paused";
  const isError = job.state === "error";
  const title = job.name || job.prompt.slice(0, 60);

  return (
    <button
      type="button"
      onClick={onSelect}
      className={`group w-full rounded-md px-2.5 py-2 text-left transition-colors ${
        selected
          ? "bg-primary/10 text-foreground"
          : "hover:bg-foreground/[0.04] text-foreground/90"
      }`}
    >
      <div className="flex items-start gap-2">
        <span
          className={`mt-1 h-1.5 w-1.5 shrink-0 rounded-full ${
            isError
              ? "bg-destructive"
              : isPaused
                ? "bg-warning"
                : "bg-success"
          }`}
          aria-hidden
        />
        <div className="min-w-0 flex-1">
          <div
            className={`truncate text-[12px] font-medium leading-tight ${
              isPaused ? "text-muted-foreground" : ""
            }`}
          >
            {title}
            {job.prompt.length > 60 && !job.name ? "…" : ""}
          </div>
          <div className="mt-0.5 flex items-center gap-1.5 text-[10px] text-muted-foreground/80">
            <Clock className="h-2.5 w-2.5" />
            <span className="truncate">{job.schedule_display}</span>
            <span className="shrink-0 rounded border border-border px-1 text-[9px] uppercase tracking-wide">
              {jobKindLabel(job)}
            </span>
          </div>
        </div>
        {isError && (
          <AlertCircle className="mt-0.5 h-3 w-3 shrink-0 text-destructive" />
        )}
      </div>
    </button>
  );
}

/* ------------------------------------------------------------------ */
/*  Right detail pane                                                  */
/* ------------------------------------------------------------------ */

function JobDetail({
  agents,
  job,
  isEditing,
  onEditToggle,
  onPauseResume,
  onTrigger,
  onDelete,
  onSaved,
  onCancelEdit,
}: {
  agents: AgentHubAgent[];
  job: CronJob;
  isEditing: boolean;
  onEditToggle: () => void;
  onPauseResume: () => void;
  onTrigger: () => void;
  onDelete: () => void;
  onSaved: () => void;
  onCancelEdit: () => void;
}) {
  const { t } = useI18n();
  const isPaused = job.state === "paused";
  const isHeartbeat = isHeartbeatJob(job);
  const reportMode = heartbeatReportMode(job);

  return (
    <div className="flex flex-1 flex-col overflow-y-auto">
      {/* Header */}
      <div className="sticky top-0 z-10 border-b border-border bg-card/95 backdrop-blur">
        <div className="flex items-start gap-3 px-5 py-4">
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="truncate text-base font-medium">
                {job.name || job.prompt.slice(0, 60)}
                {!job.name && job.prompt.length > 60 ? "…" : ""}
              </h2>
              <Badge variant={STATUS_VARIANT[job.state] ?? "secondary"}>
                {job.state}
              </Badge>
              <Badge variant="outline">{jobKindLabel(job)}</Badge>
              {isHeartbeat && (
                <Badge variant="secondary">
                  {reportMode === "notify" ? "Every run" : "Important changes"}
                </Badge>
              )}
              {job.deliver && job.deliver !== "local" && (
                <Badge variant="outline">{job.deliver}</Badge>
              )}
            </div>
            <p className="mt-1 flex items-center gap-1.5 text-[11px] text-muted-foreground">
              <CalendarDays className="h-3 w-3" />
              <span className="font-mono">{job.schedule_display}</span>
            </p>
          </div>

          <div className="flex shrink-0 items-center gap-1">
            <Button
              variant="ghost"
              size="icon"
              title={isEditing ? t.common.cancel : "Edit"}
              aria-label={isEditing ? t.common.cancel : "Edit"}
              onClick={onEditToggle}
            >
              {isEditing ? (
                <X className="h-4 w-4" />
              ) : (
                <Pencil className="h-4 w-4" />
              )}
            </Button>
            <Button
              variant="ghost"
              size="icon"
              title={isPaused ? t.cron.resume : t.cron.pause}
              aria-label={isPaused ? t.cron.resume : t.cron.pause}
              onClick={onPauseResume}
            >
              {isPaused ? (
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
              onClick={onTrigger}
            >
              <Zap className="h-4 w-4" />
            </Button>
            <Button
              variant="ghost"
              size="icon"
              title={t.common.delete}
              aria-label={t.common.delete}
              onClick={onDelete}
            >
              <Trash2 className="h-4 w-4 text-destructive" />
            </Button>
          </div>
        </div>
      </div>

      {/* Body */}
      <div className="flex-1 px-5 py-5">
        {isEditing ? (
          <EditJobForm
            agents={agents}
            job={job}
            onCancel={onCancelEdit}
            onSaved={onSaved}
          />
        ) : (
          <>
            {/* Meta grid */}
            <div className="mb-5 grid grid-cols-1 gap-3 sm:grid-cols-2">
              <MetaCell
                icon={<Clock className="h-3 w-3" />}
                label={t.cron.last}
                value={formatTime(job.last_run_at)}
                hint={
                  job.last_run_at ? formatRelative(job.last_run_at) : undefined
                }
              />
              <MetaCell
                icon={<CalendarDays className="h-3 w-3" />}
                label={t.cron.next}
                value={formatTime(job.next_run_at)}
                hint={
                  job.next_run_at ? formatRelative(job.next_run_at) : undefined
                }
              />
              <MetaCell
                icon={<Send className="h-3 w-3" />}
                label="Type"
                value={jobKindLabel(job)}
                hint={
                  isHeartbeat
                    ? reportMode === "notify"
                      ? "reports every run"
                      : "quiet unless useful"
                    : undefined
                }
              />
              <MetaCell
                icon={<Send className="h-3 w-3" />}
                label={t.cron.deliverTo}
                value={job.deliver || "local"}
              />
              {job.agent && (
                <MetaCell
                  icon={<MessageSquare className="h-3 w-3" />}
                  label="Agent"
                  value={job.agent}
                />
              )}
            </div>

            {job.last_error && (
              <div className="mb-5 flex items-start gap-2 rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-xs text-destructive">
                <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                <div className="min-w-0 break-words">{job.last_error}</div>
              </div>
            )}

            {job.last_summary && !job.last_error && (
              <section className="mb-5">
                <div className="mb-2 flex items-center gap-1.5 text-[10px] font-medium uppercase tracking-wide text-muted-foreground/70">
                  <MessageSquare className="h-3 w-3" />
                  Last run summary
                </div>
                <div className="whitespace-pre-wrap rounded-md border border-border bg-card/50 px-3 py-3 text-[12.5px] leading-relaxed text-foreground/90">
                  {job.last_summary}
                </div>
              </section>
            )}

            {/* Prompt */}
            <section>
              <div className="mb-2 flex items-center gap-1.5 text-[10px] font-medium uppercase tracking-wide text-muted-foreground/70">
                <MessageSquare className="h-3 w-3" />
                {t.cron.prompt}
              </div>
              <pre className="whitespace-pre-wrap rounded-md border border-border bg-card/50 px-3 py-3 text-[12.5px] leading-relaxed text-foreground/90 font-sans">
                {job.prompt}
              </pre>
            </section>
          </>
        )}
      </div>
    </div>
  );
}

function MetaCell({
  icon,
  label,
  value,
  hint,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  hint?: string;
}) {
  return (
    <div className="rounded-md border border-border bg-card/40 px-3 py-2">
      <div className="flex items-center gap-1.5 text-[10px] uppercase tracking-wide text-muted-foreground/70">
        {icon}
        <span>{label}</span>
      </div>
      <div className="mt-1 truncate text-[12.5px] text-foreground">
        {value}
      </div>
      {hint && (
        <div className="text-[10px] text-muted-foreground/70">{hint}</div>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Page                                                               */
/* ------------------------------------------------------------------ */

export default function CronPage() {
  const [jobs, setJobs] = useState<CronJob[]>([]);
  const [agents, setAgents] = useState<AgentHubAgent[]>([]);
  const [attention, setAttention] = useState<import("../lib/api-types").CronAttention | null>(null);
  const [loading, setLoading] = useState(true);
  const [searchParams, setSearchParams] = useSearchParams();
  const editParam = searchParams.get("edit");
  const agentParam = searchParams.get("agent") ?? "";
  const kindFilter = normalizeJobKindFilter(searchParams.get("kind"));
  const [selectedId, setSelectedId] = useState<string | null>(editParam);
  const [editingId, setEditingId] = useState<string | null>(editParam);
  const [showCreate, setShowCreate] = useState(false);
  const [search, setSearch] = useState(agentParam);
  const [agentFilter, setAgentFilter] = useState(agentParam);
  const { toast, showToast } = useToast();
  const { t } = useI18n();
  const { setAfterTitle, setEnd } = usePageHeader();

  /* ---- Sync selected/editing with ?edit= deep link ---- */
  useEffect(() => {
    if (editParam) {
      setSelectedId(editParam);
      setEditingId(editParam);
    }
  }, [editParam]);

  useEffect(() => {
    setAgentFilter(agentParam);
  }, [agentParam]);

  useEffect(() => {
    api
      .getAgentHub({ lite: true })
      .then((snap) => setAgents(snap.agents || []))
      .catch(() => setAgents([]));
  }, []);

  const closeEditor = useCallback(() => {
    setEditingId(null);
    if (editParam) {
      setSearchParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          next.delete("edit");
          return next;
        },
        { replace: true },
      );
    }
  }, [editParam, setSearchParams]);

  /* ---- Load jobs ---- */
  const loadJobs = useCallback((options?: { refresh?: boolean }) => {
    api
      .getCronJobs({ refresh: options?.refresh })
      .then((next) => {
        setJobs(next);
        // Auto-select first job if nothing selected
        if (next.length > 0 && !selectedId) {
          setSelectedId(next[0].id);
        }
      })
      .catch(() => showToast(t.common.loading, "error"))
      .finally(() => setLoading(false));
  }, [selectedId, showToast, t.common.loading]);

  useEffect(() => {
    loadJobs();
    const interval = window.setInterval(() => {
      if (document.visibilityState === "visible") loadJobs();
    }, 15_000);
    return () => window.clearInterval(interval);
  }, [loadJobs]);
  useRefreshOnAgentTurn(() => void loadJobs({ refresh: true }));

  /* ---- Load attention rollup ---- */
  const loadAttention = useCallback(() => {
    api
      .getCronAttention()
      .then(setAttention)
      .catch(() => {
        /* silent; banner just won't show */
      });
  }, []);

  useEffect(() => {
    loadAttention();
    const interval = window.setInterval(() => {
      if (document.visibilityState === "visible") loadAttention();
    }, 30_000);
    return () => window.clearInterval(interval);
  }, [loadAttention]);

  /* ---- Filter ---- */
  const lowerSearch = search.trim().toLowerCase();
  const filteredJobs = useMemo(() => {
    const cleanAgent = agentFilter.trim();
    return jobs.filter((job) => {
      if (kindFilter === "heartbeats" && !isHeartbeatJob(job)) return false;
      if (kindFilter === "automations" && isHeartbeatJob(job)) return false;
      if (cleanAgent && (job.agent ?? "") !== cleanAgent) return false;
      if (!lowerSearch) return true;
      return (
        (job.name ?? "").toLowerCase().includes(lowerSearch) ||
        (job.agent ?? "").toLowerCase().includes(lowerSearch) ||
        job.prompt.toLowerCase().includes(lowerSearch) ||
        job.schedule_display.toLowerCase().includes(lowerSearch)
      );
    });
  }, [agentFilter, jobs, kindFilter, lowerSearch]);

  useEffect(() => {
    if (filteredJobs.length === 0) {
      if (selectedId) setSelectedId(null);
      return;
    }
    if (!selectedId || !filteredJobs.some((job) => job.id === selectedId)) {
      setSelectedId(filteredJobs[0].id);
    }
  }, [filteredJobs, selectedId]);

  /* ---- Group jobs by status for rail sections ---- */
  const activeJobs = useMemo(
    () => filteredJobs.filter((j) => j.state !== "paused" && j.state !== "completed"),
    [filteredJobs],
  );
  const pausedJobs = useMemo(
    () => filteredJobs.filter((j) => j.state === "paused"),
    [filteredJobs],
  );

  const selectedJob = useMemo(
    () => jobs.find((j) => j.id === selectedId) ?? null,
    [jobs, selectedId],
  );

  /* ---- Page header (count + search + new) ---- */
  const enabledCount = filteredJobs.filter((j) => j.state !== "paused").length;
  const heartbeatCount = jobs.filter(isHeartbeatJob).length;
  const automationCount = jobs.length - heartbeatCount;
  const emptyJobsMessage =
    kindFilter === "heartbeats"
      ? "No heartbeats yet. Create one here, or switch to All."
      : kindFilter === "automations"
        ? "No automations yet. Create one here, or switch to All."
        : t.cron.noJobs;
  const updateAgentFilter = useCallback(
    (nextAgent: string) => {
      setAgentFilter(nextAgent);
      setSearchParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          if (nextAgent) next.set("agent", nextAgent);
          else next.delete("agent");
          return next;
        },
        { replace: true },
      );
    },
    [setSearchParams],
  );
  const updateKindFilter = useCallback(
    (nextKind: JobKindFilter) => {
      setSearchParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          if (nextKind === "all") next.delete("kind");
          else next.set("kind", nextKind);
          return next;
        },
        { replace: true },
      );
    },
    [setSearchParams],
  );

  useLayoutEffect(() => {
    if (loading) {
      setAfterTitle(null);
      setEnd(null);
      return;
    }
    setAfterTitle(
      <span className="whitespace-nowrap text-xs text-muted-foreground">
        {enabledCount}/{filteredJobs.length} active · {automationCount} automations ·{" "}
        {heartbeatCount} heartbeats
      </span>,
    );
    setEnd(
      <div className="flex flex-wrap items-center justify-end gap-2">
        <Select value={agentFilter} onValueChange={updateAgentFilter}>
          <SelectOption value="">All agents</SelectOption>
          {agents.map((agent) => (
            <SelectOption key={agent.id} value={agent.id}>
              {agent.name}
            </SelectOption>
          ))}
        </Select>
        <div className="relative w-full min-w-0 sm:max-w-xs">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
          <Input
            className="h-8 pl-8 pr-7 text-xs"
            placeholder={t.common.search}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
          {search && (
            <button
              type="button"
              className="absolute right-2.5 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
              onClick={() => setSearch("")}
            >
              <X className="h-3 w-3" />
            </button>
          )}
        </div>
        <Button
          size="sm"
          variant={showCreate ? "outline" : "default"}
          onClick={() => {
            setShowCreate((v) => !v);
            if (!showCreate) {
              setEditingId(null);
            }
          }}
        >
          {showCreate ? (
            <>
              <X className="h-3.5 w-3.5" />
              {t.common.cancel}
            </>
          ) : (
            <>
              <Plus className="h-3.5 w-3.5" />
              {t.cron.newJob}
            </>
          )}
        </Button>
      </div>,
    );
    return () => {
      setAfterTitle(null);
      setEnd(null);
    };
  }, [
    agentFilter,
    agents,
    automationCount,
    enabledCount,
    filteredJobs.length,
    heartbeatCount,
    loading,
    search,
    setAfterTitle,
    setEnd,
    showCreate,
    t,
    updateAgentFilter,
  ]);

  /* ---- Actions ---- */
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
      notifyCronSidebarChanged();
      loadJobs({ refresh: true });
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
      notifyCronSidebarChanged();
      loadJobs({ refresh: true });
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
          // If deleted the selected one, clear or move to next
          setSelectedId((prev) => {
            if (prev !== id) return prev;
            const remaining = jobs.filter((j) => j.id !== id);
            return remaining[0]?.id ?? null;
          });
          notifyCronSidebarChanged();
          loadJobs({ refresh: true });
        } catch (e) {
          showToast(`${t.status.error}: ${e}`, "error");
          throw e;
        }
      },
      [jobs, loadJobs, showToast, t.common.delete, t.status.error],
    ),
  });

  /* ---- Loading ---- */
  if (loading) {
    return <RouteSkeleton path="/cron" />;
  }

  const pendingJob = jobDelete.pendingId
    ? jobs.find((j) => j.id === jobDelete.pendingId)
    : null;

  return (
    <div className="flex flex-col gap-4">
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

      <div className="flex flex-col gap-2 rounded-md border border-border bg-card/50 px-3 py-2 sm:flex-row sm:items-center sm:justify-between">
        <div className="min-w-0 text-[11px] text-muted-foreground">
          <span className="font-medium text-foreground">Scheduled runs</span>
          <span className="mx-2 text-muted-foreground/50">·</span>
          <span>{automationCount} automations</span>
          <span className="mx-2 text-muted-foreground/50">·</span>
          <span>{heartbeatCount} heartbeats</span>
        </div>
        <Segmented
          className="w-fit rounded-md bg-card p-1"
          onChange={(value) => updateKindFilter(normalizeJobKindFilter(value))}
          options={JOB_KIND_OPTIONS}
          size="sm"
          value={kindFilter}
        />
      </div>

      {attention && attention.total > 0 && (
        <div className="rounded-md border border-amber-500/40 bg-amber-500/[0.06] px-4 py-3 text-xs">
          <div className="mb-2 flex items-center gap-2 font-medium text-amber-700 dark:text-amber-300">
            <AlertCircle className="h-3.5 w-3.5" />
            <span>Needs attention ({attention.total})</span>
          </div>
          <div className="flex flex-col gap-1.5 text-foreground/85">
            {attention.pending_drafts > 0 && (
              <div>
                <span className="font-medium">{attention.pending_drafts}</span>{" "}
                {attention.pending_drafts === 1 ? "outreach draft" : "outreach drafts"} waiting on review
              </div>
            )}
            {attention.errored_jobs.map((j) => (
              <button
                key={`err-${j.id}`}
                type="button"
                onClick={() => {
                  setSelectedId(j.id);
                  setShowCreate(false);
                }}
                className="text-left underline-offset-2 hover:underline"
              >
                <span className="text-destructive">Error</span>{" "}
                <span className="font-medium">{j.name || j.id}</span>
                {j.last_error ? <span className="text-muted-foreground"> — {j.last_error}</span> : null}
              </button>
            ))}
            {attention.stale_jobs.map((j) => (
              <button
                key={`stale-${j.id}`}
                type="button"
                onClick={() => {
                  setSelectedId(j.id);
                  setShowCreate(false);
                }}
                className="text-left underline-offset-2 hover:underline"
              >
                <span className="text-amber-700 dark:text-amber-400">Stale</span>{" "}
                <span className="font-medium">{j.name || j.id}</span>
                <span className="text-muted-foreground"> — no run in {j.hours_since}h</span>
              </button>
            ))}
          </div>
        </div>
      )}

      {/* ============ Two-pane shell ============ */}
      <div className="grid min-h-[calc(100vh-12rem)] grid-cols-1 gap-0 rounded-md border border-border bg-card md:grid-cols-[280px_minmax(0,1fr)]">
        {/* ---- Left rail ---- */}
        <aside
          aria-label={t.cron.scheduledJobs}
          className="flex flex-col border-b border-border md:border-b-0 md:border-r"
        >
          <div className="flex items-center justify-between gap-2 border-b border-border px-3 py-2.5">
            <div className="flex items-center gap-2 text-[11px] font-medium tracking-normal text-muted-foreground">
              <Clock className="h-3 w-3" />
              <span>{t.cron.scheduledJobs}</span>
              <span className="text-muted-foreground/60">({filteredJobs.length})</span>
            </div>
          </div>

          <div className="flex-1 overflow-y-auto px-1 py-2">
            {/* Create entry */}
            <button
              type="button"
              onClick={() => {
                setShowCreate(true);
                setEditingId(null);
              }}
              className={`mb-1 flex w-full items-center gap-2 rounded-md px-2.5 py-1.5 text-left text-[12px] transition-colors ${
                showCreate
                  ? "bg-primary/10 text-primary"
                  : "text-muted-foreground hover:bg-foreground/[0.04] hover:text-foreground"
              }`}
            >
              <Plus className="h-3.5 w-3.5" />
              <span>{t.cron.newJob}</span>
            </button>

            <JobRailSection
              label="Active"
              items={activeJobs}
              selectedId={selectedId}
              onSelect={(id) => {
                setSelectedId(id);
                setShowCreate(false);
              }}
              defaultOpen
            />
            <JobRailSection
              label="Paused"
              items={pausedJobs}
              selectedId={selectedId}
              onSelect={(id) => {
                setSelectedId(id);
                setShowCreate(false);
              }}
              defaultOpen={pausedJobs.length > 0 && activeJobs.length === 0}
            />

            {filteredJobs.length === 0 && (
              <p className="px-3 py-6 text-center text-[11px] text-muted-foreground">
                {lowerSearch ? "No jobs match your search." : emptyJobsMessage}
              </p>
            )}
          </div>
        </aside>

        {/* ---- Right pane ---- */}
        <section className="flex min-w-0 flex-col">
          {showCreate ? (
            <div className="flex flex-1 flex-col overflow-y-auto">
              <div className="sticky top-0 z-10 border-b border-border bg-card/95 backdrop-blur">
                <div className="flex items-start gap-3 px-5 py-4">
                  <div className="min-w-0 flex-1">
                    <h2 className="flex items-center gap-2 text-base font-medium">
                      <Plus className="h-4 w-4" />
                      {t.cron.newJob}
                    </h2>
                    <p className="mt-1 text-[11px] text-muted-foreground">
                      Schedule a recurring agent run.
                    </p>
                  </div>
                  <Button
                    variant="ghost"
                    size="icon"
                    aria-label={t.common.cancel}
                    onClick={() => setShowCreate(false)}
                  >
                    <X className="h-4 w-4" />
                  </Button>
                </div>
              </div>
              <div className="px-5 py-5">
                <NewJobForm
                  agents={agents}
                  defaultKind={kindFilter === "heartbeats" ? "heartbeat" : "automation"}
                  onCancel={() => setShowCreate(false)}
                  onCreated={() => {
                    setShowCreate(false);
                    notifyCronSidebarChanged();
                    loadJobs({ refresh: true });
                  }}
                />
              </div>
            </div>
          ) : selectedJob ? (
            <JobDetail
              agents={agents}
              job={selectedJob}
              isEditing={editingId === selectedJob.id}
              onEditToggle={() => {
                if (editingId === selectedJob.id) {
                  closeEditor();
                } else {
                  setEditingId(selectedJob.id);
                }
              }}
              onPauseResume={() => handlePauseResume(selectedJob)}
              onTrigger={() => handleTrigger(selectedJob)}
              onDelete={() => jobDelete.requestDelete(selectedJob.id)}
              onSaved={() => {
                closeEditor();
                notifyCronSidebarChanged();
                loadJobs({ refresh: true });
              }}
              onCancelEdit={closeEditor}
            />
          ) : (
            <div className="flex flex-1 items-center justify-center px-6 py-12">
              <p className="text-xs text-muted-foreground">
                {filteredJobs.length === 0
                  ? emptyJobsMessage
                  : "Select a job from the rail to view its details."}
              </p>
            </div>
          )}
        </section>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Left rail section (Active / Paused)                                */
/* ------------------------------------------------------------------ */

function JobRailSection({
  label,
  items,
  selectedId,
  onSelect,
  defaultOpen,
}: {
  label: string;
  items: CronJob[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  defaultOpen: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);

  useEffect(() => {
    if (defaultOpen) setOpen(true);
  }, [defaultOpen]);

  if (items.length === 0) return null;

  return (
    <div className="mb-2">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-1.5 px-2 py-1 text-[10px] font-medium tracking-wide text-muted-foreground/70 hover:text-foreground transition-colors"
      >
        <ChevronRight
          className={`h-3 w-3 transition-transform ${open ? "rotate-90" : ""}`}
        />
        <span className="uppercase">{label}</span>
        <span className="text-muted-foreground/40">({items.length})</span>
      </button>
      {open && (
        <ul className="mt-0.5 space-y-px">
          {items.map((job) => (
            <li key={job.id}>
              <JobRailRow
                job={job}
                selected={selectedId === job.id}
                onSelect={() => onSelect(job.id)}
              />
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
