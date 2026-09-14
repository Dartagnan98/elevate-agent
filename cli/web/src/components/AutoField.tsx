import { useEffect, useMemo, useState } from "react";
import { Input } from "@/components/ui/input";
import { Select, SelectOption } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";

function FieldLabel({
  label,
  schema,
}: {
  label: string;
  schema: Record<string, unknown>;
}) {
  const description = schema.description ? String(schema.description) : "";
  return (
    <div className="min-w-0 flex-1 pr-6">
      <div className="text-[0.92rem] font-medium text-foreground leading-tight">
        {label}
      </div>
      {description && (
        <div className="mt-1 text-[0.8rem] leading-snug text-foreground/80">
          {description}
        </div>
      )}
    </div>
  );
}

export function AutoField({
  schemaKey,
  schema,
  value,
  onChange,
}: AutoFieldProps) {
  const rawLabel = schemaKey.split(".").pop() ?? schemaKey;
  const label = rawLabel.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
  const jsonValue = useMemo(() => {
    if (schema.type !== "json") return "";
    return JSON.stringify(value ?? null, null, 2);
  }, [schema.type, value]);
  const [jsonText, setJsonText] = useState(jsonValue);
  const [jsonError, setJsonError] = useState("");

  useEffect(() => {
    setJsonText(jsonValue);
    setJsonError("");
  }, [jsonValue]);

  if (schema.type === "boolean") {
    return (
      <div className="flex items-start justify-between gap-4">
        <FieldLabel label={label} schema={schema} />
        <div className="shrink-0 pt-0.5">
          <Switch checked={!!value} onCheckedChange={onChange} aria-label={label} />
        </div>
      </div>
    );
  }

  if (schema.type === "select") {
    const options = (schema.options as string[]) ?? [];
    return (
      <div className="flex items-start justify-between gap-4">
        <FieldLabel label={label} schema={schema} />
        <div className="w-72 shrink-0">
          <Select value={String(value ?? "")} onValueChange={(v) => onChange(v)}>
            {options.map((opt) => (
              <SelectOption key={opt} value={opt}>
                {opt || "(none)"}
              </SelectOption>
            ))}
          </Select>
        </div>
      </div>
    );
  }

  if (schema.type === "number") {
    return (
      <div className="flex items-start justify-between gap-4">
        <FieldLabel label={label} schema={schema} />
        <div className="w-40 shrink-0">
          <Input
            type="number"
            value={value === undefined || value === null ? "" : String(value)}
            onChange={(e) => {
              const raw = e.target.value;
              if (raw === "") {
                onChange(0);
                return;
              }
              const n = Number(raw);
              if (!Number.isNaN(n)) {
                onChange(n);
              }
            }}
          />
        </div>
      </div>
    );
  }

  if (schema.type === "text") {
    return (
      <div className="flex flex-col gap-2">
        <FieldLabel label={label} schema={schema} />
        <textarea
          className="flex min-h-[80px] w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm shadow-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
          value={String(value ?? "")}
          onChange={(e) => onChange(e.target.value)}
        />
      </div>
    );
  }

  if (schema.type === "list") {
    return (
      <div className="flex items-start justify-between gap-4">
        <FieldLabel label={label} schema={schema} />
        <div className="w-80 shrink-0">
          <Input
            value={Array.isArray(value) ? value.join(", ") : String(value ?? "")}
            onChange={(e) =>
              onChange(
                e.target.value
                  .split(",")
                  .map((s) => s.trim())
                  .filter(Boolean),
              )
            }
            placeholder="comma-separated values"
          />
        </div>
      </div>
    );
  }

  if (schema.type === "json") {
    return (
      <div className="flex flex-col gap-2">
        <FieldLabel label={label} schema={schema} />
        <textarea
          className="flex min-h-[200px] w-full rounded-md border border-input bg-transparent px-3 py-2 font-mono text-xs leading-relaxed shadow-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
          value={jsonText}
          onChange={(e) => {
            const next = e.target.value;
            setJsonText(next);
            try {
              onChange(JSON.parse(next));
              setJsonError("");
            } catch (err) {
              setJsonError(err instanceof Error ? err.message : "Invalid JSON");
            }
          }}
          spellCheck={false}
        />
        {jsonError && <div className="text-xs text-destructive">{jsonError}</div>}
      </div>
    );
  }

  if (typeof value === "object" && value !== null && !Array.isArray(value)) {
    const obj = value as Record<string, unknown>;
    return (
      <div className="flex items-start justify-between gap-4">
        <FieldLabel label={label} schema={schema} />
        <div className="w-80 shrink-0 space-y-2">
          {Object.entries(obj).map(([subKey, subVal]) => (
            <div key={subKey} className="flex items-center gap-2">
              <span className="w-24 shrink-0 text-xs text-muted-foreground">{subKey}</span>
              <Input
                value={String(subVal ?? "")}
                onChange={(e) => onChange({ ...obj, [subKey]: e.target.value })}
                aria-label={`${label} – ${subKey}`}
              />
            </div>
          ))}
        </div>
      </div>
    );
  }

  // Default: string input
  return (
    <div className="flex items-start justify-between gap-4">
      <FieldLabel label={label} schema={schema} />
      <div className="w-80 shrink-0">
        <Input value={String(value ?? "")} onChange={(e) => onChange(e.target.value)} />
      </div>
    </div>
  );
}

interface AutoFieldProps {
  schemaKey: string;
  schema: Record<string, unknown>;
  value: unknown;
  onChange: (v: unknown) => void;
}
