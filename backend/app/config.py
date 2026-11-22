"""Runtime configuration (env vars). See .env.example for documentation of every variable."""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    # infra
    database_url: str = "postgresql+psycopg://ec2opt:ec2opt@db:5432/ec2opt"
    redis_url: str = "redis://redis:6379/0"
    secret_key: str = "change-me-in-production-please-32-bytes-min"
    environment: str = "development"          # "production" => Secure cookies, no /docs

    # platform AWS identity (pricing + AssumeRole via IAM Role or dev keys)
    platform_aws_account_id: str = "374073888140"
    platform_principal_arn: str = "arn:aws:iam::374073888140:role/ec2opt-backend"
    platform_aws_access_key_id: str | None = None
    platform_aws_secret_access_key: str | None = None
    platform_aws_region: str = "us-east-1"
    cfn_template_url: str = "https://example-bucket.s3.amazonaws.com/cloudformation-role.yaml"
    role_name: str = "EC2OptimizerAccessRole"

    # detector runtime constants (formulas are never changed, only these inputs)
    lookback_hours: int = 336
    min_history_hours: int = 168
    apply_data_quality: bool = True

    demo_mode: bool = False
    frontend_origin: str = "http://localhost:5173"

    # behaviour knobs
    jwt_expiry_hours: int = 8
    cookie_name: str = "ec2opt_session"
    celery_eager: bool = False                 # tests: run tasks inline
    demo_step_delay_s: float = 1.0             # fake executor sleep per step
    waiter_delay_s: int = 15
    waiter_max_attempts: int = 40
    action_rate_limit_per_hour: int = 10
    login_rate_limit_per_min: int = 5
    cooldown_days: int = 7
    scan_max_workers: int = 5

    @property
    def is_production(self) -> bool:
        return self.environment.lower() == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
