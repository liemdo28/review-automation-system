from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Database
    database_url: str = "postgresql+asyncpg://reviews:reviews_dev@localhost:5432/review_system"
    database_url_sync: str = "postgresql+psycopg2://reviews:reviews_dev@localhost:5432/review_system"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # OpenAI
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    default_reply_tone: str = "gentle_professional"

    # Web collector sessions
    session_storage_dir: str = ".sessions"
    google_browser_proxy: str = ""
    yelp_browser_proxy: str = ""
    google_login_url: str = "https://www.google.com/"
    yelp_login_url: str = "https://biz.yelp.com/login"
    review_browser_locale: str = "en-US"
    review_browser_timezone: str = "America/Los_Angeles"
    ui_posting_headless: bool = False
    ui_posting_artifact_dir: str = ".run/ui-posting"
    ui_posting_match_threshold: float = 0.78
    ui_posting_match_margin: float = 0.08

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
