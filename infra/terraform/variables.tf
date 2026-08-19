variable "aws_region" {
  type        = string
  default     = "us-east-1"
  description = "AWS region every resource in this module is created in."
}

variable "environment" {
  type        = string
  default     = "production"
  description = "Used in resource naming/tagging -- distinguishes stacks if this module is ever instantiated more than once (e.g. staging vs. production)."
}

variable "vpc_cidr" {
  type    = string
  default = "10.0.0.0/16"
}

variable "availability_zone_count" {
  type        = number
  default     = 2
  description = "Number of AZs to spread subnets across. 2 is the minimum for an ALB and an RDS Multi-AZ deployment to mean anything -- 1 AZ would make every 'high availability' resource here a single point of failure wearing HA's name."
}

variable "db_instance_class" {
  type        = string
  default     = "db.t4g.micro"
  description = "Deliberately a burstable/small instance class -- this is reference infrastructure for a portfolio project's traffic shape, not a sized-for-real-load production database. Resize before this ever serves real traffic."
}

variable "db_name" {
  type    = string
  default = "payguard"
}

variable "db_username" {
  type    = string
  default = "payguard"
}

variable "redis_node_type" {
  type    = string
  default = "cache.t4g.micro"
}

variable "api_image" {
  type        = string
  description = "Full ECR image URI (repository:tag) for the API container. No default -- there is no sane default image to fall back to; the caller must supply one, same reasoning as api_desired_count having a real default but this not."
}

variable "worker_image" {
  type        = string
  description = "Full ECR image URI for the worker container."
}

variable "api_desired_count" {
  type        = number
  default     = 2
  description = "Starts at 2, not 1, for the identical reason infra/kubernetes/21-api.yaml does: Phase 16's Redis-backed rate limiter is only proven correct under >1 concurrent replica if something actually runs more than one."
}

variable "worker_desired_count" {
  type    = number
  default = 2
}

variable "container_port" {
  type    = number
  default = 8000
}
