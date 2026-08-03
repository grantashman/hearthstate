# Hosted deployment

Hearthstate runs as a hosted Vercel/Supabase application.

- Supabase project: `hearthstate` in `ap-southeast-2`.
- Vercel entrypoint: `api/index.py`.
- Root page and static assets: `hearthstate/dashboard/`.
- API routes: rewritten through `vercel.json`.
- Canonical production URL: `https://hearthstate.vercel.app`.

Supabase is the only application data store. The hosted app uses Supabase email OTP authentication plus a temporary password fallback, an HttpOnly session cookie, household membership RLS, and dashboard routes for tasks, calendar, meals, groceries, recipes, Inbox, chores, preferences, administration, and invitations.

## Environment

For Vercel Production and Preview, set:

```text
SUPABASE_URL=https://<project-ref>.supabase.co
SUPABASE_PUBLISHABLE_KEY=<publishable-key>
SUPABASE_SERVICE_ROLE_KEY=<server-only-service-role-key>
```

The service-role key is used only by the Vercel function for server-side operations and is never returned to the browser. Never put it in client code, `vercel.json`, or the repository.

The committed migrations under `supabase/migrations/` enable RLS on public tables and define the hosted RPC/API surface.

## Supabase Auth URLs

Configure Supabase Dashboard → Authentication → URL Configuration:

- Site URL: `https://hearthstate.vercel.app`
- Redirect URL: `https://hearthstate.vercel.app/login`

The login page sends its current `/login` origin explicitly when requesting a magic link and consumes Supabase's access-token redirect fragment. Preview deployments need a separately allowed redirect only if preview authentication is required.

## Provisioning

The first hosted household is provisioned in Supabase as an operator step. An authenticated account without a membership may use `/setup` to create its first household; an existing member visiting `/setup` is redirected to `/`.

## Verification

```bash
PYTHONPYCACHEPREFIX=/tmp/hearthstate-pyc python3 -m unittest tests.test_hosted_api -v
PYTHONPYCACHEPREFIX=/tmp/hearthstate-pyc python3 -m compileall -q api tests
for file in hearthstate/dashboard/*.js; do node --check "$file"; done
git diff --check
```

Hosted smoke checks:

```bash
curl --fail --silent --show-error https://hearthstate.vercel.app/api/health
curl --fail --silent --show-error https://hearthstate.vercel.app/api/auth/config
```

The hosted health response should include:

```json
{"status":"ok","service":"hearthstate","backend":"supabase"}
```

## GitHub-driven production

The repository includes [`.github/workflows/production.yml`](../.github/workflows/production.yml). Vercel deploys every push to `main` through its connected Git integration; when `supabase/migrations/` changes, GitHub Actions applies those committed migrations.

Add these GitHub Actions secrets in the repository's `production` environment:

```text
SUPABASE_ACCESS_TOKEN
SUPABASE_DB_PASSWORD
```

`SUPABASE_PROJECT_ID` is pinned in the workflow. The Vercel project must have `grantashman/hearthstate` connected with `main` as its Production Branch and must contain the three Supabase variables for Production.

The workflow intentionally does not call the Vercel CLI: Vercel owns deployment from its connected Git integration.
