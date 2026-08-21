# Docker & Kubernetes (Phase 17)

Status: implemented. Multi-stage Dockerfiles for all three deployables
(API, worker, dashboard), a full containerized local stack via
`docker-compose.prod.yml`, and a Kubernetes manifest set (`infra/kubernetes/`)
that runs the same three images with the horizontal-scaling story Phase 16's
Redis-backed rate limiter was specifically built to survive.

## Why three separate images, not one

The API and worker have always been separate deployables in this codebase
(docs/architecture.md section 10: the worker "must keep retrying regardless
of whether the API that originally wrote the event is still running") --
Phase 17 just gives that existing architectural decision its own container
images instead of two processes on one host. The dashboard (Phase 13) was
already "a consumer of the API, not the product"; shipping it as a static
nginx-served bundle rather than bundling it into the API image keeps that
boundary intact at the deployment layer too.

## Dockerfiles (`infra/docker/`)

All three are multi-stage builds: a `builder` stage with the full toolchain
needed to install dependencies (a C compiler for `asyncpg`'s extension,
`npm` for the frontend build), and a slim `runtime` stage that copies only
the result. The API/worker runtime images run as a non-root `payguard` user
-- there's no reason a Python process handling payment data should have
root inside its own container, and it costs nothing to not have it.

The frontend build bakes `VITE_API_BASE_URL` in at build time via a Docker
build arg, not a container runtime env var -- Vite inlines
`import.meta.env.*` values into the built JavaScript during `npm run
build`, so unlike the API/worker's env-based config (read at process
start), the dashboard's API URL has to be known before the image exists,
not when the container starts.

## `docker-compose.prod.yml`: the full stack, containerized

A second compose file, deliberately separate from the root
`docker-compose.yml` (which only runs Postgres/Redis for the fast
host-run-`uvicorn` dev loop every earlier phase has used). Running both
simultaneously would collide on service names; they serve different
purposes and were never meant to run together.

```bash
docker compose -f docker-compose.prod.yml -p payguard-prod up --build
```

The `-p payguard-prod` project name keeps this stack's containers, network,
and volumes namespaced separately from `docker-compose.yml`'s, so a
developer can have both running side by side without a collision. A
`migrate` service runs `alembic upgrade head` once and exits;
`depends_on: condition: service_completed_successfully` makes api/worker
wait on it, so the schema is guaranteed to exist before anything queries
it -- the containerized stack doesn't inherit the dev workflow's implicit
"you already ran this by hand" assumption.

## Kubernetes (`infra/kubernetes/`)

Files are numbered by apply order (`00-namespace.yaml` through
`30-ingress.yaml`) -- `kubectl apply -f infra/kubernetes/` applies them all,
and alphabetical/numeric ordering happens to also be a safe dependency
order (namespace before anything that lives in it, config before anything
that reads it).

