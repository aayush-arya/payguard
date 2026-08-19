# CI/CD (Phase 19)

Status: implemented and running for real. `.github/workflows/ci.yml` runs
on every push/PR against `main` — unlike Phase 18's Terraform (validated
but never applied, for lack of an AWS account this project could
authorize spending on), GitHub Actions is something this project's real
repository can actually run, so this phase's "done" means a real green
run on GitHub, not just a workflow file that looks plausible.

## Six independent jobs, not one long pipeline

| Job | What it checks | Why it's separate from the others |
|---|---|---|
| `lint` | `ruff check .` + `ruff format --check .` | Fastest job (no service containers, no dependency install beyond ruff itself) — fails first and fails fast, so a formatting slip doesn't wait behind a 4+ minute test run to be reported |
| `backend-tests` | The full `pytest tests/` suite against real Postgres + Redis service containers | The one job that actually needs live infrastructure — everything this project has ever tested against is a real database, never a mock, and CI is no exception |
| `frontend` | `tsc -b && vite build` (via `npm run build`) then `oxlint` | Independent of the backend entirely — a frontend-only change shouldn't wait on Postgres spinning up to get feedback |
| `docker-build` | All three Dockerfiles actually build, via a matrix (`api`/`worker`/`frontend`) | Catches a Dockerfile bug (a missing `COPY`, a broken build stage) before it reaches Phase 17's manifests, which assume these images build cleanly |
| `terraform` | `terraform fmt -check` + `terraform init -backend=false` + `terraform validate` | The exact three checks docs/terraform.md documents as what was actually verified locally — CI re-runs them on every push so that guarantee doesn't quietly rot as the module changes |
| `kubernetes-manifests` | Every file in `infra/kubernetes/` parses as YAML and every document declares a `kind` | The same check `docs/deployment.md` describes running locally, now enforced on every push instead of only when someone remembers to run it by hand |

All six run in parallel — there's no reason `terraform validate` should
wait on `pytest` finishing, and structuring the workflow as one dependency
chain would only make every push slower without buying any additional
safety.

## Why the test job isn't parallelized internally

`pytest tests/ -v` runs single-threaded, not under `pytest-xdist`.
`tests/concurrency/` and `tests/e2e/` deliberately open many real
concurrent database connections *within* a single test to prove
race-condition safety (the same 100-concurrent-request proof this project
has relied on since Phase 2); parallelizing test *files* on top of that
would multiply concurrent connection demand against Postgres's connection
limit for no benefit — the identical reason this project's own established
local workflow always stops any live preview server before running the
full suite (docs/observability.md's Phase 11 lesson, referenced in every
phase's completion checklist since).

## Concurrency control

```yaml
concurrency:
  group: ci-${{ github.ref }}
  cancel-in-progress: true
```

A second push to the same branch cancels whatever run is already in
flight for it. There's no value in a CI provider finishing a ~5-minute
test run against a commit that's already been superseded by the next
push — cancelling frees the runner for the commit that actually matters
now.

## Testing

This phase's own test *is* itself: pushed to `main` and watched via
`gh run watch` against the real repository, not inferred from the YAML
looking correct. See the commit this phase shipped in for the actual run
result.
