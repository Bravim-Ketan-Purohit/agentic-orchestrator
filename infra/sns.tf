# SNS topic for terminal-state fan-out

resource "aws_sns_topic" "run_completions" {
  name = "${local.name_prefix}-run-completions"

  tags = {
    Name = "${local.name_prefix}-run-completions"
  }
}

# SQS subscriber for durable downstream processing
resource "aws_sqs_queue" "completions" {
  name = "${local.name_prefix}-completions"

  tags = {
    Name = "${local.name_prefix}-completions"
  }
}

resource "aws_sns_topic_subscription" "completions_sqs" {
  topic_arn = aws_sns_topic.run_completions.arn
  protocol  = "sqs"
  endpoint  = aws_sqs_queue.completions.arn

  # Filter by terminal states only
  filter_policy = jsonencode({
    state = ["succeeded", "failed", "cancelled"]
  })
}

resource "aws_sqs_queue_policy" "completions" {
  queue_url = aws_sqs_queue.completions.url
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect    = "Allow"
        Principal = { Service = "sns.amazonaws.com" }
        Action    = "sqs:SendMessage"
        Resource  = aws_sqs_queue.completions.arn
        Condition = {
          ArnEquals = {
            "aws:SourceArn" = aws_sns_topic.run_completions.arn
          }
        }
      }
    ]
  })
}
