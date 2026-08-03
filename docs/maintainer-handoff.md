# Maintainer handoff

This is the operational map for Hermes or any future coding agent returning to Hearthstate.

## Current state

- Repository: `https://github.com/grantashman/hearthstate.git`
- Production app: `https://hearthstate.vercel.app`
- Production runtime: Vercel Python function at `api/index.py`
- Canonical hosted database and Auth provider: Supabase project ref `zcfzdqtjglelrbyhcvcu` in `ap-southeast-2`
- Hosted data is Supabase-backed. Local SQLite is retained for compatibility, Photon/iMessage development, backups, and tests; it is not read by Vercel and must never be uploaded to GitHub.
- Hermes/Linux workspace: `/home/ubuntu/workspace/hearthstate`
- This Mac workspace: `/Users/grant/Documents/Hearthstate`
- Remote production branch: `main`

Read `AGENTS.md` before changing anything. It contains the repository safety rules and verification gates.

## Repository map

| Location | Responsibility |
| --- | --- |
| `hearthstate/app.py` | Natural-language planner boundary used by CLI, tests, and Photon/iMessage. |
| `hearthstate/store.py` | Local SQLite planner store, privacy filtering, activity history, undo, groceries, meals, recipes, chores, and briefing delivery state. |
| `hearthstate/accounts.py` | Local compatibility account/household/membership directory and invitation/sign-in token lifecycle. |
| `hearthstate/dashboard.py` | Local/tailnet HTTP dashboard backed by SQLite. |
| `hearthstate/dashboard/` | HTML, CSS, and JavaScript for both local pages and the hosted branded UI. |
| `api/index.py` | Hosted Vercel handler: Auth/session boundary, Supabase REST calls, RLS-scoped reads/mutations, asset routing, and owner administration. |
| `supabase/migrations/` | Hosted schema, RLS policies/functions, grants, invitations, notification preferences, recipes, and other feature tables. |
| `vercel.json` | Rewrites browser routes and `/api/*` requests to `api/index.py`. |
| `.github/workflows/production.yml` | On `main`, applies committed Supabase migrations only when that directory changed; Vercel deploys through its native Git integration. |
| `scripts/backup_db.py` | Local SQLite backup/retention helper. It does not back up Supabase. |
| `deploy/systemd/` | Local/tailnet dashboard, backup, and briefing user-service/timer definitions. |
| `docs/hosted-deployment.md` | Hosted environment, Auth URL, migration, and GitHub/Vercel setup. |
| `docs/briefing-scheduler.md` | Local AgentMail briefing scheduler behavior and operations. |
| `.hermes/plans/` | Product strategy and roadmap; update status when roadmap work lands. |

## Runtime boundaries

### Hosted production

The browser loads the full branded UI from `hearthstate/dashboard/`. `login.js` talks directly to Supabase Auth for OTP/password authentication, then posts the returned access token to `/api/auth/session`. The hosted handler validates the token with Supabase Auth, confirms household membership, and sets the `HearthstateHostedSession` HttpOnly cookie. Subsequent API requests use that session and an optional `X-Hearthstate-Household` selector.

Hosted records live in Supabase public tables protected by RLS. The important tables are `profiles`, `households`, `memberships`, `tasks`, `events`, `meals`, `grocery_items`, `recipes`, `saved_recipes`, `inbox_items`, `activity_log`, `chore_templates`, `planner_settings`, `notification_preferences`, and `invitations`.

The hosted Auth flow is:

1. `/login` serves `hosted-login.html` and `login.js`.
2. OTP requests send `redirect_to` for the current origin's `/login` route.
3. Supabase may return an access token in the URL fragment; `login.js` consumes it and removes the need for a local callback server.
4. `/api/auth/session` establishes the HttpOnly app session.
5. `/api/me` resolves the account's household memberships.
6. Members go to `/`; an authenticated member visiting `/setup` is redirected to `/`. A genuinely unprovisioned account may still use `/setup` to create its first household.
7. `/api/dashboard` and the page-specific endpoints read/mutate only the active household.

The temporary password panel is an intentional fallback while email delivery/rate limits are unreliable. It calls Supabase's normal password token endpoint; it is not a second application auth system. Do not hard-code passwords or service keys.

### Local compatibility and Photon

The local runtime remains useful for development and the iMessage/Photon bridge:

```bash
python3 -m hearthstate.dashboard \
  --database /path/to/hearthstate.db \
  --host 127.0.0.1 \
  --port 8788
```

The Hermes skill at `~/.hermes/skills/productivity/hearthstate/SKILL.md` routes supported Photon turns through:

```bash
python3 -m hearthstate.cli --from-session \
  --database /home/ubuntu/workspace/hearthstate/hearthstate.db \
  "EXACT USER MESSAGE"
```

`HERMES_SESSION_USER_ID` supplies the sender identity. Keep the planner/application boundary independent from HTTP transport so this path continues to work.

## Hosted configuration

Vercel Production and Preview need:

```text
SUPABASE_URL
SUPABASE_PUBLISHABLE_KEY
SUPABASE_SERVICE_ROLE_KEY   # server-only; never expose or commit
```

GitHub Actions' `production` environment needs:

```text
SUPABASE_ACCESS_TOKEN
SUPABASE_DB_PASSWORD
```

Supabase Auth URL Configuration must include:

- Site URL: `https://hearthstate.vercel.app`
- Redirect URL: `https://hearthstate.vercel.app/login`
- Optional local redirect: `http://localhost:3000/login`

Do not put any secret, session token, household database, backup, or AgentMail credential in tracked files. The local AgentMail secrets belong outside the repository under the deployment account's secret directory.

## Deployment workflow

The intended production path is:

1. Create a focused `codex/*` or feature branch.
2. Make the smallest safe change and update tests/docs together.
3. Run the verification gates below.
4. Commit with a Conventional Commit message.
5. Push the branch. If production shipping is explicitly requested, fast-forward/merge to `main` and push it.
6. Check both GitHub Actions and the Vercel deployment. Vercel deploys `main` via its connected Git integration; the workflow does not invoke the Vercel CLI.

Supabase migrations are the only database schema deployment mechanism. Add schema changes under `supabase/migrations/`; the production workflow detects and applies them. Do not make an ad hoc production schema change and leave the repository behind.

## Verification

From the repository root:

```bash
PYTHONPYCACHEPREFIX=/tmp/hearthstate-pyc python3 -m unittest discover -s tests -v
PYTHONPYCACHEPREFIX=/tmp/hearthstate-pyc python3 -m compileall -q api hearthstate scripts tests
for file in hearthstate/dashboard/*.js; do node --check "$file"; done
git diff --check
```

Hosted smoke checks:

```bash
curl --fail --silent --show-error https://hearthstate.vercel.app/api/health
curl --fail --silent --show-error https://hearthstate.vercel.app/api/auth/config
```

Hosted `/api/health` should report `service: hearthstate` and `backend: supabase`. The local dashboard `/health` reports SQLite health instead; do not confuse the two.

## Known boundaries and next work

- Hosted provisioning is currently an operator step; public onboarding and owner-confirmed export/deletion remain roadmap work.
- Local briefing delivery through AgentMail is documented in `docs/briefing-scheduler.md`; it is not a Vercel cron/runtime service.
- The curated Coles matcher is the safe fallback. A rate-limited, policy-compliant live retailer adapter remains future work.
- Stale-backup alerting, external calendar sync, push delivery, provider idempotency, analytics/pilot instrumentation, billing, and richer multi-action parsing remain future work.
- Keep local SQLite and hosted Supabase behavior covered separately. Never assume a hosted change is exercised by local SQLite tests alone.
