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
from family_planner import FamilyPlanner, PlannerStore

store = PlannerStore("family_planner.db")
planner = FamilyPlanner(store)
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
python3 -m family_planner.cli you Add oat milk to the grocery list
python3 -m family_planner.cli partner "What needs attention?"
```

Use a different database for development or tests:

```bash
FAMILY_PLANNER_DB=/tmp/family-planner.db \
  python3 -m family_planner.cli you "Add soccer Thursday at 5 for Alex"
```

## Photon/iMessage bridge

The Hermes skill at `~/.hermes/skills/productivity/family-planner/SKILL.md` routes supported Photon turns through the tested boundary using Hermes' injected `HERMES_SESSION_USER_ID` sender identity:

```bash
python3 -m family_planner.cli --from-session \
  --database /home/ubuntu/workspace/family-planner/family_planner.db \
  "EXACT USER MESSAGE"
```

Private reminders are filtered by sender when `What needs attention?` is requested, and user-facing confirmations never echo the raw phone identifier.

## Dashboard pages and actions

The tailnet dashboard is available at [http://vnic.tail015325.ts.net:8788](http://vnic.tail015325.ts.net:8788).

- `/calendar` lists upcoming events plus all dated tasks, filters by assignee, adds events, and edits existing events or task records.
- `/tasks` lists open tasks, filters by assignee, adds shared tasks, edits task title/date/assignee, marks tasks done, deletes tasks with confirmation, and supports optional daily, weekly, fortnightly, monthly, or yearly recurrence. Dates are optional; recurring tasks require an anchor date.
- `/meals` plans breakfast/lunch/dinner, records the cook and ingredients, lets each planned meal be edited in place (date, meal type, title, cook, and ingredients), deletes meals with browser confirmation, and sends ingredients into Groceries.
- `/recipes` shows the curated recipe catalogue with local illustrative photos, supports save/plan actions, and accepts user-supplied recipes with optional permitted photo URLs. The 22 seeded themes now use **Hearthstate Original** ingredient lists authored locally; external Coles/Taste links remain inspiration/source links and their instructions are not copied. When saving or planning a user/local recipe, the Ingredient check list lets the household mark pantry items as already owned; only unchecked/missing ingredients are added to Groceries. **Plan dinner** opens a dialog for the dinner date and cook, then uses the same ownership check while creating the meal. The catalogue includes a Protein-forward filter covering chicken, salmon, beef, tofu, eggs, lentils, beans, and sausage.
- `/groceries` shows the open list, inline editable quantities, quantity-aware line totals, a weekly budget, priced subtotal, remaining amount, and unknown-price count. Every open item is checked against the curated Coles matcher when it is added, when the API is read, and by the hourly background review; manual prices are preserved and unsafe/unresolved items fail closed.
- Groceries automatically apply explainable Coles-preferred matches using aliases for common household wording. The current curated set includes milk, eggs, oat milk, bananas, bread, mince, chicken breast, tortillas, white pepper, potatoes, sweet potatoes, carrots, cannellini beans, celery, diced tomatoes, chicken stock, kale, lemon, popping corn kernels, vegetable oil, table spread, beef strips, broccoli, brown onion, garlic, and ginger; Coles products are preferred before considering other products.
- The milk default is **Coles Australian Full Cream Long Life Milk 1L**. Each item exposes a quantity field and Save action; changing quantity recalculates its line total.
- Each Coles price stores the product title, source URL, observed date, and a note about location/weight variability. Unknown items are excluded from the subtotal rather than guessed.
- Unknown items support manual price entry; the page labels those prices separately from Coles observations.
- All pages preserve the light/dark preference in the browser.

- The JSON read/action endpoints are `/api/calendar`, `/api/tasks`, `/api/meals`, `/api/meals/sync-groceries`, `/api/groceries`, `/api/groceries/budget`, `/api/groceries/price`, and `/api/groceries/refresh-coles`. Dashboard actions support adding and editing tasks, setting task recurrence, adding/editing calendar entries, planning meals, syncing meal ingredients, setting a grocery budget, and recording grocery prices; destructive operations remain unavailable until confirmation and permission rules are added.
## Tailnet access

The dashboard is served over the tailnet at:

- [http://vnic.tail015325.ts.net:8788](http://vnic.tail015325.ts.net:8788)
- `http://100.89.153.13:8788`

It is bound only to the Tailscale interface and managed by `family-planner-dashboard.service` as a user service. Tailscale Serve could not be used without sudo, so this direct interface bind is the non-root setup. The dashboard has no separate app login yet; tailnet membership/ACLs are the access boundary.
### Manual/local launch

```bash
python3 -m family_planner.dashboard \
  --database /home/ubuntu/workspace/family-planner/family_planner.db \
  --host 127.0.0.1 \
  --port 8788
```

Open [http://127.0.0.1:8788](http://127.0.0.1:8788). The dashboard is intentionally organized around the family's current state:

- A connected **What needs attention?** centre combines open tasks, unplanned dinners, unpriced/over-budget groceries, and meal assignments. Task rows can be completed inline; every item links to the page where it can be resolved.
- A **Today** view combines calendar events, dated task occurrences, and planned meals for the next 24 hours.
- A seven-day **Plan the week** strip shows dinners, calendar events, and recurring tasks together. Empty dinner slots link directly to the meal planner; meal cards link back to the relevant day.
- Viewer switcher for the two household members
- Private-by-default reminder note

- The dashboard supports safe shared mutations: adding/editing/completing/deleting tasks, assigning tasks, setting task recurrence, adding/editing calendar events, planning meals, syncing meal ingredients to Groceries, setting a weekly grocery budget, and recording grocery prices. Destructive task deletion requires browser confirmation.
- The API read model is available at `/api/dashboard?viewer=you` or `/api/dashboard?viewer=partner`; it includes `attention_items`, `today_items`, `planning_week`, `grocery_summary`, and the existing page-specific fields.
- Theme toggle: click the sun/moon button in the top-right. The preference persists in that browser via `localStorage`.
- The welcome greeting follows the browser's local time: morning (05:00–11:59), afternoon (12:00–16:59), evening (17:00–20:59), and quiet late-night copy (21:00–04:59).
- Grocery messages handled through the iMessage/Photon planner boundary write to the same SQLite store the dashboard reads, so shared items appear for both household views.

## Privacy behavior so far

- Grocery items are shared household records.
- `Remind me ...` creates a private task owned by the sender.
- `family tasks` creates an unassigned shared task.
- Every stored record keeps its creator.


## Next slice

Add explicit household identity configuration, completion/edit commands, conflict detection, and an adapter for the existing iMessage/Photon delivery path. The adapter should call `FamilyPlanner.handle_message(sender, text)` and send the returned response, keeping transport separate from planner state and policy.
