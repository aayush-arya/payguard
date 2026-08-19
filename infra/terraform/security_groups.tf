# Each security group only allows traffic from the specific security group
# that legitimately needs it -- never a CIDR range, and never each other's
# full subnet -- mirroring this codebase's own "narrowest correct scope"
# instinct (Phase 16's tenant isolation, merchant_id filtering at the
# repository layer) applied to network access instead of application rows.

resource "aws_security_group" "alb" {
  name_prefix = "payguard-${var.environment}-alb-"
  vpc_id      = aws_vpc.main.id

  ingress {
    description = "HTTP from the internet -- a real deployment terminates TLS here or one hop earlier at a CDN; not modeled in this reference module."
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "payguard-${var.environment}-alb" }
}

resource "aws_security_group" "ecs_api" {
  name_prefix = "payguard-${var.environment}-ecs-api-"
  vpc_id      = aws_vpc.main.id

  ingress {
    description     = "Only from the ALB -- the API is never reachable directly."
    from_port       = var.container_port
    to_port         = var.container_port
    protocol        = "tcp"
    security_groups = [aws_security_group.alb.id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "payguard-${var.environment}-ecs-api" }
}

resource "aws_security_group" "ecs_worker" {
  name_prefix = "payguard-${var.environment}-ecs-worker-"
  vpc_id      = aws_vpc.main.id

  # No ingress rule at all -- nothing calls the worker over the network
  # (docs/architecture.md section 10), matching infra/kubernetes/22-worker.yaml's
  # identical "no Service" decision at the Kubernetes layer.
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "payguard-${var.environment}-ecs-worker" }
}

resource "aws_security_group" "rds" {
  name_prefix = "payguard-${var.environment}-rds-"
  vpc_id      = aws_vpc.main.id

  ingress {
    description     = "Postgres, only from the api and worker tasks."
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.ecs_api.id, aws_security_group.ecs_worker.id]
  }

  tags = { Name = "payguard-${var.environment}-rds" }
}

resource "aws_security_group" "redis" {
  name_prefix = "payguard-${var.environment}-redis-"
  vpc_id      = aws_vpc.main.id

  ingress {
    description     = "Redis, only from the api tasks -- the worker never touches Redis (Phase 16's rate limiter is API-only, packages/ratelimit is imported only by apps/api)."
    from_port       = 6379
    to_port         = 6379
    protocol        = "tcp"
    security_groups = [aws_security_group.ecs_api.id]
  }

  tags = { Name = "payguard-${var.environment}-redis" }
}
