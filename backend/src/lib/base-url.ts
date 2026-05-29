// Public, browser-reachable base URL for links we email to users.
//
// Do NOT derive this from req.url / req.nextUrl: behind nginx the Next server
// sees a plain-HTTP hop (proxy_pass http://127.0.0.1:3001) and ignores
// X-Forwarded-Proto, so `new URL(req.url).origin` comes back as http:// (and in
// some proxy setups, the internal host). Emailed http links are fragile —
// they depend on an HSTS/301 upgrade surviving the user's mail client. A
// configured https origin is deterministic and correct.
export function publicBaseUrl(): string {
  return (process.env.PUBLIC_BASE_URL || "https://api.elevationrealestatehq.com").replace(/\/+$/, "");
}
