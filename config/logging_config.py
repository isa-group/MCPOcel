import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

# Base directory for logs
LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True)

# Configuration from environment variables
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
LOG_FILE = LOG_DIR / "app.log"

# Formats
LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

def setup_logging():
    """
    Configures the root logger with a StreamHandler (console)
    and a RotatingFileHandler (file).
    """
    root = logging.getLogger()

    # Avoid duplicating handlers if already configured
    if root.hasHandlers():
        return

    # Root log level
    root.setLevel(LOG_LEVEL)

    # Handler for Console (cleaner)
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(logging.Formatter("%(levelname)s - %(message)s"))
    console_handler.setLevel(logging.INFO)

    # Handler for File (Detailed and Rotating)
    # 5MB per file, saves up to 5 old versions
    file_handler = RotatingFileHandler(
    LOG_FILE,
    maxBytes=5 * 1024 * 1024,
    backupCount=5,
    encoding="utf-8",)

    file_handler.setFormatter (logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT))
    file_handler.setLevel(logging.DEBUG if LOG_LEVEL == "DEBUG" else logging.INFO)

    # Add handlers to the root logger
    root.addHandler(console_handler)
    root.addHandler(file_handler)

def get_logger(name: str | None = None) -> logging.Logger:
    """
    Returns a logger instance for the specific module.
    """
    return logging.getLogger(name)
