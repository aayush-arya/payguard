data "aws_availability_zones" "available" {
  state = "available"
}

resource "aws_vpc" "main" {
  cidr_block           = var.vpc_cidr
  enable_dns_support   = true
  enable_dns_hostnames = true

  tags = {
    Name        = "payguard-${var.environment}"
    Environment = var.environment
  }
}

resource "aws_internet_gateway" "main" {
  vpc_id = aws_vpc.main.id

  tags = {
    Name = "payguard-${var.environment}"
  }
}

# Public subnets hold only the ALB and the NAT gateway -- the API/worker
# tasks and the database never get a public IP, reachable only through the
# ALB (for the API) or not at all from outside the VPC (worker, RDS,
# ElastiCache). "Public" here means "has a route to the internet gateway,"
# not "runs application code."
resource "aws_subnet" "public" {
  count                   = var.availability_zone_count
  vpc_id                  = aws_vpc.main.id
  cidr_block              = cidrsubnet(var.vpc_cidr, 8, count.index)
  availability_zone       = data.aws_availability_zones.available.names[count.index]
  map_public_ip_on_launch = true

  tags = {
    Name = "payguard-${var.environment}-public-${count.index}"
    Tier = "public"
  }
}

resource "aws_subnet" "private" {
  count             = var.availability_zone_count
  vpc_id            = aws_vpc.main.id
  cidr_block        = cidrsubnet(var.vpc_cidr, 8, count.index + var.availability_zone_count)
  availability_zone = data.aws_availability_zones.available.names[count.index]

  tags = {
    Name = "payguard-${var.environment}-private-${count.index}"
    Tier = "private"
  }
}

# One NAT gateway, not one per AZ -- a deliberate cost/availability
# tradeoff called out explicitly rather than left as an unstated
# limitation: a NAT-gateway-per-AZ setup survives a single AZ's NAT
# gateway failing, this doesn't. For reference infrastructure demonstrating
# the shape of a deployment (not sized/hardened for real production
# traffic), one NAT gateway is the right default; docs/terraform.md says
# so explicitly rather than leaving it to be discovered during an incident.
resource "aws_eip" "nat" {
  domain = "vpc"
  tags = {
    Name = "payguard-${var.environment}-nat"
  }
}

resource "aws_nat_gateway" "main" {
  allocation_id = aws_eip.nat.id
  subnet_id     = aws_subnet.public[0].id

  tags = {
    Name = "payguard-${var.environment}"
  }
  depends_on = [aws_internet_gateway.main]
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.main.id
  }

  tags = {
    Name = "payguard-${var.environment}-public"
  }
}

resource "aws_route_table" "private" {
  vpc_id = aws_vpc.main.id

  route {
    cidr_block     = "0.0.0.0/0"
    nat_gateway_id = aws_nat_gateway.main.id
  }

  tags = {
    Name = "payguard-${var.environment}-private"
  }
}

resource "aws_route_table_association" "public" {
  count          = var.availability_zone_count
  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public.id
}

resource "aws_route_table_association" "private" {
  count          = var.availability_zone_count
  subnet_id      = aws_subnet.private[count.index].id
  route_table_id = aws_route_table.private.id
}
