# Terraform / AWS Deployment (Phase 18)

Status: implemented as reference infrastructure-as-code, **not applied**.
`infra/terraform/` provisions the AWS shape docs/deployment.md's Kubernetes
manifests already gestured at needing (a managed database and cache
instead of the StatefulSet/Deployment reference versions) — VPC, RDS
Postgres, ElastiCache Redis, ECS Fargate services for the API and worker,
an ALB, ECR repositories, and the IAM/Secrets Manager wiring to run them
without a plaintext credential anywhere in a task definition.

## Why "not applied" is the honest answer, not a hedge

This project has no AWS account, no billing owner, and no authorization to
create real cloud resources — and creating them would cost real money for
infrastructure nothing here would ever actually serve traffic to. Every
other phase's "done" has meant "built, tested, verified against something
real" (a live Postgres database, a real HTTP request, a real container
actually running). Phase 18's version of that standard is: the
configuration is syntactically valid and internally consistent, checked
the same way a real team checks it before ever touching a real AWS
account — `terraform validate`, `terraform fmt -check`, provider
resolution via `terraform init` — not a live `terraform plan`/`apply`
against real infrastructure, which needs credentials and a bill nobody in
this project's development is positioned to authorize.

```
$ terraform init      # resolved and locked hashicorp/aws ~> 5.0, hashicorp/random ~> 3.6
$ terraform fmt -check # caught real formatting drift on first run, fixed
$ terraform validate
Success! The configuration is valid.
```

## What it provisions, and why each piece looks the way it does

| Resource | Design choice | Why |
|---|---|---|
| VPC, public/private subnets across 2 AZs | Application containers, RDS, and ElastiCache all live in private subnets; only the ALB and one NAT gateway are public | The API is reachable only through the ALB, never directly — the same "nothing calls the worker over the network" boundary from `infra/kubernetes/22-worker.yaml` enforced at the network layer, not just by omitting a Kubernetes Service |
| One NAT gateway, not one per AZ | A stated cost/availability tradeoff, not a silent gap | Reference infrastructure for a portfolio project's traffic shape doesn't need per-AZ NAT redundancy; a team taking this to real production would add the second one and should know exactly why it wasn't there to start with |
| RDS Postgres, Multi-AZ when `environment == "production"` | Managed database instead of the Kubernetes StatefulSet's self-hosted Postgres | Automated backups, point-in-time recovery, and failover without an on-call engineer doing it by hand — the exact tradeoff `infra/kubernetes/10-postgres.yaml`'s own comment already named as what a real deployment would reach for instead |
| ElastiCache Redis, single node, no replication group | Deliberately *not* highly available | Mirrors `packages/ratelimit`'s own design: a Redis outage means rate-limit buckets reset to full, never a correctness failure (an empty bucket state is indistinguishable from a full one to the Lua script). That's not a workload worth paying for Redis's own HA story — unlike RDS, where losing the ledger is a real incident |
| ECS Fargate, `api` starting at 2 tasks | No EC2 instances to manage; replica count mirrors `infra/kubernetes/21-api.yaml`'s reasoning exactly | Phase 16's Redis-backed rate limiter is only proven to share a limit correctly across replicas if more than one replica actually runs — a `desired_count = 1` default would silently retreat from that proof |
| Every security group scoped to a specific peer security group, never a CIDR range | RDS only accepts connections from the api/worker security groups; Redis only from api's | The same narrowest-correct-scope instinct as Phase 16's tenant isolation (`merchant_id` filtering at the repository layer, never left to individual handlers to remember), applied to network ACLs instead of database rows |
| IAM execution role's Secrets Manager policy scoped to exactly 3 ARNs | Not `secretsmanager:GetSecretValue` on `"*"` | Same instinct, applied to IAM |
| `random_password` for the RDS master password and webhook secret, referenced only into Secrets Manager | Never a `variable`, never in `terraform.tfvars` | A password that *could* be set via a variable is a password that could end up committed in a `.tfvars` file by mistake — removing that possibility entirely is simpler than trusting everyone to always remember not to |
| ECS task definitions read secrets via `secrets`, never `environment` | Values injected by the ECS agent at container start | They never appear in a task definition's plaintext, in CloudTrail, or in a `terraform plan` output the way an `environment` block's values would |

## What a real production rollout would still need before this is safe to apply

- **Remote state** (the commented `backend "s3"` block in `versions.tf`)
  and a locking table — local state is fine for `validate`, not for a team.
- **TLS**: the ALB listener here is plaintext HTTP on port 80 because ACM
  certificate provisioning needs a real domain this reference module
  doesn't own. A real listener is 443 with a cert and an 80→443 redirect.
- **A reviewed IAM boundary** beyond "scoped to what this module's own
  resources need" — a real account has more going on than one Terraform
  root module, and least-privilege for *this stack* isn't the same
  question as least-privilege for *the account*.
- **Someone who owns the AWS bill** and has actually authorized spending
  on RDS Multi-AZ, NAT gateway hours, and Fargate vCPU-hours running
  24/7 — the one prerequisite no amount of careful Terraform can supply.

## Testing

| Check | Command | Result |
|---|---|---|
| Provider resolution | `terraform init` | Resolved `hashicorp/aws ~> 5.0` (v5.100.0) and `hashicorp/random ~> 3.6` (v3.9.0), wrote `.terraform.lock.hcl` |
| Formatting | `terraform fmt -check -diff` | Found real drift on the first run (inconsistent alignment across 4 files); `terraform fmt` fixed it, re-run is clean |
| Syntax and internal consistency | `terraform validate` | `Success! The configuration is valid.` |
| Live plan/apply against real AWS | Not run — no AWS account or authorization exists for this project | Explicitly out of scope; see "not applied" above |
