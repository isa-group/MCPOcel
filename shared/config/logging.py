from pathlib import Path
from shared.config.env import Env


VALID_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}

class LoggingConfig:
    def __init__(
            self,
            level: str,
            log_file: str | None = None,
            format: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        ):
        level_upper = level.upper()
        if level_upper not in VALID_LOG_LEVELS:
            raise ValueError(
                f"Invalid log level: {level}. "
                f"Must be one of: {', '.join(VALID_LOG_LEVELS)}"
            )

        self.level = level_upper
        # log_file=None means it will be resolved lazily in setup_logging()
        self.log_file = log_file
        self.format = format

        if self.log_file is not None and not self.log_file.parent.exists():
            self.log_file.parent.mkdir(parents=True, exist_ok=True)

    @classmethod
    def from_env(cls) -> "LoggingConfig":
        return cls(
            level=Env.str("LOG_LEVEL", default="INFO"),
            # None when LOG_FILE is not set → setup_logging() resolves via caller name
            log_file=Env.optional_path("LOG_FILE"),
            format=Env.str("LOG_FORMAT")
        )
