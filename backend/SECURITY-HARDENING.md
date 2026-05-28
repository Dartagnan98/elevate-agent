# Backend Security Hardening — Status

Mapped against the OpenClaw Security Hardening Guide (11 sections / 28 controls).
Scope: the `backend/` API (`api.elevationrealestatehq.com`) — auth, accounts,
licensing. The CLI/agent runtime is tracked separately.

Legend: ✅ done · 🟡 partial · ⬜ todo · ➖ n/a

## Done / in place
- ✅ **#3 Secrets in env, not code** — scanned `src/`, zero hardcoded secrets. All via `process.env`. `.env*` gitignored.
- ✅ **#6 Auth on all endpoints** — every non-public route guarded by `requireAccess` (auth-guard) or `requireAdmin` (admin-guard). Public-by-design: `/auth/*`, `/device/*`, `/invitations/accept`, `/license/refresh` (token-authenticated), `/health`.
- ✅ **#7 RBAC** — `requireAdmin` + role/tier on access tokens; `effectiveAccess` gates entitlements.
- ✅ **#13 Rate limiting** — per-IP + per-email on login, signup, forgot, reset, login-code request/verify (migration 0008, atomic `check_rate_limit`). 429 + Retry-After, runs before lookup (no enumeration).
- ✅ **#12 Security headers** — HSTS, X-Frame-Options DENY, nosniff, Referrer-Policy, Permissions-Policy, X-XSS-Protection 0; `poweredByHeader: false` (next.config.ts).
- ✅ **#23 Dependency audit** — `npm audit fix` applied; **high** Next.js advisory cleared (15.0.3 → 15.5.15). 2 moderate remain (breaking major bumps — see below).
- ✅ Passwords: bcrypt cost 12. Reset tokens / login codes: sha256 at rest. Refresh tokens: sha256 at rest + rotation. JWT: fails hard in prod if secret unset/weak.

## Partial
- 🟡 **#10 CORS** — no wildcard ACAO exists (Next adds none by default, so cross-origin is already blocked). Add an explicit origin allowlist only if/when browser clients on other origins need it — don't add blind (would break the desktop/CLI clients).
- 🟡 **#16 Security logging** — auth failures / rate-limit hits are logged (console.error). Not yet structured JSON with categories + external sink.

## TODO (prioritized)
1. ⬜ **#5 Secrets scanning** — pre-commit hook + CI step (regex for `sk-ant-`, high-entropy strings) so a key can never be committed. Cheap, high value.
2. ⬜ **#11 IP allowlist on `/admin/*`** — env-driven CIDR allowlist in middleware (defense-in-depth on top of `requireAdmin`).
3. ⬜ **#16/#17 Structured security logging + alerts** — JSON logs (auth_failed, rate_limited, admin_action) + alert rules.
4. ⬜ **#20 PII detection + data retention** — redact SSN/CC/email in logs; auto-purge old reset/login-code rows + expired sessions (cron).
5. ⬜ **#9 Remaining dep vulns** — 2 moderate (postcss/qs transitive paths) need major bumps; do deliberately with a full `next build` + smoke test.
6. ⬜ **#24 Encrypted backups** of the Supabase DB (pg_dump + gpg, offsite, daily) + a tested restore.
7. ⬜ **#21/#22 Docker + CI/CD hardening** — non-root container, pinned action SHAs, branch protection.

## Not applicable to the backend (handled in the CLI/agent or platform)
- ➖ **#14 Cost circuit breakers**, **#15 prompt-injection defense / output filtering** — these live in the agent runtime (model calls), not this auth API. The agent already has a cron prompt-injection scanner; output key/PII filtering is worth confirming there.
- ➖ **#9 TLS/HSTS termination** — handled at the edge (nginx/Caddy on Hetzner). HSTS header now also set by the app.

## Re-score
Guide §1.3 baseline: was ~50 (env secrets, auth, HTTPS, input validation, hashed
secrets) → now ~75+ with rate limiting, security headers, hardened JWT, and the
high dep vuln cleared. Remaining gap to 90+ is logging, secrets-scanning, PII
purge, and backups.
