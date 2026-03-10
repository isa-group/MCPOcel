import inspect
import logging
from pathlib import Path
import sys
from typing import Optional
from logging.handlers import RotatingFileHandler
from shared.config.logging import LoggingConfig
from shared.config.env import Env

_LOGS_DIR = Path(__file__).resolve().parent.parent.parent / "logs"

def _caller_module_name() -> str:
    """Returns the module name that imports this file outside shared/logger/."""
    logger_dir = Path(__file__).resolve().parent
    for frame_info in inspect.stack():
        filename = frame_info.filename
        # Skip frozen/internal Python frames (e.g. <frozen importlib._bootstrap>)
        if filename.startswith("<"):
            continue
        frame_path = Path(filename).resolve()
        # Skip any file inside the shared/logger package
        if frame_path.parent == logger_dir:
            continue
        module = inspect.getmodule(frame_info[0])
        if module:
            name = module.__name__
            if name not in ("__main__", "__mp_main__"):
                return name.split(".")[-1]
        return frame_path.stem
    return "app"

def setup_logging(config: Optional[LoggingConfig] = None) -> None:
    if config is None:
        config = LoggingConfig.from_env()

    # Resolve log file path lazily: caller module name is only meaningful here,
    # not at class-definition/import time.
    if config.log_file is None:
        config.log_file = Env.optional_path("LOG_FILE", _LOGS_DIR / f"{_caller_module_name()}.log")

    # Create logs directory if it doesn't exist
    config.log_file.parent.mkdir(parents=True, exist_ok=True)

    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(config.level)

    # Clean up existing handlers to prevent duplicate logs in interactive environments
    if root_logger.hasHandlers():
        for handler in root_logger.handlers[:]:
            handler.close()
            root_logger.removeHandler(handler)

    # Create formatters
    detailed_formatter = logging.Formatter(
        config.format,
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    # Simplified format for the terminal
    console_formatter = logging.Formatter(
        '%(levelname)s - %(name)s - %(message)s'
    )
    try:
        # File handler (detailed)
        # Rotates when file reaches 5MB, keeps last 5 backups
        file_handler = RotatingFileHandler(
            filename=config.log_file,
            encoding='utf-8',
            maxBytes=5 * 1024 * 1024,
            backupCount=5
        )
        file_handler.setLevel(logging.DEBUG)  # Files capture everything
        file_handler.setFormatter(detailed_formatter)
        root_logger.addHandler(file_handler)
    except Exception as e:
        print(f"Error initialising log file: {e}", file=sys.stderr)

    # Console handler (less verbose)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(config.level)
    console_handler.setFormatter(console_formatter)
    root_logger.addHandler(console_handler)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)