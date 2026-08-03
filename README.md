# Hearthstate

Hearthstate helps a household notice what matters, decide who owns it, and get it done.

## Architecture

Hosted production is the canonical application:

- **Vercel** serves the branded dashboard and Python API from [`api/index.py`](api/index.py).
- **Supabase** provides Auth, the hosted PostgreSQL data model, and household-scoped RLS.
- **GitHub `main`** is the production source branch. Vercel deploys it through the connected Git integration, while GitHub Actions applies committed Supabase migrations when `supabase/migrations/` changes.
- **Production URL:** [hearthstate.vercel.app](https://hearthstate.vercel.app)

The repository also contains a compatibility runtime for tests, local development, and Hermes/Photon message handling. It is not the hosted production backend. The complete boundary map is in [`docs/maintainer-handoff.md`](docs/maintainer-handoff.md).

## Hosted request flow

1. The browser loads the branded pages from `hearthstate/dashboard/`.
2. `login.js` authenticates with Supabase Auth using email OTP or the temporary password fallback.
3. `/api/auth/session` validates the Supabase access token and establishes the `HearthstateHostedSession` HttpOnly cookie.
4. `/api/me` resolves the account's household memberships.
5. `/api/dashboard` and the page-specific endpoints call Supabase through `api/index.py`, always with authenticated household context.
6. Supabase RLS protects `profiles`, `households`, `memberships`, tasks, events, meals, groceries, recipes, Inbox items, activity, chores, settings, preferences, and invitations.

An authenticated member visiting `/setup` is redirected to `/`. An unprovisioned account may use `/setup` to create its first household. Hosted provisioning is currently operator-assisted; public onboarding remains roadmap work.

## Product surface

The hosted dashboard includes:

- Overview with connected **What needs attention?**, Today, weekly planning, Inbox, activity, and grocery signals.
- Calendar and dated task projection with assignees and conflict detection.
- Tasks with ownership, recurrence, completion, editing, deletion confirmation, and undo history.
- Meals and recipes with cook assignment, ingredient ownership checks, planning, and grocery sync.
- Groceries with curated Coles matching, quantities, provenance, budgets, manual prices, and fail-closed unknown pricing.
- Owner administration for household name, roles, members, invitations, and revocation.
- Authenticated notification preferences and the local AgentMail briefing boundary.

Assignments are explicit and shared: **Grant, Billie, Skye, or All**.

Supported planner messages include:

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

The planner/application boundary remains callable independently of HTTP:

```python
from hearthstate import Hearthstate, PlannerStore

store = PlannerStore("hearthstate.db")
planner = Hearthstate(store)
print(planner.handle_message("you", "Add oat milk to the grocery list"))
```

## Hermes and local compatibility

Hermes should read [`AGENTS.md`](AGENTS.md) and [`docs/maintainer-handoff.md`](docs/maintainer-handoff.md) before coding. Those documents describe the compatibility runtime, repository map, hosted Auth/session flow, secrets, deployment ownership, and verification gates.

The Photon/iMessage skill is normally at:

```text
~/.hermes/skills/productivity/hearthstate/SKILL.md
```

It routes supported turns through the tested planner boundary using `HERMES_SESSION_USER_ID`:

```bash
python3 -m hearthstate.cli --from-session \
  --database /home/ubuntu/workspace/hearthstate/hearthstate.db \
  "EXACT USER MESSAGE"
```

The local/tailnet dashboard and AgentMail scheduler are compatibility/operations paths. They are documented separately and must not be mistaken for the Vercel/Supabase production runtime.

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
- Optional local redirect: `http://localhost:3000/login`

See [`docs/hosted-deployment.md`](docs/hosted-deployment.md) for the complete one-time setup and migration procedure. Never commit secrets, session tokens, household data, backups, or AgentMail credentials.

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

Hosted `/api/health` should report `service: hearthstate` and `backend: supabase`.

## Roadmap

Completed foundation:

- Household identity, membership roles, invitations, sign-in sessions, owner administration, and hosted API boundary.
- Privacy-aware planner behavior, activity history, reversible mutations, chores, conflicts, recipes, meals, groceries, and notification preferences.
- Local AgentMail briefing delivery with quiet hours, deduplication, bounded retries, and sanitized status output.

Next priorities:

1. Public hosted onboarding and owner-confirmed household export/deletion.
2. Pilot instrumentation and retention measurement.
3. Policy-compliant live retailer refresh behind the curated matcher fallback.
4. External calendar sync, push delivery, provider idempotency, billing, and richer multi-action parsing.

The product strategy and implementation history are preserved in [`.hermes/plans/2026-08-03_141918-hearthstate-commercial-roadmap.md`](.hermes/plans/2026-08-03_141918-hearthstate-commercial-roadmap.md).
