# Hearthstate

Hearthstate helps a household notice what matters, decide who owns it, and get it done.

## Hosted architecture

Hearthstate is a hosted Vercel/Supabase application:

- **Vercel** serves the branded dashboard and Python API from [`api/index.py`](api/index.py).
- **Supabase** provides Auth, PostgreSQL persistence, and household-scoped row-level security.
- **GitHub `main`** is the production source branch. Vercel deploys it through the connected Git integration, while GitHub Actions applies committed Supabase migrations when `supabase/migrations/` changes.
- **Production URL:** [hearthstate.vercel.app](https://hearthstate.vercel.app)

The browser dashboard assets live under [`hearthstate/dashboard/`](hearthstate/dashboard/). The hosted API is the only application runtime in this repository. Retired local SQLite files, if present on a maintainer workstation, are ignored artifacts and are not read, uploaded, or deployed.

Photon/iMessage remains available as a messaging transport through the Hermes `hearthstate-photon-bridge` skill. The bridge maps the configured Photon sender identity to the hosted Hearthstate account and uses server-side, household-scoped commands; it does not restore the retired local runtime.

## Hosted request flow

1. The browser loads the branded pages from `hearthstate/dashboard/`.
2. `login.js` authenticates with Supabase Auth using email OTP or the temporary password fallback.
3. `/api/auth/session` validates the Supabase access token and establishes the `HearthstateHostedSession` HttpOnly cookie.
4. `/api/me` resolves the account's household memberships.
5. `/api/dashboard` and page-specific endpoints call Supabase through `api/index.py`, always with authenticated household context.
6. Supabase RLS protects profiles, households, memberships, tasks, events, meals, groceries, recipes, Inbox items, activity, chores, settings, preferences, and invitations.

An authenticated member visiting `/setup` is redirected to `/`. An unprovisioned account may use `/setup` to create its first household. Hosted provisioning is currently operator-assisted; public onboarding remains roadmap work.

## Product surface

The hosted dashboard includes:

- Overview with **What needs attention?**, Today, weekly planning, Inbox, activity, and grocery signals.
- Calendar and dated task projection with assignees and conflict detection.
- Tasks with ownership, recurrence, completion, editing, deletion confirmation, and undo history.
- Meals and recipes with cook assignment, ingredient ownership checks, planning, and grocery sync.
- Groceries with curated Coles matching, quantities, provenance, budgets, manual prices, and fail-closed unknown pricing.
- Owner administration for household name, roles, members, invitations, and revocation.
- Authenticated notification preferences.

Assignments are explicit and shared: **Grant, Billie, Skye, or All**.

Supported planner actions include:

```text
Add oat milk and bananas to the grocery list
Remind me to submit the school form tomorrow
Add soccer Thursday at 5 for Skye
Add school permission form to the family tasks for Grant
What tasks are assigned to Skye?
What is on the calendar for All?
Add tacos to the meal plan tomorrow for Billie with ingredients tortillas, mince, lettuce
What's for dinner tomorrow?
What needs attention?
```

## Deployment and configuration

Vercel Production and Preview require:

```text
SUPABASE_URL
SUPABASE_PUBLISHABLE_KEY
SUPABASE_SERVICE_ROLE_KEY   # server-only; never expose or commit
```

The GitHub Actions `production` environment requires:

```text
SUPABASE_ACCESS_TOKEN
SUPABASE_DB_PASSWORD
```

Supabase Auth URL Configuration:

- Site URL: `https://hearthstate.vercel.app`
- Redirect URL: `https://hearthstate.vercel.app/login`

See [`docs/hosted-deployment.md`](docs/hosted-deployment.md) for the complete one-time setup and migration procedure. Never commit secrets, session tokens, household data, backups, or AgentMail credentials.

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

## Roadmap

Completed foundation:

- Household identity, membership roles, invitations, sign-in sessions, owner administration, and hosted API boundary.
- Privacy-aware planner behavior, activity history, reversible mutations, chores, conflicts, recipes, meals, groceries, and notification preferences in the hosted schema/API.

Next priorities:

1. Public hosted onboarding and owner-confirmed household export/deletion.
2. Pilot instrumentation and retention measurement.
3. Policy-compliant live retailer refresh behind the curated matcher fallback.
4. External calendar sync, push delivery, provider idempotency, billing, and richer multi-action parsing.

The product strategy and implementation history are preserved in [`.hermes/plans/2026-08-03_141918-hearthstate-commercial-roadmap.md`](.hermes/plans/2026-08-03_141918-hearthstate-commercial-roadmap.md).
