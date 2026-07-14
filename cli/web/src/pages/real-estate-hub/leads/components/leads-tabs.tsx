export type LeadsTab = "leads" | "templates" | "sent" | "didnt-send";

const TABS: Array<{ id: LeadsTab; label: string }> = [
  { id: "leads", label: "Leads" },
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
    <div className="lb-tabs" role="tablist" aria-label="Lead workspace views">
      {TABS.map((t, index) => (
        <button
          key={t.id}
          type="button"
          role="tab"
          id={`crm-tab-${t.id}`}
          aria-controls={`crm-panel-${t.id}`}
          aria-selected={tab === t.id}
          tabIndex={tab === t.id ? 0 : -1}
          className={"lb-tab" + (tab === t.id ? " active" : "")}
          onClick={() => onChange(t.id)}
          onKeyDown={(event) => {
            let nextIndex = index;
            if (event.key === "ArrowRight") nextIndex = (index + 1) % TABS.length;
            else if (event.key === "ArrowLeft") nextIndex = (index - 1 + TABS.length) % TABS.length;
            else if (event.key === "Home") nextIndex = 0;
            else if (event.key === "End") nextIndex = TABS.length - 1;
            else return;
            event.preventDefault();
            const next = TABS[nextIndex];
            onChange(next.id);
            window.requestAnimationFrame(() => document.getElementById(`crm-tab-${next.id}`)?.focus());
          }}
        >
          {t.label}
        </button>
      ))}
    </div>
  );
}
