# Generated, never hand-chosen -- and never referenced anywhere in this
# module except into Secrets Manager below. There is no terraform.tfvars
# entry for this on purpose: a password that could be set via a variable
# is a password that could end up in a .tfvars file someone commits.
resource "random_password" "db" {
  length  = 32
  special = false # RDS's Postgres engine rejects some special characters in the master password; avoiding them entirely is simpler than allow-listing which ones are safe
}

resource "aws_db_subnet_group" "main" {
  name       = "payguard-${var.environment}"
  subnet_ids = aws_subnet.private[*].id

  tags = { Name = "payguard-${var.environment}" }
}

resource "aws_db_instance" "main" {
  identifier     = "payguard-${var.environment}"
  engine         = "postgres"
  engine_version = "16"
  instance_class = var.db_instance_class

  allocated_storage     = 20
  max_allocated_storage = 100 # storage autoscaling -- avoids a manual resize being the first thing anyone has to do under real load

  db_name  = var.db_name
  username = var.db_username
  password = random_password.db.result

  db_subnet_group_name   = aws_db_subnet_group.main.name
  vpc_security_group_ids = [aws_security_group.rds.id]
  publicly_accessible    = false

  multi_az                = var.environment == "production"
  backup_retention_period = 7
  storage_encrypted       = true
  deletion_protection     = var.environment == "production"
  skip_final_snapshot     = var.environment != "production"

  tags = { Name = "payguard-${var.environment}" }
}

resource "aws_elasticache_subnet_group" "main" {
  name       = "payguard-${var.environment}"
  subnet_ids = aws_subnet.private[*].id
}

# A single cache.t4g.micro node, not a replication group -- Phase 16's
# rate limiter treats a Redis outage as "buckets reset to full," never as
# a correctness failure (packages/ratelimit's own design note: a merchant
# with no traffic costs nothing to maintain, and an empty bucket state is
# indistinguishable from a full one to the Lua script). That's exactly the
# kind of workload that doesn't need Redis's own HA story -- unlike RDS,
# where multi_az above exists because losing the ledger is a real
# incident, not a temporarily-generous rate limit.
resource "aws_elasticache_cluster" "main" {
  cluster_id         = "payguard-${var.environment}"
  engine             = "redis"
  engine_version     = "7.1"
  node_type          = var.redis_node_type
  num_cache_nodes    = 1
  port               = 6379
  subnet_group_name  = aws_elasticache_subnet_group.main.name
  security_group_ids = [aws_security_group.redis.id]

  tags = { Name = "payguard-${var.environment}" }
}
