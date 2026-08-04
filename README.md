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
6. Supabase RLS protects profiles, households, memberships, tasks, events, meals, groceries, recipes, Inbox items, activity, chores, settings, preferences, invitations, and the service-role-only pilot measurement ledger.

An authenticated member visiting `/setup` is redirected to `/`. An unprovisioned account may use `/setup` to create its first household; hosted onboarding is available through the dashboard flow.

## Product surface

The hosted dashboard includes:

- Overview with **What needs attention?**, Today, weekly planning, a universal Inbox, activity, and grocery signals. Inbox captures now create privacy-scoped, editable suggestions; accepting a suggestion is the only path from the review UI to a task, event, meal, grocery item, or resolved note.
- Calendar and dated task projection with assignees and conflict detection.
- Tasks with ownership, recurrence, completion, editing, deletion confirmation, and activity history.
- Meals and recipes with cook assignment, ingredient ownership checks, planning, grocery sync, and auditable household-scoped meal edits.
- Groceries with curated supermarket matching for Coles, ALDI Australia, and Woolworths, quantities, per-retailer cart comparison, equivalent-product safeguards, provenance, budgets, manual prices, and fail-closed unknown pricing.

Grocery matching uses controlled product aliases rather than unconstrained fuzzy matching. For example, `Coke Zero` resolves to the curated Woolworths Coca-Cola Zero Sugar 2L observation, while ALDI requires an explicit size when its 600mL and 30x375mL Zero Sugar packs would otherwise be ambiguous. Grocery price metadata is server-controlled: ordinary grocery writes cannot set prices or provenance, the manual-price route supplies fixed manual metadata, and the dashboard links only to HTTPS Coles, ALDI, or Woolworths domains. The database migration also removes authenticated PostgREST write privileges for protected price columns and quote mutations; only service-role-only RPCs can persist curated/manual price metadata and refresh observations, and each RPC re-checks and locks the actor's household membership before mutating. A recipe/import line such as `600 | ml | Coke Zero` is canonicalized to one packaged purchase (`Coke Zero 600ml`, quantity `1`, unit `each`) only when a known catalog product supports it. Explicit same-family size differences may be shown as a **closest pack**, but they are never treated as equivalent for a cheapest-retailer recommendation.
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
- Privacy-aware planner behavior, activity history, auditable mutations, chores, conflicts, recipes, meals, groceries, and notification preferences in the hosted schema/API.

Next priorities:

1. Run the pilot using the [privacy-safe instrumentation and retention contract](docs/pilot-instrumentation.md) to measure activation, repeated capture, suggestion review, conversion, task completion, and weekly active households.
2. Dogfood the self-serve hosted onboarding path and universal Inbox with multiple household members.
3. Policy-compliant live retailer refresh behind the curated matcher fallback.
4. Mobile-first PWA work, external calendar sync, push delivery, provider idempotency, billing, and richer multi-action parsing.

The product strategy and implementation history are preserved in [`.hermes/plans/2026-08-03_141918-hearthstate-commercial-roadmap.md`](.hermes/plans/2026-08-03_141918-hearthstate-commercial-roadmap.md).
