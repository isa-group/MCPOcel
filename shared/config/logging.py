from pathlib import Path
from shared.config.env import Env


VALID_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}

class LoggingConfig:
    def __init__(self, level: str, log_file: Path, format: str):
        level_upper = level.upper()
        if level_upper not in VALID_LOG_LEVELS:
            raise ValueError(
                f"Invalid log level: {level}. "
                f"Must be one of: {', '.join(VALID_LOG_LEVELS)}"
            )

        self.level = level_upper
        self.log_file = log_file
        self.format = format

    @classmethod
    def from_env(cls) -> "LoggingConfig":
        return cls(
            level=Env.str("LOG_LEVEL", default="INFO"),
            log_file=Env.path("LOG_FILE", default="./logs/app.log"),
            format=Env.str(
                "LOG_FORMAT",
                default="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
            )
        )