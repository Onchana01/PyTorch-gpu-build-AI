from functools import lru_cache
from typing import Optional, List, Set
from enum import Enum

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, SecretStr, field_validator, model_validator


class Environment(str, Enum):
    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    environment: Environment = Field(
        default=Environment.DEVELOPMENT,
        description="Application environment"
    )
    debug: bool = Field(default=False, description="Debug mode flag")
    log_level: str = Field(default="INFO", description="Logging level")

    mongodb_url: str = Field(
        default="mongodb://localhost:27017",
        description="MongoDB connection URL"
    )
    mongodb_database: str = Field(
        default="rocm_cicd",
        description="MongoDB database name"
    )
    mongodb_max_pool_size: int = Field(default=10, ge=1, le=100)
    mongodb_min_pool_size: int = Field(default=1, ge=1, le=50)

    redis_url: str = Field(
        default="redis://localhost:6379/0",
        description="Redis connection URL for caching"
    )
    redis_password: Optional[SecretStr] = Field(default=None)
    redis_ssl: bool = Field(default=False)

    github_token: Optional[SecretStr] = Field(
        default=None,
        description="GitHub API token for PR interactions"
    )
    github_webhook_secret: Optional[SecretStr] = Field(default=None)
    github_app_id: Optional[str] = Field(default=None)
    github_app_private_key: Optional[SecretStr] = Field(default=None)

    slack_webhook_url: Optional[str] = Field(default=None)
    slack_bot_token: Optional[SecretStr] = Field(default=None)

    email_smtp_host: str = Field(default="localhost")
    email_smtp_port: int = Field(default=587)
    email_smtp_user: Optional[str] = Field(default=None)
    email_smtp_password: Optional[SecretStr] = Field(default=None)
    email_from_address: str = Field(default="cicd@rocm-pytorch.local")
    email_use_tls: bool = Field(default=True)

    jwt_secret_key: SecretStr = Field(
        default=SecretStr("change-me-in-production"),
        description="Secret key for JWT token signing"
    )
    jwt_algorithm: str = Field(default="HS256")
    jwt_access_token_expire_minutes: int = Field(default=1440)

    api_host: str = Field(default="0.0.0.0")
    api_port: int = Field(default=8000)
    api_workers: int = Field(default=4)
    api_rate_limit_per_minute: int = Field(default=100)
    api_cors_origins: List[str] = Field(default=["*"])

    kubernetes_namespace: str = Field(default="rocm-cicd")
    kubernetes_service_account: str = Field(default="rocm-cicd-sa")
    kubernetes_config_path: Optional[str] = Field(default=None)

    rocm_default_version: str = Field(default="6.0")
    rocm_supported_versions: List[str] = Field(
        default=["5.6", "5.7", "6.0", "6.1"]
    )
    gpu_architectures: List[str] = Field(
        default=["gfx906", "gfx908", "gfx90a", "gfx1030"]
    )

    docker_registry: str = Field(default="docker.io")
    docker_image_prefix: str = Field(default="rocm-pytorch-cicd")
    docker_pull_policy: str = Field(default="IfNotPresent")

    build_timeout_seconds: int = Field(default=7200)
    test_timeout_seconds: int = Field(default=1800)
    max_concurrent_builds: int = Field(default=10)
    max_retry_attempts: int = Field(default=3)

    artifact_storage_type: str = Field(default="s3")
    artifact_storage_bucket: str = Field(default="rocm-cicd-artifacts")
    artifact_storage_endpoint: Optional[str] = Field(default=None)
    artifact_retention_days: int = Field(default=90)

    aws_access_key_id: Optional[SecretStr] = Field(default=None)
    aws_secret_access_key: Optional[SecretStr] = Field(default=None)
    aws_region: str = Field(default="us-east-1")

    vault_enabled: bool = Field(default=False)
    vault_url: str = Field(default="http://localhost:8200")
    vault_token: Optional[SecretStr] = Field(default=None)
    vault_mount_path: str = Field(default="secret")

    metrics_enabled: bool = Field(default=True)
    metrics_port: int = Field(default=9090)
    tracing_enabled: bool = Field(default=False)
    tracing_endpoint: Optional[str] = Field(default=None)

    sentry_dsn: Optional[str] = Field(default=None)

    encryption_key: Optional[SecretStr] = Field(default=None)

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        valid_levels = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        upper_v = v.upper()
        if upper_v not in valid_levels:
            raise ValueError(f"Invalid log level: {v}. Must be one of {valid_levels}")
        return upper_v

    @field_validator("rocm_supported_versions")
    @classmethod
    def validate_rocm_versions(cls, v: List[str]) -> List[str]:
        for version in v:
            parts = version.split(".")
            if len(parts) < 2:
                raise ValueError(f"Invalid ROCm version format: {version}")
        return v

    @model_validator(mode="after")
    def validate_production_settings(self) -> "Settings":
        if self.environment == Environment.PRODUCTION:
            if self.jwt_secret_key.get_secret_value() == "change-me-in-production":
                raise ValueError("JWT secret key must be changed in production")
            if self.debug:
                raise ValueError("Debug mode must be disabled in production")
        return self

    def get_mongodb_url(self) -> str:
        return self.mongodb_url

    def get_jwt_secret(self) -> str:
        return self.jwt_secret_key.get_secret_value()

    def is_production(self) -> bool:
        return self.environment == Environment.PRODUCTION

    def is_development(self) -> bool:
        return self.environment == Environment.DEVELOPMENT


@lru_cache()
def get_settings() -> Settings:
    return Settings()
