# Elevate

AI chief of staff for real estate agents. Forked from Hermes-Agent (MIT, Nous Research) + subscription-gated skill library.

## Layout

```
elevate/
├── cli/        # forked Hermes-Agent, renamed hermes→elevate
│              #   + elevate_cli/license.py      — subscription gate
│              #   + elevate_cli/cloud_skills.py — fetch skills from backend
├── backend/    # Next.js API — login, license refresh, skill serve, stripe webhook
└── db/         # Supabase SQL migrations
```

## The three extras we added on top of Hermes

1. **License check on startup** — `cli/elevate_cli/license.py`. `~/.elevate/license.json` holds a JWT + refresh token. `cmd_chat` calls `ensure_valid()` before anything else; refreshes when <5min remain; exits with paywall msg if revoked.
2. **Cloud skill fetch** — `cli/elevate_cli/cloud_skills.py`. On chat start, fetches all subscription skills from backend and writes them to a tmp dir that is wiped on exit. Never persists to disk between sessions.
3. **Stripe-driven revocation** — `backend/src/app/api/stripe/webhook/route.ts` handles `customer.subscription.deleted` and marks all of that user's licenses `revoked=true`. The CLI's next refresh call gets 402, wipes the license, prompts re-login.

## Dev setup

### Backend

```bash
cd backend
npm install
cp .env.example .env.local   # supabase + stripe + JWT_SECRET
npm run dev                   # :3000
```

### Supabase

```bash
psql $SUPABASE_DB_URL -f db/001_init.sql
psql $SUPABASE_DB_URL -f db/002_password_hash.sql
```

### CLI

```bash
cd cli
./setup-elevate.sh            # creates venv, installs, symlinks elevate bin
elevate subscribe              # log in with email+password → license.json
elevate license status         # check token state
elevate cloud-skills list      # list skills at your tier
elevate cloud-skills fetch <name>
ELEVATE_BACKEND_URL=http://localhost:3000 elevate  # point CLI at local backend
```

Dev flag to bypass the subscription gate while building: `ELEVATE_DEV_MODE=1 elevate`.

## License

MIT. Upstream attribution to Nous Research in `cli/LICENSE` and `cli/NOTICE`.
