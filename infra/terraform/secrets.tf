# The AWS-side counterpart to infra/kubernetes/02-secrets.example.yaml's
# comment: this is where that manifest's "generate this from a real secret
# manager" advice actually gets implemented. ECS tasks read these via
# `secrets` (not `environment`) in their container definitions below, so
# the values are injected at container start by the ECS agent and never
# appear in a task definition's plaintext, in CloudTrail, or in this
# Terraform state's plan output.
resource "random_password" "webhook_secret" {
  length  = 48
  special = false
}

resource "aws_secretsmanager_secret" "database_url" {
  name = "payguard-${var.environment}-database-url"
}

resource "aws_secretsmanager_secret_version" "database_url" {
  secret_id     = aws_secretsmanager_secret.database_url.id
  secret_string = "postgresql+asyncpg://${var.db_username}:${random_password.db.result}@${aws_db_instance.main.address}:5432/${var.db_name}"
}

resource "aws_secretsmanager_secret" "redis_url" {
  name = "payguard-${var.environment}-redis-url"
}

resource "aws_secretsmanager_secret_version" "redis_url" {
  secret_id     = aws_secretsmanager_secret.redis_url.id
  secret_string = "redis://${aws_elasticache_cluster.main.cache_nodes[0].address}:6379/0"
}

resource "aws_secretsmanager_secret" "webhook_secret" {
  name = "payguard-${var.environment}-webhook-secret"
}

resource "aws_secretsmanager_secret_version" "webhook_secret" {
  secret_id     = aws_secretsmanager_secret.webhook_secret.id
  secret_string = random_password.webhook_secret.result
}
