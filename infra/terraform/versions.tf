# Phase 18: demonstrates the shape of a real AWS deployment -- VPC, RDS,
# ElastiCache, ECS Fargate, an ALB -- as reference infrastructure-as-code,
# not something applied against a real AWS account in this project's
# development. See docs/terraform.md for exactly what "demonstrates" means
# here versus what a team would still need to do before running
# `terraform apply` against production: real state locking, a reviewed
# IAM boundary, and someone who owns the AWS bill.

terraform {
  required_version = ">= 1.5"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }

  # S3 + DynamoDB remote state, commented rather than active: enabling this
  # requires the bucket/table to already exist (a chicken-and-egg problem
  # every real Terraform setup solves once, by hand or via a small
  # bootstrap stack) and real AWS credentials neither of which this
  # project has in its development environment. Local state is what
  # `terraform validate`/`terraform plan` below actually run against.
  #
  # backend "s3" {
  #   bucket         = "payguard-terraform-state"
  #   key            = "payguard/terraform.tfstate"
  #   region         = "us-east-1"
  #   dynamodb_table = "payguard-terraform-locks"
  #   encrypt        = true
  # }
}

provider "aws" {
  region = var.aws_region
}
