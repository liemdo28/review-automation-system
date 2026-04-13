from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Database
    database_url: str = "postgresql+asyncpg://reviews:reviews_dev@localhost:5432/review_system"
    database_url_sync: str = "postgresql+psycopg2://reviews:reviews_dev@localhost:5432/review_system"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # Google OAuth
    google_client_id: str = ""
    google_client_secret: str = ""
    google_refresh_token: str = ""
    google_account_id: str = ""

    # OpenAI
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    default_reply_tone: str = "gentle_professional"

    # Email
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    alert_email_to: str = ""
    alert_email_from: str = "Review Bot <noreply@example.com>"

    # App
    dry_run: bool = True
    fetch_interval_minutes: int = 10
    process_interval_minutes: int = 1
    max_retries: int = 3
    job_execution_mode: str = "inline"
    log_level: str = "INFO"
    secret_key: str = "change-this"


settings = Settings()
