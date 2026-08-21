export type LeadsTab = "leads" | "action" | "templates" | "sent" | "didnt-send";

const TABS: Array<{ id: LeadsTab; label: string }> = [
  { id: "leads", label: "Leads" },
  { id: "action", label: "Action board" },
  { id: "templates", label: "Templates" },
  { id: "sent", label: "Sent" },
  { id: "didnt-send", label: "Didn't Send" },
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
