"""Centralized logging for OCEL MCP Server.
"""

import logging
import sys
from typing import Optional

_logger: Optional[logging.Logger] = None


def get_logger(name: str = "ocel_mcp_server", level: str = "INFO") -> logging.Logger:
    """
    Gets or creates the centralized logger.
    
    Args:
        name: Logger name.
        level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL).
    
    Returns:
        Configured logger.
    """
    global _logger
    
    if _logger is not None:
        return _logger
    
    _logger = logging.getLogger(name)
    _logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    
    handler = logging.StreamHandler(sys.stderr)
    handler.setLevel(getattr(logging, level.upper(), logging.INFO))
    
    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    handler.setFormatter(formatter)
    
    _logger.addHandler(handler)
    
    return _logger


def set_log_level(level: str) -> None:
    """Changes logging level at runtime."""
    global _logger
    if _logger is None:
        _logger = get_logger()
    
    level_obj = getattr(logging, level.upper(), logging.INFO)
    _logger.setLevel(level_obj)
    
    for handler in _logger.handlers:
        handler.setLevel(level_obj)


def debug(msg: str, *args, **kwargs) -> None:
    """DEBUG level log helper."""
    get_logger().debug(msg, *args, **kwargs)


def info(msg: str, *args, **kwargs) -> None:
    """INFO level log helper."""
    get_logger().info(msg, *args, **kwargs)


def warning(msg: str, *args, **kwargs) -> None:
    """WARNING level log helper."""
    get_logger().warning(msg, *args, **kwargs)


def error(msg: str, *args, **kwargs) -> None:
    """ERROR level log helper."""
    get_logger().error(msg, *args, **kwargs)


def critical(msg: str, *args, **kwargs) -> None:
    """CRITICAL level log helper."""
    get_logger().critical(msg, *args, **kwargs)
