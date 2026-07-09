// Shared PII/secret scrubber for diagnostic ingest. Applied to any free-text
// field (crash stacks, messages, event strings) before it is stored, so a
// paying customer's email, API key, or home-directory path can never land in
// the diagnostics tables. Belt-and-suspenders: the desktop client also redacts
// before POSTing.
export function redactSensitive(value: string): string {
  return value
    .replace(/[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}/gi, "[redacted-email]")
    .replace(/\b(?:sk|rk|pk)-[A-Za-z0-9_-]{8,}\b/g, "[redacted-secret]")
    .replace(
      /\b(token|password|secret|api[_-]?key)=([^\s&]+)/gi,
      "$1=[redacted-secret]",
    )
    .replace(/\/Users\/[^\s"'`]+/g, (match) => {
      const name = match.split("/").pop() || "path";
      return `[path:${name}]`;
    })
    .replace(/\/home\/[^\s"'`]+/g, (match) => {
      const name = match.split("/").pop() || "path";
      return `[path:${name}]`;
    });
}
