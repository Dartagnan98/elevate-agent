import type { NextConfig } from "next";

// Security response headers applied to every route (guide §4.3, checklist #12).
// Conservative set that won't break the admin UI: HSTS, anti-clickjacking,
// MIME-sniff protection, referrer + permissions policy. A strict
// Content-Security-Policy is intentionally omitted here — it needs per-page
// tuning against the Next.js admin UI before enabling, or it breaks styles/
// scripts. Add it as a report-only header first when ready.
const securityHeaders = [
  {
    // Force HTTPS for a year incl. subdomains. Safe — TLS is already enforced
    // at the edge; this just tells browsers to never try HTTP.
    key: "Strict-Transport-Security",
    value: "max-age=31536000; includeSubDomains; preload",
  },
  { key: "X-Frame-Options", value: "DENY" }, // no embedding → clickjacking off
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  {
    key: "Permissions-Policy",
    value: "camera=(), microphone=(), geolocation=()",
  },
  // Modern browsers ignore the legacy XSS auditor; 0 disables it (recommended).
  { key: "X-XSS-Protection", value: "0" },
];

const config: NextConfig = {
  // Don't leak the framework/version in the Server header.
  poweredByHeader: false,
  async headers() {
    return [
      {
        source: "/:path*",
        headers: securityHeaders,
      },
    ];
  },
};

export default config;
