resource "aws_ecs_cluster" "main" {
  name = "payguard-${var.environment}"

  setting {
    name  = "containerInsights"
    value = "enabled"
  }
}

resource "aws_ecr_repository" "api" {
  name                 = "payguard-api"
  image_tag_mutability = "IMMUTABLE" # a tag, once pushed, always points at the same image -- "deploy the v1.2.3 image" should never quietly mean something different than it did yesterday
}

resource "aws_ecr_repository" "worker" {
  name                 = "payguard-worker"
  image_tag_mutability = "IMMUTABLE"
}

resource "aws_iam_role" "ecs_execution" {
  name = "payguard-${var.environment}-ecs-execution"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy_attachment" "ecs_execution" {
  role       = aws_iam_role.ecs_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

# A second, narrower policy for the one thing the base execution role
# doesn't grant: permission to actually read the three secrets these tasks
# need at start. Scoped to exactly those three ARNs, not "secretsmanager:*"
# on "*" -- the same narrowest-correct-scope instinct as the security
# groups above, applied to IAM instead of network ACLs.
resource "aws_iam_role_policy" "ecs_execution_secrets" {
  name = "payguard-${var.environment}-read-secrets"
  role = aws_iam_role.ecs_execution.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = ["secretsmanager:GetSecretValue"]
      Resource = [
        aws_secretsmanager_secret.database_url.arn,
        aws_secretsmanager_secret.redis_url.arn,
        aws_secretsmanager_secret.webhook_secret.arn,
      ]
    }]
  })
}

resource "aws_cloudwatch_log_group" "api" {
  name              = "/ecs/payguard-${var.environment}-api"
  retention_in_days = 30
}

resource "aws_cloudwatch_log_group" "worker" {
  name              = "/ecs/payguard-${var.environment}-worker"
  retention_in_days = 30
}

resource "aws_ecs_task_definition" "api" {
  family                   = "payguard-${var.environment}-api"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 512
  memory                   = 1024
  execution_role_arn       = aws_iam_role.ecs_execution.arn

  container_definitions = jsonencode([{
    name         = "api"
    image        = var.api_image
    portMappings = [{ containerPort = var.container_port, protocol = "tcp" }]
    environment = [
      { name = "RATE_LIMIT_CAPACITY", value = "20" },
      { name = "RATE_LIMIT_REFILL_PER_SECOND", value = "5" },
    ]
    secrets = [
      { name = "DATABASE_URL", valueFrom = aws_secretsmanager_secret.database_url.arn },
      { name = "REDIS_URL", valueFrom = aws_secretsmanager_secret.redis_url.arn },
      { name = "WEBHOOK_SECRET", valueFrom = aws_secretsmanager_secret.webhook_secret.arn },
    ]
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.api.name
        "awslogs-region"        = var.aws_region
        "awslogs-stream-prefix" = "api"
      }
    }
  }])
}

resource "aws_ecs_task_definition" "worker" {
  family                   = "payguard-${var.environment}-worker"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 256
  memory                   = 512
  execution_role_arn       = aws_iam_role.ecs_execution.arn

  container_definitions = jsonencode([{
    name  = "worker"
    image = var.worker_image
    secrets = [
      { name = "DATABASE_URL", valueFrom = aws_secretsmanager_secret.database_url.arn },
    ]
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.worker.name
        "awslogs-region"        = var.aws_region
        "awslogs-stream-prefix" = "worker"
      }
    }
  }])
}

resource "aws_lb" "main" {
  name               = "payguard-${var.environment}"
  internal           = false
  load_balancer_type = "application"
  security_groups    = [aws_security_group.alb.id]
  subnets            = aws_subnet.public[*].id
}

resource "aws_lb_target_group" "api" {
  name        = "payguard-${var.environment}-api"
  port        = var.container_port
  protocol    = "HTTP"
  vpc_id      = aws_vpc.main.id
  target_type = "ip" # required for awsvpc network mode -- Fargate tasks don't have a stable EC2 instance to register as a target

  health_check {
    path                = "/v1/health"
    healthy_threshold   = 2
    unhealthy_threshold = 3
    interval            = 15
    timeout             = 5
  }
}

resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.main.arn
  port              = 80
  protocol          = "HTTP"
  # Plaintext HTTP on purpose here -- ACM certificate provisioning needs a
  # real domain this reference module doesn't own. A production listener
  # would be port 443 with an ACM cert and a redirect rule from 80 to 443,
  # not this.

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.api.arn
  }
}

resource "aws_ecs_service" "api" {
  name            = "payguard-${var.environment}-api"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.api.arn
  desired_count   = var.api_desired_count
  launch_type     = "FARGATE"

  network_configuration {
    subnets         = aws_subnet.private[*].id
    security_groups = [aws_security_group.ecs_api.id]
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.api.arn
    container_name   = "api"
    container_port   = var.container_port
  }

  depends_on = [aws_lb_listener.http]
}

resource "aws_ecs_service" "worker" {
  name            = "payguard-${var.environment}-worker"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.worker.arn
  desired_count   = var.worker_desired_count
  launch_type     = "FARGATE"
  # No load_balancer block -- same "nothing calls the worker over the
  # network" reasoning as its security group and the Kubernetes Deployment
  # it mirrors.

  network_configuration {
    subnets         = aws_subnet.private[*].id
    security_groups = [aws_security_group.ecs_worker.id]
  }
}

resource "aws_appautoscaling_target" "api" {
  max_capacity       = 10
  min_capacity       = var.api_desired_count
  resource_id        = "service/${aws_ecs_cluster.main.name}/${aws_ecs_service.api.name}"
  scalable_dimension = "ecs:service:DesiredCount"
  service_namespace  = "ecs"
}

# CPU-target scaling, same choice and same caveat as infra/kubernetes/21-api.yaml's
# HPA: this system's per-request cost is dominated by sequential database
# round trips (docs/load-testing.md), not CPU, but CPU-target scaling needs
# no extra metrics pipeline to work at all -- a reasonable first pass, not
# the final word on autoscaling policy.
resource "aws_appautoscaling_policy" "api_cpu" {
  name               = "payguard-${var.environment}-api-cpu"
  policy_type        = "TargetTrackingScaling"
  resource_id        = aws_appautoscaling_target.api.resource_id
  scalable_dimension = aws_appautoscaling_target.api.scalable_dimension
  service_namespace  = aws_appautoscaling_target.api.service_namespace

  target_tracking_scaling_policy_configuration {
    predefined_metric_specification {
      predefined_metric_type = "ECSServiceAverageCPUUtilization"
    }
    target_value = 70
  }
}
