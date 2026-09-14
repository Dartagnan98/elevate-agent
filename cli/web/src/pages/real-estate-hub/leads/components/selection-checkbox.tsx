import { useEffect, useRef } from "react";

export function SelectionCheckbox({ checked, mixed = false, label, disabled = false, onChange }: {
  checked: boolean; mixed?: boolean; label: string; disabled?: boolean; onChange: () => void;
}) {
  const ref = useRef<HTMLInputElement>(null);
  useEffect(() => { if (ref.current) ref.current.indeterminate = mixed; }, [mixed]);
  return <label className="leadsx-select-hit" onClick={(e) => e.stopPropagation()} onKeyDown={(e) => e.stopPropagation()}>
    <input ref={ref} type="checkbox" className="leadsx-select-input" checked={checked}
      aria-checked={mixed ? "mixed" : checked} aria-label={label} disabled={disabled} onChange={onChange} />
    <span className="leadsx-select-mark" aria-hidden="true">{mixed ? "−" : checked ? "✓" : ""}</span>
  </label>;
}