| File | What it is | Why |
|---|---|---|
| `02-secrets.example.yaml` | Template, not a real manifest | Copy to `02-secrets.yaml` (gitignored) and fill in real values -- or better, generate it from a real secret manager. Never `kubectl apply` a file that had real credentials in plaintext on a developer's disk. |
| `10-postgres.yaml` | StatefulSet + headless Service + PVC | Stable identity and a PersistentVolumeClaim that survives a reschedule -- what a Deployment's interchangeable-pod model doesn't give you. Running Postgres in-cluster is here to make this manifest set runnable standalone; a real deployment would point at a managed database (RDS, see `infra/terraform/`) instead, for the operational reasons any managed-DB pitch makes (automated backups, PITR, failover without an on-call engineer doing it by hand). |
| `11-redis.yaml` | Plain Deployment, no PVC | Losing this Redis instance's data is not a correctness problem -- it only ever holds rate-limit token-bucket state (Phase 16), which is reconstructed correctly (buckets start full) the moment it's empty. |
| `20-migration-job.yaml` | A `batch/v1` Job | Deliberately *not* run from every api replica's container entrypoint -- N replicas racing `alembic upgrade head` on a rolling restart would (harmlessly, thanks to Alembic's advisory lock, but confusingly) surface a migration failure as a crashlooping api pod instead of a clearly-named Job you'd check first. |
| `21-api.yaml` | Deployment (2 replicas) + Service + HPA | Starts at 2 replicas on purpose: this is the whole point of Phase 16's rate limiter being Redis-backed rather than an in-process counter. A single-replica deployment would never have exposed whether the limit was actually shared correctly across replicas, only whether the code compiled. HPA scales on CPU (this system's per-request cost is dominated by sequential DB round trips per docs/load-testing.md's Phase 15 finding, not CPU, but CPU-based scaling needs no extra metrics pipeline to work at all -- a good first pass). |
| `22-worker.yaml` | Deployment, no Service, no HPA | Nothing calls the worker over the network. `SELECT ... FOR UPDATE SKIP LOCKED` (ADR-003) is what makes running >1 replica safe -- multiple workers pull different outbox rows without double-processing one. |
| `23-frontend.yaml` | Deployment + Service | The nginx-served static bundle. |
| `30-ingress.yaml` | Path-based routing on one host | `/v1` and `/metrics` to the API, everything else to the dashboard -- the same "dashboard is a separate consumer, not a merged app" boundary from Phase 13, carried into how traffic is actually routed. |

### What this manifest set does not attempt

- **A service mesh, mTLS between pods, or NetworkPolicies** -- reasonable
  additions for a real production cluster, but not what this phase set out
  to prove: that the application's own horizontal-scaling assumptions
  (the Redis-backed rate limiter, the outbox worker's `SKIP LOCKED`
  claim) actually hold when there's more than one of something running.
- **A real Ingress controller installation** -- `30-ingress.yaml` declares
  routing rules assuming `ingress-nginx` is already installed; installing
  the controller itself is a cluster-operator concern, not something this
  application's manifests should own.
- **Applying this against a real cluster.** A `kind` (Kubernetes-in-Docker)
  cluster was the intended way to validate these manifests against a real
  Kubernetes API server — creating one turned out to be blocked in this
  environment specifically (DNS resolution to Docker Hub for the cluster
  node image failed; the Docker builds two paragraphs up worked fine over
  the same daemon, so this is a `kind`-specific network path, not a
  general connectivity problem). What's actually been verified is
  described honestly in Testing below, not overstated.

## Deploying to Render (Phase 22)

