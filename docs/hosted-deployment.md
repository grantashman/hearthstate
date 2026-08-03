# Hosted deployment

Hearthstate now has a hosted P1.3 boundary:

- Supabase project: `hearthstate` in `ap-southeast-2`.
- Vercel entrypoint: `api/index.py`.
- Root hosted page: the existing full branded dashboard under `hearthstate/dashboard/`.
- API routes are rewritten through `vercel.json`.

Supabase is the canonical hosted data store. SQLite remains only as a local compatibility and test path; the Vercel runtime does not read the server's SQLite database. The hosted app uses the existing branded login and dashboard pages, Supabase email OTP authentication plus a temporary password fallback, an HTTP-only session cookie, household membership RLS, and the full dashboard routes for tasks, calendar, meals, groceries, recipes, Inbox, chores, preferences, administration, and invitations.

## Temporary password fallback

The hosted login includes a temporary password option while email delivery is unavailable. It calls Supabase Auth's standard password token endpoint and then uses the same `/api/auth/session` boundary as email OTP, so it does not bypass Auth, memberships, or RLS. Use the email address of the existing Supabase Auth user and its password. This UI is intentionally marked for removal once email delivery is restored; do not use a shared or hard-coded application password.

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

## GitHub-driven production

The repository includes [`.github/workflows/production.yml`](../.github/workflows/production.yml). Every push to `main` deploys the Vercel build to `https://hearthstate.vercel.app`; when `supabase/migrations/` changes, the workflow applies those committed migrations first.

Add these GitHub Actions secrets in the repository's `production` environment:

```text
SUPABASE_ACCESS_TOKEN
SUPABASE_DB_PASSWORD
VERCEL_TOKEN
VERCEL_ORG_ID
VERCEL_PROJECT_ID
```

`SUPABASE_PROJECT_ID` is already pinned to `zcfzdqtjglelrbyhcvcu` in the workflow. `VERCEL_ORG_ID` and `VERCEL_PROJECT_ID` must come from the connected Vercel project settings; they are not available through the current Vercel connector. The Vercel project must also contain `SUPABASE_URL`, `SUPABASE_PUBLISHABLE_KEY`, and the server-only `SUPABASE_SERVICE_ROLE_KEY` environment variables for Production.

If using native integrations instead of the included workflow, connect `grantashman/hearthstate` in Vercel Project Settings → Git with `main` as the Production Branch, and connect the same repository in Supabase Project Settings → Integrations → GitHub Integration with working directory `.` and production deployment from `main`. Use one deployment mechanism, not both, to avoid duplicate production deploys.
