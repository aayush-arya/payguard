output "alb_dns_name" {
  value       = aws_lb.main.dns_name
  description = "Point the dashboard's VITE_API_BASE_URL (or a CNAME) at this."
}

output "ecr_api_repository_url" {
  value = aws_ecr_repository.api.repository_url
}

output "ecr_worker_repository_url" {
  value = aws_ecr_repository.worker.repository_url
}

output "rds_endpoint" {
  value       = aws_db_instance.main.address
  sensitive   = false # the hostname alone isn't sensitive; the password (never output here) is what matters
  description = "For operator access (psql, a migration run) -- application containers get the full connection string from Secrets Manager instead, never from a Terraform output."
}

output "redis_endpoint" {
  value = aws_elasticache_cluster.main.cache_nodes[0].address
}
