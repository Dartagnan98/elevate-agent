export type LeadsTab = "action" | "profiles" | "templates" | "sent" | "didnt-send" | "paid-ads";

const TABS: Array<{ id: LeadsTab; label: string }> = [
  { id: "action", label: "Action board" },
  { id: "profiles", label: "Profiles" },
  { id: "templates", label: "Templates" },
  { id: "sent", label: "Sent" },
  { id: "didnt-send", label: "Didn't Send" },
  { id: "paid-ads", label: "Paid Ads" },
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
