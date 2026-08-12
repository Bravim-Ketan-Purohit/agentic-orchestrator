"""Application configuration via pydantic-settings."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Central configuration. Reads from environment / .env file."""

    # Database
    database_url: str = (
        "postgresql+asyncpg://orchestrator:orchestrator@localhost:7602/orchestrator"
    )
    database_url_sync: str = (
        "postgresql://orchestrator:orchestrator@localhost:7602/orchestrator"
    )

    # SQS
    sqs_endpoint_url: str = "http://localhost:7604"
    sqs_queue_url: str = "http://localhost:7604/000000000000/runs"
    sqs_dlq_url: str = "http://localhost:7604/000000000000/runs-dlq"
    aws_region: str = "us-east-1"
    aws_access_key_id: str = "test"
    aws_secret_access_key: str = "test"

    # SNS
    sns_endpoint_url: str = "http://localhost:7608"
    sns_topic_arn: str = "arn:aws:sns:us-east-1:000000000000:run-completions"

    # WebSocket
    ws_origin_allowlist: str = "http://localhost:7600,http://localhost:3000"
    ws_heartbeat_interval: int = 20
    ws_send_queue_max: int = 1024

    # LISTEN/NOTIFY poll fallback
    notify_poll_interval_ms: int = 300

    # OpenTelemetry
    otel_exporter_otlp_endpoint: str = "http://localhost:7607"
    otel_service_name: str = "orchestrator"
    otel_traces_sampler: str = "parentbased_traceidratio"
    otel_traces_sampler_arg: str = "0.1"
    otel_enabled: bool = False  # Enable when Jaeger is running

    # API
    api_host: str = "0.0.0.0"
    api_port: int = 7601

    model_config = {"env_file": ".env", "extra": "ignore"}

    @property
    def ws_origins(self) -> list[str]:
        return [o.strip() for o in self.ws_origin_allowlist.split(",") if o.strip()]


settings = Settings()
