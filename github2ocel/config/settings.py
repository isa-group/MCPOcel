import os
from typing import Optional
from dataclasses import dataclass

BASE_DIR = Path(__file__).resolve().parent.parent.parent

# LOGGING CONFIG
@dataclass
class LoggingConfig:
    level: str = "INFO"
    """Logging configuration"""
    log_file: Path = BASE_DIR / "logs" / "extractor.log"
    format: str = (
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    @classmethod
    def from_env(cls) -> "LoggingConfig":
        raw_level = os.getenv("LOG_LEVEL", "INFO").upper()
        allowed_levels = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        level = raw_level if raw_level in allowed_levels else "INFO"

        env_log_path = os.getenv("LOG_FILE", "logs/github_extractor.log")
        log_file = BASE_DIR / env_log_path

        return cls(
            level=level,
            log_file=log_file
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
    max_pages: Optional[int] = None

    @classmethod
    def from_env(cls) -> "APIConfig":
        try:
            raw_pages = int(os.getenv("GITHUB_MAX_PAGES", "0"))
            max_pages = raw_pages if raw_pages > 0 else None
        except ValueError:
            max_pages = None

        return cls(
            max_pages=max_pages,
            graphql_url=os.getenv("GITHUB_GRAPHQL_URL", "https://api.github.com/graphql"),
            rest_url=os.getenv("GITHUB_API_URL", "https://api.github.com"),
            timeout=int(os.getenv("API_TIMEOUT", "30")),
            max_retries=int(os.getenv("MAX_RETRIES", "3")),
            retry_backoff_min=float(os.getenv("RETRY_BACKOFF_MIN", "4.0")),
            retry_backoff_max=float(os.getenv("RETRY_BACKOFF_MAX", "30.0")),
        )
