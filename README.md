# Hearthstate

Hearthstate is a local, SQLite-backed household operations assistant designed to receive natural-language messages from iMessage and return concise, safe responses. Its dashboard is a shared operating picture of what needs attention at home.

## Current vertical slice

The planner now has a shared SQLite backend plus a tailnet dashboard:

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

`PlannerStore(database, household_id="...")` keeps the existing default database path for local compatibility. A named household context uses a sibling SQLite database derived from the base path, so two households cannot read or mutate each other's planner records. This is the first tenancy boundary; a later hosted API can resolve the authenticated account through `HouseholdDirectory` and open the corresponding planner context.

## Dashboard pages and actions

The tailnet dashboard is available at [http://vnic.tail015325.ts.net:8788](http://vnic.tail015325.ts.net:8788).

- `/calendar` lists upcoming events plus all dated tasks, filters by assignee, adds events, and edits existing events or task records.
- `/tasks` lists open tasks, filters by assignee, adds shared tasks, edits task title/date/assignee, marks tasks done, deletes tasks with confirmation, and supports optional daily, weekly, fortnightly, monthly, or yearly recurrence. Dates are optional; recurring tasks require an anchor date.
- `/meals` plans breakfast/lunch/dinner, records the cook and ingredients, lets each planned meal be edited in place (date, meal type, title, cook, and ingredients), deletes meals with browser confirmation, and sends ingredients into Groceries.
- `/recipes` shows the curated recipe catalogue with local illustrative photos, supports save/plan actions, and accepts user-supplied recipes with optional permitted photo URLs. The 22 seeded themes now use **Hearthstate Original** ingredient lists authored locally; external Coles/Taste links remain inspiration/source links and their instructions are not copied. When saving or planning a user/local recipe, the Ingredient check list lets the household mark pantry items as already owned; only unchecked/missing ingredients are added to Groceries. **Plan dinner** opens a dialog for the dinner date and cook, then uses the same ownership check while creating the meal. The catalogue includes a Protein-forward filter covering chicken, salmon, beef, tofu, eggs, lentils, beans, and sausage.
- `/groceries` shows the open list, inline editable quantities, quantity-aware line totals, a weekly budget, priced subtotal, remaining amount, and unknown-price count. Every open item is checked against the curated Coles matcher when it is added, when the API is read, and by the hourly background review; manual prices are preserved and unsafe/unresolved items fail closed.
- The Overview includes a **Household Inbox** for loose threads: capture original text from the dashboard or iMessage, preserve source/creator metadata, then convert an item into a task, event, meal, or grocery item, or archive it without deleting its history.
- The first dashboard visit opens a passwordless household chooser for **Grant**, **Billie**, or **Skye**. Selection creates a short-lived, HttpOnly session cookie; the overview greeting, sidebar identity, read model, and dashboard-created records use the selected household member.
- Groceries automatically apply explainable Coles-preferred matches using aliases for common household wording. The current curated set includes milk, eggs, oat milk, bananas, bread, mince, chicken breast, 2L Coke Zero, Frank's hot sauce, tortillas, white pepper, potatoes, sweet potatoes, carrots, cannellini beans, celery, diced tomatoes, chicken stock, kale, lemon, popping corn kernels, vegetable oil, table spread, beef strips, broccoli, brown onion, garlic, and ginger; Coles products are preferred before considering other products.
- The milk default is **Coles Australian Full Cream Long Life Milk 1L**. Each item exposes a quantity field and Save action; changing quantity recalculates its line total.
- Each Coles price stores the product title, source URL, observed date, and a note about location/weight variability. Unknown items are excluded from the subtotal rather than guessed.
- Unknown items support manual price entry; the page labels those prices separately from Coles observations.
- All pages preserve the light/dark preference in the browser.

- The JSON read/action endpoints are `/health`, `/api/session`, `/api/dashboard`, `/api/inbox`, `/api/inbox/{id}/archive`, `/api/inbox/{id}/convert`, `/api/activity`, `/api/activity/undo`, `/api/conflicts`, `/api/chores`, `/api/calendar`, `/api/tasks`, `/api/meals`, `/api/meals/sync-groceries`, `/api/groceries`, `/api/groceries/budget`, `/api/groceries/price`, and `/api/groceries/refresh-coles`. `/health` performs a SQLite quick integrity check for service monitoring. Dashboard actions support capturing and triaging Inbox items, auditing/reversing household mutations, adding and editing tasks, setting task recurrence, adding/editing calendar entries, planning meals, syncing meal ingredients, setting a grocery budget, recording grocery prices, creating chores, and advancing round-robin chore assignments.

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
- Chores can be created with a cadence and at least two household participants, then advanced through round-robin assignment into recurring tasks. The morning briefing engine is available through `python3 -m hearthstate.briefings`; it respects 07:00–21:00 quiet hours and deduplicates one briefing per viewer per day. Delivery wiring remains deliberately separate from message composition.

## Remaining roadmap

1. **Household identity and permissions** — **foundation complete:** `HouseholdDirectory` now models accounts, households, memberships, and roles; named `PlannerStore` contexts isolate planner data per household. Hosted authentication, invitations, and explicit API permission checks remain.
2. **Audit history** — **complete:** append-only activity records, before/after snapshots, archive semantics, undo, and activity API.
3. **Real retailer refresh** — keep the current curated matcher as the safe fallback, then add a policy-compliant Coles search/refresh adapter with rate limits, provenance, stale-price labels, and fail-closed matching.
4. **Scheduled backups** — **mostly complete:** the tested backup helper runs from a user-level timer with retention; a stale-age alert remains.
5. **Conversation depth** — **expanded:** natural-language completion, assignment, grocery removal, undo, conflict queries, chores, and briefings are now supported; richer multi-action parsing remains separate.

The remaining roadmap items are intentionally separate from the tailnet boundary: tailnet membership controls network reachability, while the passwordless session identifies the household member inside the app.
