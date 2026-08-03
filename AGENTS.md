# Hearthstate repository instructions

## Identity and location

- Product name: **Hearthstate**.
- Repository path on this host: `/home/ubuntu/workspace/hearthstate`.
- GitHub remote: `https://github.com/grantashman/hearthstate.git`.
- Python package: `hearthstate`.
- Main application class: `Hearthstate`.
- Default live database: `/home/ubuntu/workspace/hearthstate/hearthstate.db`.
- Hosted production: `https://hearthstate.vercel.app`.
- Hosted canonical database/Auth: Supabase project `zcfzdqtjglelrbyhcvcu` in `ap-southeast-2`.
- Current local Mac checkout: `/Users/grant/Documents/Hearthstate`; Hermes/Linux normally uses the repository path above.

Do not reintroduce `family_planner`, `FamilyPlanner`, `FAMILY_PLANNER_DB`, or `family-planner` service/path names. Use Hearthstate naming consistently in code, docs, tests, deployment files, and Hermes skills.

For the full subsystem map and hosted Auth/session flow, read [`docs/maintainer-handoff.md`](docs/maintainer-handoff.md). In brief: `api/index.py` is the Vercel/Supabase boundary; `hearthstate/dashboard.py` is the local SQLite/tailnet boundary; `hearthstate/app.py` and `hearthstate/store.py` are the planner/application boundary; `supabase/migrations/` owns hosted schema changes; and `vercel.json` owns hosted route rewrites.

## Working rules

1. Inspect `git status`, the current branch, and the remote before changing files.
2. Preserve the local SQLite database and backups. They are operational household data and must never be committed or uploaded.
3. Use the existing application boundaries for database access; do not inspect or mutate the live SQLite database directly from an agent task.
4. Keep grocery, reminder, assignment, calendar, meal, recipe, inbox, and dashboard behavior covered by tests.
5. Use parameterized SQL and validate HTTP/user input. Do not add secrets, tokens, phone numbers, or private household data to tracked files.
6. Prefer small, reviewable commits using Conventional Commit messages.
7. Do not force-push, reset shared branches, delete data, or change production services without explicit user direction.
8. Before declaring work complete, run the verification commands below and inspect the final diff.

## Verification gates

From the repository root:

```bash
python3 -m unittest discover -s tests -v
python3 -m compileall -q hearthstate scripts tests
for file in hearthstate/dashboard/*.js; do node --check "$file"; done
git diff --check
```

For local dashboard or deployment changes, also verify:

```bash
systemctl --user is-active hearthstate-dashboard.service
curl --fail --silent --show-error http://vnic.tail015325.ts.net:8788/health
```

Expected local health response includes:

```json
{"status":"ok","service":"hearthstate","database":"ok","integrity":"ok"}
```

Hosted smoke checks use the production API instead of the local service:

```bash
curl --fail --silent --show-error https://hearthstate.vercel.app/api/health
```

Expected hosted fields include `{"status":"ok","service":"hearthstate","backend":"supabase"}`. The hosted runtime does not read the local SQLite database.

## GitHub workflow

- Work on a feature/fix/docs branch for non-trivial changes.
- Run the verification gates before committing.
- Review staged changes for secrets and stale project names.
- Push with `git push -u origin HEAD` only after the user has asked to ship or the task explicitly authorizes a push.
- Use pull requests for changes that need review; do not silently merge or force-push.
- Check GitHub Actions after pushing and fix only failures caused by the current change.

## Hermes maintenance behavior

When asked to maintain Hearthstate:

1. Read this file and inspect the current repository state.
2. Review open work, recent commits, CI status, and relevant tests before editing.
3. Make the smallest safe change, add or update tests where behavior changes, and run all verification gates.
4. Use an independent review when the change is more than documentation/configuration.
5. Report the exact commit, pushed branch/PR URL when available, tests run, and any blocker.

A scheduled maintenance check may report stale CI, dependency, or documentation issues. It must not push, merge, delete, or deploy without an explicit authorization policy from the user.
