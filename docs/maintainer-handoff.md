# Maintainer handoff

This is the operational map for Hermes or any future coding agent returning to Hearthstate.

## Current state

- Repository: `https://github.com/grantashman/hearthstate.git`
- Production app: `https://hearthstate.vercel.app`
- Production runtime: Vercel Python function at `api/index.py`
- Canonical hosted database and Auth provider: Supabase project ref `zcfzdqtjglelrbyhcvcu` in `ap-southeast-2`
- Hosted data is Supabase-backed and protected by household-scoped RLS.
- Remote production branch: `main`

The repository is hosted-only. Retired SQLite/account databases may remain as ignored workstation artifacts for preservation, but no checked-in runtime, service, backup job, or test reads them.

## Repository map

| Location | Responsibility |
| --- | --- |
| `api/index.py` | Hosted Vercel handler: Auth/session boundary, Supabase REST calls, RLS-scoped reads/mutations, asset routing, and owner administration. |
| `hearthstate/dashboard/` | Branded HTML, CSS, JavaScript, and static images served by the hosted handler. |
| `supabase/migrations/` | Hosted schema, RLS policies/functions, grants, invitations, notification preferences, recipes, and feature tables. |
| `vercel.json` | Rewrites browser routes and `/api/*` requests to `api/index.py`. |
| `.github/workflows/ci.yml` | Hosted API contract tests, Python compilation, and browser JavaScript syntax checks. |
| `.github/workflows/production.yml` | On `main`, applies committed Supabase migrations when that directory changes; Vercel deploys through its native Git integration. |
| `docs/hosted-deployment.md` | Hosted environment, Auth URL, migration, and GitHub/Vercel setup. |

## Hosted Auth and request flow

1. `/login` serves `hosted-login.html` and `login.js`.
2. OTP requests use the current origin's `/login` redirect URL.
3. Supabase returns an access token to the login callback; `login.js` consumes it and removes the fragment from the browser flow.
4. `/api/auth/session` validates the token and establishes the `HearthstateHostedSession` HttpOnly cookie.
5. `/api/me` resolves the account's household memberships.
6. Members go to `/`; an authenticated member visiting `/setup` is redirected to `/`. A genuinely unprovisioned account may still use `/setup` to create its first household.
7. `/api/dashboard` and page-specific endpoints read or mutate only the active household.

The temporary password panel is an intentional fallback while email delivery or rate limits are unreliable. It calls Supabase's normal password token endpoint; it is not a second application auth system. Do not hard-code passwords or service keys.

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

Do not put any secret, session token, household database, backup, or AgentMail credential in tracked files.

## Deployment workflow

1. Create a focused feature or fix branch.
2. Make the smallest safe change and update hosted tests/docs together.
3. Run the verification gates below.
4. Commit with a Conventional Commit message.
5. Push the branch. If production shipping is explicitly requested, fast-forward/merge to `main` and push it.
6. Check both GitHub Actions and the Vercel deployment.

Vercel deploys `main` through its connected Git integration. Supabase migrations are the only database schema deployment mechanism; add schema changes under `supabase/migrations/` and do not make an ad hoc production schema change that leaves the repository behind.

## Verification

From the repository root:

```bash
PYTHONPYCACHEPREFIX=/tmp/hearthstate-pyc python3 -m unittest discover -s tests -v
PYTHONPYCACHEPREFIX=/tmp/hearthstate-pyc python3 -m compileall -q api tests
for file in hearthstate/dashboard/*.js; do node --check "$file"; done
git diff --check
```

Hosted smoke checks:

```bash
curl --fail --silent --show-error https://hearthstate.vercel.app/api/health
curl --fail --silent --show-error https://hearthstate.vercel.app/api/auth/config
```

Hosted `/api/health` should report `service: hearthstate` and `backend: supabase`.

## Known boundaries and next work

- Hosted provisioning is currently an operator step; public onboarding and owner-confirmed export/deletion remain roadmap work.
- A rate-limited, policy-compliant live retailer adapter remains future work behind the curated matcher.
- External calendar sync, push delivery, provider idempotency, analytics/pilot instrumentation, billing, and richer multi-action parsing remain future work.
- Keep household isolation and hosted Supabase behavior covered by API contract tests and production read-only checks.
