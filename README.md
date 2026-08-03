# Hearthstate

Hearthstate is a household operations assistant: notice what matters, decide who owns it, and get it done. It has two deliberate runtime boundaries:

- **Hosted production:** [hearthstate.vercel.app](https://hearthstate.vercel.app), with Vercel serving the branded dashboard/API and Supabase providing canonical hosted Auth, data, and RLS.
- **Local compatibility:** SQLite-backed planner/dashboard code used by tests, local development, backups, and the Photon/iMessage bridge. Local SQLite is not used by Vercel and is never uploaded to GitHub.

For the maintainer map, read [`docs/maintainer-handoff.md`](docs/maintainer-handoff.md) and [`AGENTS.md`](AGENTS.md) before coding. Hermes/Linux normally works from `/home/ubuntu/workspace/hearthstate`; this checkout is `/Users/grant/Documents/Hearthstate`. Both use the same GitHub repository and `main` is the production branch.

## Current vertical slice

The local planner has a shared SQLite backend plus a tailnet dashboard. The hosted deployment uses the same branded dashboard concepts over the Supabase-backed API:

- Overview: `/`
- Calendar: `/calendar`
- Tasks: `/tasks`
- Meal planner: `/meals`
- Recipes: `/recipes`

Assignments are explicit and shared: **Grant, Billie, Skye, or All**.

```python
from hearthstate import Hearthstate, PlannerStore

store = PlannerStore("hearthstate.db")
planner = Hearthstate(store)
response = planner.handle_message("you", "Add oat milk to the grocery list")
print(response)
```

Supported messages:

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

Run one message from the shell:

```bash
python3 -m hearthstate.cli you Add oat milk to the grocery list
python3 -m hearthstate.cli partner "What needs attention?"
```

Use a different database for development or tests:

```bash
HEARTHSTATE_DB=/tmp/hearthstate.db \
  python3 -m hearthstate.cli you "Add soccer Thursday at 5 for Alex"
```

## Photon/iMessage bridge

The Hermes skill at `~/.hermes/skills/productivity/hearthstate/SKILL.md` routes supported Photon turns through the tested boundary using Hermes' injected `HERMES_SESSION_USER_ID` sender identity:

```bash
python3 -m hearthstate.cli --from-session \
  --database /home/ubuntu/workspace/hearthstate/hearthstate.db \
  "EXACT USER MESSAGE"
```

Private reminders are filtered by sender when `What needs attention?` is requested, and user-facing confirmations never echo the raw phone identifier.

## Household boundary

`HouseholdDirectory` stores commercial account, household, membership, and role metadata in a separate SQLite database. The supported roles are `owner`, `member`, `child`, and `guest`; callers can use `can_access`, `role_for`, and `require_access` before selecting a planner context.

`PlannerStore(database, household_id="...")` keeps the existing default database path for local compatibility. A named household context uses a sibling SQLite database derived from the base path, so two households cannot read or mutate each other's planner records.

P1.2 adds account-backed invitation and sign-in routes when the dashboard is launched with both `--accounts-database` and `--household-id` (or `HEARTHSTATE_ACCOUNTS_DB` and `HEARTHSTATE_HOUSEHOLD_ID`). Owners can create a one-time, seven-day invitation through `POST /api/auth/invitations`; the response contains a copyable `/invite?token=...` link. The invite page accepts a display name, creates or finds the account, adds the membership, and signs the invitee in. Existing members can request a one-time sign-in link through `POST /api/auth/sign-in/request` and consume it through `POST /api/auth/sign-in`. The request endpoint deliberately returns the same response for known and unknown email addresses. The production dashboard uses `--agentmail` with the verified AgentMail inbox stored in `/home/ubuntu/.hermes/secret`; the API key remains outside the repository and the HTTP response never returns it or the sign-in token.

The owner-only `/admin` section manages the household name, member roles, member removal, invitation creation, and pending-invitation revocation. Its data boundary is `/api/admin`; member and invitation listings never return raw invitation credentials. Owners cannot demote or remove the last household owner. Compatibility-mode households do not expose the administration section.

## Hosted boundary

The hosted application is available under `api/index.py` for Vercel and uses the dedicated Supabase project described in [`docs/hosted-deployment.md`](docs/hosted-deployment.md). Supabase is the canonical hosted database: email OTP authentication, a temporary password fallback while email is offline, an HTTP-only session cookie, household membership RLS, and the full branded dashboard run through Vercel. Local SQLite remains only as a compatibility and test path; it is not used by the hosted runtime. The hosted Auth/session flow and route ownership are documented in [`docs/maintainer-handoff.md`](docs/maintainer-handoff.md).

Production releases are GitHub-driven through [`.github/workflows/production.yml`](.github/workflows/production.yml): pushes to `main` trigger the migration workflow when needed, while Vercel deploys `main` through its connected Git integration. The required GitHub/Vercel/Supabase secrets and one-time integration steps are documented in [`docs/hosted-deployment.md`](docs/hosted-deployment.md).

Example account-backed launch:

```bash
python3 -m hearthstate.dashboard \
  --database /path/to/hearthstate.db \
  --accounts-database /path/to/hearthstate-accounts.db \
  --household-id home \
  --host 127.0.0.1 \
  --port 8788
```

In account-backed mode, the legacy passwordless `/api/session` chooser is disabled; users must arrive through an invitation or a sign-in token. The production user service runs this mode for the `home` household with AgentMail delivery; local compatibility mode remains available when the account flags are omitted.

## Dashboard pages and actions

The tailnet dashboard is available at [http://vnic.tail015325.ts.net:8788](http://vnic.tail015325.ts.net:8788).

- `/calendar` lists upcoming events plus all dated tasks, filters by assignee, adds events, and edits existing events or task records.
- `/tasks` lists open tasks, filters by assignee, adds shared tasks, edits task title/date/assignee, marks tasks done, deletes tasks with confirmation, and supports optional daily, weekly, fortnightly, monthly, or yearly recurrence. Dates are optional; recurring tasks require an anchor date.
- `/meals` plans breakfast/lunch/dinner, records the cook and ingredients, lets each planned meal be edited in place (date, meal type, title, cook, and ingredients), deletes meals with browser confirmation, and sends ingredients into Groceries.
- `/recipes` shows the curated recipe catalogue with local illustrative photos, supports save/plan actions, and accepts user-supplied recipes with optional permitted photo URLs. The 22 seeded themes now use **Hearthstate Original** ingredient lists authored locally; external Coles/Taste links remain inspiration/source links and their instructions are not copied. When saving or planning a user/local recipe, the Ingredient check list lets the household mark pantry items as already owned; only unchecked/missing ingredients are added to Groceries. **Plan dinner** opens a dialog for the dinner date and cook, then uses the same ownership check while creating the meal. The catalogue includes a Protein-forward filter covering chicken, salmon, beef, tofu, eggs, lentils, beans, and sausage.
- `/groceries` shows the open list, inline editable quantities, quantity-aware line totals, a weekly budget, priced subtotal, remaining amount, and unknown-price count. Every open item is checked against the curated Coles matcher when it is added, when the API is read, and by the hourly background review; manual prices are preserved and unsafe/unresolved items fail closed.
- The Overview includes a **Household Inbox** for loose threads: capture original text from the dashboard or iMessage, preserve source/creator metadata, then convert an item into a task, event, meal, or grocery item, or archive it without deleting its history.
- The first dashboard visit opens a passwordless household chooser for **Grant**, **Billie**, or **Skye** in compatibility mode. Account-backed mode replaces that chooser with invitation/sign-in sessions and exposes `/invite?token=...` for one-time household invitations. Selection in compatibility mode creates a short-lived, HttpOnly session cookie; the overview greeting, sidebar identity, read model, and dashboard-created records use the selected household member.
- Groceries automatically apply explainable Coles-preferred matches using aliases for common household wording. The current curated set includes milk, eggs, oat milk, bananas, bread, mince, chicken breast, 2L Coke Zero, Frank's hot sauce, hotdogs, hotdog buns, tortillas, white pepper, potatoes, sweet potatoes, carrots, cannellini beans, celery, diced tomatoes, chicken stock, kale, lemon, popping corn kernels, vegetable oil, table spread, beef strips, broccoli, brown onion, garlic, and ginger; Coles products are preferred before considering other products.
- The milk default is **Coles Australian Full Cream Long Life Milk 1L**. Each item exposes a quantity field and Save action; changing quantity recalculates its line total.
- Each Coles price stores the product title, source URL, observed date, and a note about location/weight variability. Unknown items are excluded from the subtotal rather than guessed.
- Unknown items support manual price entry; the page labels those prices separately from Coles observations.
- All pages preserve the light/dark preference in the browser.

- The JSON read/action endpoints are listed in `api/index.py`; the hosted boundary includes `/api/auth/session`, `/api/me`, `/api/households`, and the dashboard/action routes, while `/api/session` remains compatibility-mode only. Hosted `/health` checks Supabase reachability and reports `backend: supabase`; local `/health` checks SQLite integrity. Account-backed API reads and mutations require a live session whose account is a member of the configured household; administration endpoints additionally require the `owner` role. See [`docs/maintainer-handoff.md`](docs/maintainer-handoff.md) for the route and data-boundary map.

## Backups and verification

Create a consistent local backup of the live SQLite database without stopping the dashboard:

```bash
python3 scripts/backup_db.py \
  --database /home/ubuntu/workspace/hearthstate/hearthstate.db \
  --output-dir /home/ubuntu/workspace/hearthstate/backups \
  --keep 14
```

Backups are intentionally ignored by Git. Keep them on storage with appropriate household-data protections; this command does not upload them anywhere. The default rotation retains the newest 14 `hearthstate-*.db` snapshots; use `--keep` to change it.

The recommended user-level schedule is supplied in `deploy/systemd/`:

```bash
systemctl --user enable --now hearthstate-backup.timer
systemctl --user start hearthstate-backup.service
systemctl --user status hearthstate-backup.timer hearthstate-backup.service
```

The timer runs once daily with a persistent catch-up run and the service fails visibly in the user journal if a backup cannot be created. A stale-backup age check/notification is still a separate follow-up; the current timer guarantees rotation and exposes failures rather than silently claiming a successful backup.

The repository CI workflow runs the unittest/HTTP suite on Python 3.11 and 3.12, compiles Python sources, and checks every dashboard JavaScript file with Node.
## Tailnet access

The dashboard is served over the tailnet at:

- [http://vnic.tail015325.ts.net:8788](http://vnic.tail015325.ts.net:8788)
- `http://100.89.153.13:8788`

It is bound only to the Tailscale interface and managed by `hearthstate-dashboard.service` as a user service. Tailscale Serve could not be used without sudo, so this direct interface bind is the non-root setup. Tailnet membership/ACLs remain the network boundary; the dashboard now also requires a passwordless household selection session.
### Manual/local launch

```bash
python3 -m hearthstate.dashboard \
  --database /home/ubuntu/workspace/hearthstate/hearthstate.db \
  --host 127.0.0.1 \
  --port 8788
```

Open [http://127.0.0.1:8788](http://127.0.0.1:8788). The dashboard is intentionally organized around the family's current state:

- A connected **What needs attention?** centre combines open tasks, unplanned dinners, unpriced/over-budget groceries, and meal assignments. Task rows can be completed inline; every item links to the page where it can be resolved.
- A **Today** view combines calendar events, dated task occurrences, and planned meals for the next 24 hours.
- A seven-day **Plan the week** strip shows dinners, calendar events, and recurring tasks together. Empty dinner slots link directly to the meal planner; meal cards link back to the relevant day.
- Private-by-default reminder note. Live dashboard reads use the selected session user; the API still accepts a `viewer` selector only for local read-model tests when no dashboard session is present.

- The dashboard supports safe shared mutations: adding/editing/completing/deleting tasks, assigning tasks, setting task recurrence, adding/editing calendar events, planning meals, syncing meal ingredients to Groceries, setting a weekly grocery budget, and recording grocery prices. Destructive task deletion requires browser confirmation.
- The authenticated API read model is available at `/api/dashboard` and includes `viewer`, `viewer_name`, `viewer_role`, `attention_items`, `today_items`, `planning_week`, `inbox`, `grocery_summary`, and the existing page-specific fields.
- Theme toggle: click the sun/moon button in the top-right. The preference persists in that browser via `localStorage`.
- The welcome greeting follows the browser's local time: morning (05:00–11:59), afternoon (12:00–16:59), evening (17:00–20:59), and quiet late-night copy (21:00–04:59).
- Grocery messages handled through the iMessage/Photon planner boundary write to the same SQLite store the dashboard reads, so shared items appear for both household views.

## Privacy behavior so far

- Grocery items are shared household records.
- Inbox captures are shared by default; private Inbox captures are visible only to their creator through the tested viewer filter.
- `Remind me ...` creates a private task owned by the sender.
- `family tasks` creates an unassigned shared task.
- Every stored record keeps its creator.


- The dashboard now includes an append-only activity feed with actor, timestamp, before/after snapshots, and reversible task, event, meal, and grocery mutations. `Undo that` restores the sender's most recent reversible change; archived records remain available for history instead of being physically deleted.
- The planner accepts conversational `Mark <task> done`, `Assign <task> to <person>`, grocery removal, `Undo that`, and `What conflicts are there?` queries. Calendar conflicts use explicit event end times when supplied and a one-hour default otherwise; task deadlines falling inside an event are also reported.
- Chores can be created with a cadence and at least two household participants, then advanced through round-robin assignment into recurring tasks. The morning briefing engine and delivery runner are available through `python3 -m hearthstate.briefing_delivery`; they respect per-member enabled state, preferred time, quiet hours, unique daily delivery records, bounded retries, and AgentMail delivery. Delivery contents are privacy-filtered and are not written to journald.

## Remaining roadmap

1. **Household identity and permissions** — **P1.1/P1.2 complete; hosted P1.3 boundary live:** `HouseholdDirectory` models accounts, households, memberships, and roles; named `PlannerStore` contexts isolate planner data per household; owner invitations, one-time invitation acceptance, one-time sign-in tokens, AgentMail delivery, and account-backed dashboard sessions are implemented. Hosted provisioning is currently operator-assisted; public onboarding remains.
2. **Notification preferences and briefing delivery** — **P2.4 complete for the local deployment:** authenticated Notifications settings, per-member delivery preferences, atomic claims, bounded retries, and AgentMail email delivery are implemented. Photon/iMessage, push, and provider idempotency remain.
3. **Data portability** — add owner-confirmed household export and deletion with documented retention behavior.
4. **Real retailer refresh** — keep the current curated matcher as the safe fallback, then add a policy-compliant Coles search/refresh adapter with rate limits, provenance, stale-price labels, and fail-closed matching.
5. **Scheduled backups** — **mostly complete:** the tested backup helper runs from a user-level timer with retention; a stale-age alert remains.
6. **Conversation depth** — **expanded:** natural-language completion, assignment, grocery removal, undo, conflict queries, chores, and briefings are now supported; richer multi-action parsing remains separate.

The remaining roadmap items are intentionally separate from the tailnet boundary: tailnet membership controls local network reachability, while the hosted Supabase session identifies the household member inside the app. See [`docs/maintainer-handoff.md`](docs/maintainer-handoff.md) for the current implementation map and resume checklist.
