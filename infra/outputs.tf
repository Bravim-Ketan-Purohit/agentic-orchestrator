output "alb_dns_name" {
  description = "ALB DNS name for the API"
  value       = aws_lb.api.dns_name
}

output "sqs_queue_url" {
  description = "SQS queue URL for runs"
  value       = aws_sqs_queue.runs.url
}

output "sqs_dlq_url" {
  description = "SQS DLQ URL"
  value       = aws_sqs_queue.dlq.url
}

output "rds_endpoint" {
  description = "RDS endpoint"
  value       = aws_db_instance.main.endpoint
}

output "sns_topic_arn" {
  description = "SNS topic ARN for run completions"
  value       = aws_sns_topic.run_completions.arn
}

output "ecs_cluster_name" {
  description = "ECS cluster name"
  value       = aws_ecs_cluster.main.name
}
