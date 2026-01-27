import logging
import sys
from pathlib import Path
from typing import Optional
from logging.handlers import RotatingFileHandler

from github2ocel.config.settings import LoggingConfig


def setup_logging(config: Optional[LoggingConfig] = None) -> logging.Logger:

    if config is None:
        config = LoggingConfig.from_env()

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
        '%(levelname)s - %(message)s'
    )

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

    # Console handler (less verbose)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(console_formatter)
    root_logger.addHandler(console_handler)

    return root_logger


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)