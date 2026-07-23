import { useState } from "react";
import { Modal } from "@/components/ui/modal";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { api } from "@/lib/api";
import type { AccountGoals } from "@/lib/api-types";

interface GoalField {
  key: "leadsGoal" | "apptsGoal" | "closingsGoal" | "gciGoal";
  label: string;
}

const FIELDS: GoalField[] = [
  { key: "leadsGoal", label: "New leads (per month)" },
  { key: "apptsGoal", label: "Appointments booked (per month)" },
  { key: "closingsGoal", label: "Closings (per month)" },
  { key: "gciGoal", label: "GCI target (year, $)" },
];

function initialValue(goals: AccountGoals | null, key: GoalField["key"]): string {
  const value = goals?.[key];
  return typeof value === "number" && Number.isFinite(value) ? String(value) : "";
}

/** Set-goals dialog. Saves via PUT /api/crm/goals, then asks the page to refetch. */
export function GoalsModal({
  goals,
  onClose,
  onSaved,
}: {
  goals: AccountGoals | null;
  onClose: () => void;
  onSaved: () => Promise<void> | void;
}) {
  const [values, setValues] = useState<Record<GoalField["key"], string>>(() => ({
    leadsGoal: initialValue(goals, "leadsGoal"),
    apptsGoal: initialValue(goals, "apptsGoal"),
    closingsGoal: initialValue(goals, "closingsGoal"),
    gciGoal: initialValue(goals, "gciGoal"),
  }));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (saving) return;
    const payload: Partial<Record<GoalField["key"], number | null>> = {};
    for (const field of FIELDS) {
      const raw = values[field.key].trim();
      if (raw === "") {
        payload[field.key] = null;
        continue;
      }
      const parsed = Number(raw);
      if (!Number.isFinite(parsed) || parsed < 0) {
        setError(`${field.label} must be a number of 0 or more.`);
        return;
      }
      payload[field.key] = parsed;
    }
    setSaving(true);
    setError(null);
    try {
      await api.putCrmGoals(payload);
      await onSaved();
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Saving goals failed. Try again.");
      setSaving(false);
    }
  };

  return (
    <Modal title="Set your goals" onClose={onClose}>
      <form onSubmit={(event) => void submit(event)} className="report-goal-form">
        <p className="report-goal-form-sub">
          Targets for this period. Progress shows on this page.
        </p>
        {FIELDS.map((field) => (
          <div key={field.key} className="report-goal-field">
            <Label htmlFor={`report-goal-${field.key}`}>{field.label}</Label>
            <Input
              id={`report-goal-${field.key}`}
              type="number"
              min={0}
              step={field.key === "gciGoal" ? 1000 : 1}
              inputMode="numeric"
              value={values[field.key]}
              onChange={(event) =>
                setValues((prev) => ({ ...prev, [field.key]: event.target.value }))
              }
            />
          </div>
        ))}
        {error ? (
          <p className="report-goal-form-error" role="alert">{error}</p>
        ) : null}
        <div className="report-goal-form-foot">
          <Button type="button" variant="ghost" onClick={onClose} disabled={saving}>
            Cancel
          </Button>
          <Button type="submit" disabled={saving}>
            {saving ? "Saving…" : "Save goals"}
          </Button>
        </div>
      </form>
    </Modal>
  );
}
