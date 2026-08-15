# SQS queue + DLQ with redrive policy

resource "aws_sqs_queue" "dlq" {
  name                      = "${local.name_prefix}-runs-dlq"
  message_retention_seconds = 1209600 # 14 days

  tags = {
    Name = "${local.name_prefix}-runs-dlq"
  }
}

resource "aws_sqs_queue" "runs" {
  name                       = "${local.name_prefix}-runs"
  visibility_timeout_seconds = 60
  receive_wait_time_seconds  = 20
  message_retention_seconds  = 86400 # 1 day

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.dlq.arn
    maxReceiveCount     = 3
  })

  tags = {
    Name = "${local.name_prefix}-runs"
  }
}
