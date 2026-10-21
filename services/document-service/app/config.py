"""Application configuration via pydantic-settings."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = "document-service"
    app_version: str = "0.1.0"
    debug: bool = False

    mongodb_url: str = "mongodb://localhost:27017"
    mongodb_database: str = "otterworks_documents"
    mongodb_server_selection_timeout_ms: int = 5000
    # Driver connection pool: maxPoolSize = db_pool_size + db_max_overflow.
    db_pool_size: int = 10
    db_max_overflow: int = 20

    sns_topic_arn: str = ""
    aws_endpoint_url: str = ""
    aws_region: str = "us-east-1"
    sns_enabled: bool = False

    otel_exporter_otlp_endpoint: str = "http://localhost:4318"
    otel_enabled: bool = False

    request_log_dir: str = "/var/log/otterworks/document-service"

    rollup_enabled: bool = True
    rollup_interval_seconds: int = 60

    cors_origins: list[str] = ["http://localhost:3000", "http://localhost:4200"]

    model_config = {"env_prefix": "DOC_SVC_", "env_file": ".env", "extra": "ignore"}


settings = Settings()