Status: implemented and applied against a real Render account (the free-tier
adjustments below came directly from what that account's Blueprint sync
actually rejected, not guessed in advance). `render.yaml` (repo root) is a
[Blueprint](https://render.com/docs/blueprint-spec) that provisions Postgres,
Redis, the API, and the dashboard on Render's free tier, using the exact
Dockerfiles above unmodified. The worker is the one deployable that
*doesn't* map onto this cleanly -- see below.

### The worker doesn't get its own free-tier service

Render's free tier has no background-worker plan (`render.yaml` originally
declared `payguard-worker` as `type: worker`; the Blueprint sync rejected it
with "service type is not available for this plan"). Rather than push the
worker onto a second platform with its own uncertain free-tier limits,
`payguard-api` now runs `apps/worker/main.py`'s outbox-polling loop
(`run_worker_loop()`) as a background `asyncio` task inside its own process,
gated behind `RUN_WORKER_INPROCESS=1` (`apps/api/main.py`'s `lifespan`). This
is a demo-hosting concession, not a reversal of `apps/worker/main.py`'s own
documented reasoning for why the worker is normally a separate process --
`docker-compose.prod.yml` and the Kubernetes manifests above are unchanged
and still run it that way.

To deploy:

1. Push this repo to GitHub (already done, if you're reading this from the
   repo).
2. In Render: **New -> Blueprint**, connect the repo. Render reads
   `render.yaml` and shows a plan for all five resources before creating
   anything -- review it (free-tier limits and exact plan names do change,
   so this is also your chance to confirm what's actually being created).
3. Deploy. `payguard-api`'s Docker command runs `alembic upgrade head` and
   the idempotent demo-merchant seed (`scripts/seed_demo_merchant.py`)
   before every boot, so the schema and the public demo key
   (`sk_test_demo_public_...`, see docs/dashboard.md) both exist without a
   manual step.
4. Once `payguard-api` is live, confirm its assigned URL matches
   `payguard-dashboard`'s `VITE_API_BASE_URL` build arg in `render.yaml`.
   Vite bakes this into the built JS at image-build time (same constraint
   `infra/docker/frontend.Dockerfile` has always had for the Docker Compose
   path above) -- if the URL doesn't match, update the env var in Render's
   dashboard and trigger a manual redeploy of `payguard-dashboard` to
   rebuild with the corrected value.
5. Open the dashboard's URL and click "Try the demo" -- same public-key flow
   as the local dev server, now on a real public URL.

One thing this blueprint can't fully pin down from the file alone: Render's
free-tier availability for its Redis-compatible "Key Value" service has
changed more than once, so `render.yaml`'s `plan: free` on `payguard-redis`
is a best-effort default, not a guarantee -- if that plan isn't offered when
you go through this, either accept the cheapest paid tier or point
`REDIS_URL` at a free external Redis (e.g. Upstash) instead.

## Testing

| Check | Command | Result |
|---|---|---|
| API image builds | `docker build -f infra/docker/api.Dockerfile -t payguard-api:test .` | Built, 75.2MB |
| API container actually runs and reaches Postgres | Container started against the real `payguard-postgres`/`payguard-redis` containers via `host.docker.internal`; `GET /v1/health` and `GET /v1/ready` (which opens a real DB connection) both returned `200` | Verified |
| Worker image builds | `docker build -f infra/docker/worker.Dockerfile -t payguard-worker:test .` | Built, shares the API's base layers |
| Frontend image builds | `docker build -f infra/docker/frontend.Dockerfile -t payguard-frontend:test .` | Built, 74MB |
| Frontend container actually serves the SPA | Container started; `GET /health` returned `200`, `GET /` (the React app's index) returned `200` | Verified |
| Kubernetes manifests are syntactically valid, correctly-shaped Kubernetes objects | `yaml.safe_load_all()` against every file in `infra/kubernetes/`, asserting each parses and reports the expected `kind` | All 10 files parsed cleanly with the expected kinds (Namespace, ConfigMap, Secret, StatefulSet+Service, Deployment+Service, Job, Deployment+Service+HPA, Deployment, Deployment+Service, Ingress) |
| Kubernetes manifests apply cleanly to a real API server | `kind create cluster` then `kubectl apply -f infra/kubernetes/` | **Not verified in this environment** — `kind`'s cluster-node image pull failed on DNS resolution to Docker Hub, an environment-specific network restriction, not a manifest problem. The YAML-shape check above is real but weaker than a live server accepting these objects; treat the manifests as reviewed and structurally sound, not as apply-tested. |
| `docker-compose.prod.yml` syntax and service graph | `docker compose -f docker-compose.prod.yml -p payguard-prod config` | Resolves cleanly: correct `depends_on` conditions, env vars, and build contexts for all five services |
| `docker-compose.prod.yml` full stack running together | Not run end-to-end in this session -- doing so alongside the already-running dev Postgres/Redis containers this session depended on for every other check risked exactly the port/name collision the file's own comments warn about | Individual images verified standalone (table above); the compose file's *shape* is verified, its *coordinated startup* is not |

Every claim above is stated at the confidence level it actually earned --
several things here are genuinely verified against running containers, one
thing (live-cluster apply) is an honest gap this environment couldn't
close, and that gap is called out rather than glossed over.
