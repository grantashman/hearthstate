# Hosted deployment

Hearthstate now has a hosted P1.3 boundary:

- Supabase project: `hearthstate` in `ap-southeast-2`.
- Vercel entrypoint: `api/index.py`.
- Root hosted page: `hearthstate/dashboard/hosted.html`.
- API routes are rewritten through `vercel.json`.

The local SQLite dashboard remains available and unchanged for the existing pilot and Photon workflows. The hosted page uses Supabase email OTP authentication, selects a household membership, and currently supports the hosted dashboard read model plus Inbox capture and core task, calendar, meal, and grocery record creation.

## Environment

For a Vercel project, set these variables for Preview and Production:

```text
SUPABASE_URL=https://<project-ref>.supabase.co
SUPABASE_PUBLISHABLE_KEY=<publishable-key>
```

The publishable key is intended for client-side use. Never put a Supabase service-role key in Vercel client code, `vercel.json`, or the repository.

The remote migrations are recorded under `supabase/migrations/`. The hosted schema enables RLS on every public table and returns no security-advisor lints.

## Local checks

```bash
PYTHONPYCACHEPREFIX=/tmp/hearthstate-pyc python3 -m unittest tests.test_hosted_api -v
PYTHONPYCACHEPREFIX=/tmp/hearthstate-pyc python3 -m compileall -q api hearthstate tests
```

## Next cutover steps

The hosted boundary is intentionally incremental. The existing dashboard pages, invitation/admin flow, notifications, recipes, briefing delivery, and data export still need hosted adapters before the local SQLite deployment can be retired. Production promotion also requires a Vercel team member with Production Deployment permission.
