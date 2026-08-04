# Overnight production sprint — 2026-08-04

## Scope

This sprint moved Hearthstate toward the hosted production baseline described in
`.hermes/plans/2026-08-03_141918-hearthstate-commercial-roadmap.md` and
`docs/maintainer-handoff.md`. The work prioritised household privacy,
transactional mutation boundaries, installability, and multi-household
correctness rather than adding another broad feature surface.

## Shipped slices

The work is preserved as separate commits on
`feat/overnight-production-sprint` and PR #10:

- `144086d` — `fix: make household mutations transactional`
  - Membership administration and invitation acceptance use actor-bound,
    transactional RPCs.
  - Task completion/deletion boundaries preserve household and actor scope.
  - Audit writes are kept inside the mutation transaction where applicable.
- `607f115` — `feat: make hosted dashboard installable`
  - Added the hosted manifest and a progressive static-shell service worker.
  - The service worker deliberately excludes household HTML, API responses,
    analytics, and cross-origin data from its cache.
  - Added best-effort registration and an install affordance.
- `dc99913` — `fix: restrict task deletion actors`
  - Shared task deletion is limited to owners or the task creator.
  - Task deletion is routed through the actor-bound transactional boundary and
    preserves the existing task-ID response contract.
- `24738b2` — `fix: preserve household selection across dashboard calls`
  - Added 192x192 and 512x512 branded PNG PWA icons plus the iOS touch-icon
    link on manifest-bearing pages.
  - Added public PNG asset routing and precaching.
  - Bumped the static cache to `hearthstate-static-v2`.
  - Centralised `X-Hearthstate-Household` propagation in `nav.js` and migrated
    authenticated dashboard calls across dashboard, meals, recipes, tasks,
    calendar, groceries, Inbox, activity, chores, and notifications.

## Review findings and resolutions

An independent pre-ship review identified two blockers against the earlier
meal/audit ref:

1. Task deletion was not actor-bound or audited. Fixed in `dc99913` with a
   transactional deletion boundary and database-side owner/creator checks.
2. Multi-household dashboard callers omitted the selected household header.
   Fixed in `24738b2` with a shared fetch wrapper that reads only the
   server-injected viewer bootstrap household ID.

The review also recommended database-backed RLS/RPC tests and a migration
report for cleanup of invalid historical meal cooks. Those remain follow-up
work; the current repository test suite is contract-oriented and no live
PostgreSQL test harness was available in this environment.

## Verification

The final local verification before `24738b2` was committed returned:

- `Ran 132 tests in 0.418s — OK`
- Python compilation passed.
- `node --check` passed for every dashboard JavaScript file.
- Manifest JSON parsing passed.
- PNG signature and dimensions passed for both icons.
- `git diff --check` passed.

PR #10 had passing Python 3.11, Python 3.12, Vercel preview, and preview
comments checks before the final `24738b2` push. Fresh checks for that commit
must pass before merge.

## Research notes

Official guidance consulted:

- Chrome/Web.dev installability requirements:
  <https://web.dev/installable-manifest/>
  - A valid installable manifest needs a name/short name, start URL,
    standalone-compatible display mode, and 192x192 and 512x512 icons.
  - iOS uses manual Add to Home Screen flow and benefits from an
    `apple-touch-icon` link.
- Supabase production checklist:
  <https://supabase.com/docs/guides/deployment/going-into-prod>
  - Review RLS and Security Advisor, enforce SSL, consider network
    restrictions and MFA, configure production auth email delivery, set an
    appropriate backup/PITR posture, and use repeatable GitHub-backed
    migrations.
- Vercel production checklist:
  <https://vercel.com/docs/production-checklist>
  - Review CSP/security headers, deployment protection, WAF/rate limiting,
    log retention, spend alerts, function/database region alignment,
    observability, rollback procedures, and incident response.

## Remaining production checklist

These items require account-level dashboard access or a live staging database
and were not fabricated as completed:

- Run Supabase Security Advisor and verify RLS on every sensitive table.
- Confirm SSL enforcement, network restrictions, MFA, auth email confirmation,
  OTP expiry, and production SMTP settings.
- Confirm backup/PITR settings against the household data recovery objective.
- Run migration `20260804120000_auditable_task_completion.sql` in the hosted
  Supabase project and verify the RPC grants/functions in the database.
- Configure Vercel CSP/security headers, WAF/rate limiting, spend alerts,
  observability, and a documented rollback path.
- Add a staging database test suite covering RLS, cross-household RPC attempts,
  rollback on audit failure, and composite household membership constraints.
- Add migration telemetry or a remediation path for any historical meal cooks
  removed because they were not household members.

## Product direction after this sprint

The highest-value follow-ups remain:

1. Real multi-user household pilot with privacy and authorization probes.
2. Hosted operational controls: rate limiting, CSP, alerts, backups, and
   migration observability.
3. Database-backed end-to-end tests for the actor-bound mutation layer.
4. Product differentiation around confirmation-first capture, Inbox review,
   privacy-safe activity/undo, and Photon/iMessage household workflows.

## Post-merge deployment correction

The first PR #10 production smoke test correctly exposed a deployment routing
bug: Vercel served the Python asset handler for local tests, but `vercel.json`
did not rewrite the new root-level manifest, service worker, or nested icon
paths. Those production requests returned 404 while existing health, login, and
favicon routes remained healthy.

The correction was shipped separately:

- `e139176` — `fix: route hosted PWA assets through Vercel`
- PR #11: <https://github.com/grantashman/hearthstate/pull/11>
- Merge commit: `7664379`
- Production migration/deployment workflow: successful

Final public smoke test against `https://hearthstate.vercel.app`:

| Route | Result |
|---|---|
| `/api/health` | HTTP 200, JSON |
| `/api/auth/config` | HTTP 200, JSON |
| `/manifest.webmanifest` | HTTP 200, manifest JSON |
| `/sw.js` | HTTP 200, JavaScript |
| `/icons/icon-192.png` | HTTP 200, PNG |
| `/icons/icon-512.png` | HTTP 200, PNG |
| `/favicon.svg` | HTTP 200, SVG |
| `/login` | HTTP 200, HTML |

The preview deployment itself required Vercel Deployment Protection and could
not be inspected anonymously without a bypass credential; no bypass secret
was requested, copied, or logged.

PR #10: <https://github.com/grantashman/hearthstate/pull/10>
PR #11: <https://github.com/grantashman/hearthstate/pull/11>
