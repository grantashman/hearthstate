# Hearthstate repository instructions

## Identity and location

- Product name: **Hearthstate**.
- Repository path on this host: `/home/ubuntu/workspace/hearthstate`.
- GitHub remote: `https://github.com/grantashman/hearthstate.git`.
- Hosted production: `https://hearthstate.vercel.app`.
- Hosted canonical database/Auth: Supabase project `zcfzdqtjglelrbyhcvcu` in `ap-southeast-2`.

`api/index.py` is the Vercel/Supabase runtime boundary; `hearthstate/dashboard/` contains the hosted browser assets; `supabase/migrations/` owns the hosted schema; and `vercel.json` owns hosted route rewrites. There is no local application runtime in this repository.

## Working rules

1. Inspect `git status`, the current branch, and the remote before changing files.
2. Never commit or upload secrets, tokens, household data, backups, or ignored database artifacts.
3. Use the hosted API and Supabase migrations as the application boundaries.
4. Validate HTTP/user input and use parameterized SQL through the existing hosted boundary.
5. Prefer small, reviewable commits using Conventional Commit messages.
6. Do not force-push, reset shared branches, or alter production data without explicit user direction.
7. Before declaring work complete, run the hosted verification commands below and inspect the final diff.

## Verification gates

From the repository root:

```bash
PYTHONPYCACHEPREFIX=/tmp/hearthstate-pyc python3 -m unittest discover -s tests -v
PYTHONPYCACHEPREFIX=/tmp/hearthstate-pyc python3 -m compileall -q api tests
for file in hearthstate/dashboard/*.js; do node --check "$file"; done
git diff --check
```

Hosted smoke checks:

```bash
curl --fail --silent --show-error https://hearthstate.vercel.app/api/health
curl --fail --silent --show-error https://hearthstate.vercel.app/api/auth/config
```

Expected health response includes:

```json
{"status":"ok","service":"hearthstate","backend":"supabase"}
```

## GitHub workflow

- Work on a feature/fix/docs branch for non-trivial changes.
- Run the hosted verification gates before committing.
- Review staged changes for secrets and stale runtime references.
- Push with `git push -u origin HEAD` only after the user has asked to ship or the task explicitly authorizes a push.
- Check GitHub Actions after pushing and fix only failures caused by the current change.

## Hermes maintenance behavior

When asked to maintain Hearthstate:

1. Read this file and inspect the current repository state.
2. Review open work, recent commits, CI status, and relevant hosted tests before editing.
3. Make the smallest safe change, add or update tests where behavior changes, and run all hosted verification gates.
4. Use an independent review when the change is more than documentation/configuration.
5. Report the exact commit, pushed branch/PR URL when available, tests run, and any blocker.
