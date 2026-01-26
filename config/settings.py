import os

from dataclasses import dataclass
from pathlib import Path

# LOGGING CONFIG
@dataclass
class LoggingConfig:
    level: str = "INFO"
    """Logging configuration"""

    level: str = "INFO"
    log_file: Path = Path("logs/github_extractor.log")
    format: str = (
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    @classmethod
    def from_env(cls) -> "LoggingConfig":
        raw_level = os.getenv("LOG_LEVEL", "INFO").upper()
        allowed_levels = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        level = raw_level if raw_level in allowed_levels else "INFO"

        return cls(
            level=level,
            log_file=Path(os.getenv("LOG_FILE", "logs/github_extractor.log"))
        )

# API CONFIG
@dataclass(frozen=True)
class APIConfig:
    """GitHub API configuration"""

    graphql_url: str = "https://api.github.com/graphql"
    rest_url: str = "https://api.github.com"
    timeout: int = 30

    max_retries: int = 3
    retry_backoff_min: float = 4.0
    retry_backoff_max: float = 30.0

    @classmethod
    def from_env(cls) -> "APIConfig":
        return cls(
            graphql_url=os.getenv(
                "GITHUB_GRAPHQL_URL",
                "https://api.github.com/graphql",
            ),
            rest_url=os.getenv(
                "GITHUB_API_URL",
                "https://api.github.com",
            ),
            timeout=int(os.getenv("API_TIMEOUT", "30")),
            max_retries=int(os.getenv("MAX_RETRIES", "3")),
            # .env configurable backoff settings
            retry_backoff_min=float(os.getenv("RETRY_BACKOFF_MIN", "4.0")),
            retry_backoff_max=float(os.getenv("RETRY_BACKOFF_MAX", "30.0")),
        )