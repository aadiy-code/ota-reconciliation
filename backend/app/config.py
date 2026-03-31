from pydantic_settings import BaseSettings
from pydantic import ConfigDict, field_validator


class Settings(BaseSettings):
    model_config = ConfigDict(env_file=".env", extra="ignore")

    DATABASE_URL: str = "sqlite:///./ota_reconciliation.db"
    UPLOAD_DIR: str = "/tmp/ota_uploads"

    @field_validator("DATABASE_URL", mode="before")
    @classmethod
    def fix_postgres_url(cls, v: str) -> str:
        # Railway provides postgres:// but SQLAlchemy needs postgresql://
        if isinstance(v, str) and v.startswith("postgres://"):
            return v.replace("postgres://", "postgresql://", 1)
        return v
    SECRET_KEY: str = "changeme"

    # Matching thresholds
    NAME_AUTO_MATCH_THRESHOLD: float = 0.92
    NAME_MANUAL_REVIEW_THRESHOLD: float = 0.80
    AMOUNT_TOLERANCE_ABSOLUTE: float = 200.0  # INR
    AMOUNT_TOLERANCE_PERCENT: float = 0.02    # 2%
    DATE_TOLERANCE_DAYS: int = 1
    HIGH_CONFIDENCE_THRESHOLD: float = 85.0
    MANUAL_REVIEW_THRESHOLD: float = 50.0

    # AI (optional, used only for schema mapping fallback)
    ANTHROPIC_API_KEY: str = ""
    AI_SCHEMA_MAPPING_ENABLED: bool = False

    # API settings
    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8000
    FRONTEND_URL: str = "http://localhost:8501"


settings = Settings()
