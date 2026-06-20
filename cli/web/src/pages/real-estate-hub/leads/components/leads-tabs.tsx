export type LeadsTab = "action" | "profiles" | "templates" | "sent";

const TABS: Array<{ id: LeadsTab; label: string }> = [
  { id: "action", label: "Action board" },
  { id: "profiles", label: "Profiles" },
  { id: "templates", label: "Templates" },
  { id: "sent", label: "Sent" },
];

export function LeadsTabs({
  tab,
  onChange,
}: {
  tab: LeadsTab;
  onChange: (t: LeadsTab) => void;
}) {
  return (
    <div className="lb-tabs">
      {TABS.map((t) => (
        <button
          key={t.id}
          type="button"
          className={"lb-tab" + (tab === t.id ? " active" : "")}
          onClick={() => onChange(t.id)}
        >
          {t.label}
        </button>
      ))}
    </div>
  );
}
