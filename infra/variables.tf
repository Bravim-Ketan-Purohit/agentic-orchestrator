variable "aws_region" {
  description = "AWS region"
  type        = string
  default     = "us-east-1"
}

variable "environment" {
  description = "Environment name"
  type        = string
  default     = "dev"
}

variable "api_image" {
  description = "Docker image for the API service"
  type        = string
  default     = ""
}

variable "worker_image" {
  description = "Docker image for the worker service"
  type        = string
  default     = ""
}

variable "api_desired_count" {
  description = "Desired number of API tasks"
  type        = number
  default     = 2
}

variable "worker_desired_count" {
  description = "Desired number of worker tasks"
  type        = number
  default     = 2
}

variable "api_cpu" {
  description = "CPU units for API task (1024 = 1 vCPU)"
  type        = number
  default     = 512
}

variable "api_memory" {
  description = "Memory MiB for API task"
  type        = number
  default     = 1024
}

variable "worker_cpu" {
  description = "CPU units for worker task"
  type        = number
  default     = 512
}

variable "worker_memory" {
  description = "Memory MiB for worker task"
  type        = number
  default     = 1024
}

variable "db_instance_class" {
  description = "RDS instance class"
  type        = string
  default     = "db.t4g.micro"
}

variable "db_password" {
  description = "Database password"
  type        = string
  sensitive   = true
  default     = ""
}

variable "ws_heartbeat_interval" {
  description = "WebSocket heartbeat interval in seconds"
  type        = number
  default     = 20
}

variable "alb_idle_timeout" {
  description = "ALB idle timeout in seconds. MUST exceed WS heartbeat interval."
  type        = number
  default     = 60
}
