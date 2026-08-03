# Hosted deployment

Hearthstate now has a hosted P1.3 boundary:

- Supabase project: `hearthstate` in `ap-southeast-2`.
- Vercel entrypoint: `api/index.py`.
- Root hosted page: the existing full branded dashboard under `hearthstate/dashboard/`.
- API routes are rewritten through `vercel.json`.

Supabase is the canonical hosted data store. SQLite remains only as a local compatibility and test path; the Vercel runtime does not read the server's SQLite database. The hosted app uses the existing branded login and dashboard pages, Supabase email OTP authentication, an HTTP-only session cookie, household membership RLS, and the full dashboard routes for tasks, calendar, meals, groceries, recipes, Inbox, chores, preferences, administration, and invitations.

## Environment

For a Vercel project, set these variables for Preview and Production:

```text
SUPABASE_URL=https://<project-ref>.supabase.co
SUPABASE_PUBLISHABLE_KEY=<publishable-key>
SUPABASE_SERVICE_ROLE_KEY=<server-only-service-role-key>
```

Set the first two variables for Preview and Production. Set the service-role key only as a server-side Vercel variable; it is used by the Vercel function for invitation inspection/acceptance and is never returned to the browser. Never put a service-role key in client code, `vercel.json`, or the repository.

The remote migrations are recorded under `supabase/migrations/`. The hosted schema enables RLS on every public table and returns no security-advisor lints.

## Local checks

```bash
PYTHONPYCACHEPREFIX=/tmp/hearthstate-pyc python3 -m unittest tests.test_hosted_api -v
PYTHONPYCACHEPREFIX=/tmp/hearthstate-pyc python3 -m compileall -q api hearthstate tests
```

## Cutover

The hosted migration is now the application path for Vercel. Add the three variables above in the Vercel project for Preview and Production, then deploy the branch or promote it to the project's production branch. Existing local SQLite data is not uploaded automatically; a deliberate export/import adapter is required before moving household records into Supabase.
