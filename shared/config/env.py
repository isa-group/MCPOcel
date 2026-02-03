import os
from pathlib import Path
from typing import Optional, List, Callable

def load_env(env_file: Path = Path(".env")) -> None:
    """
    Loads variables from .env without external dependencies.
    Does not overwrite variables already defined.
    """
    if not env_file.exists():
        return

    with env_file.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()

            if not line or line.startswith("#") or "=" not in line:
                continue

            key, value = line.split("=", 1)
            key, value = key.strip(), value.strip()

            # Only define if it does not exist in the system
            if key not in os.environ:
                os.environ[key] = value


# Read env utility
class Env:
    """
    Simple and robust wrapper for obtaining environment variables
    with validation, defaults, and conversions.
    """

    # STRING
    @staticmethod
    def str(name: str, default: Optional[str] = None) -> str:
        val = os.getenv(name, default)
        if val is None:
            raise KeyError(f"Missing required environment variable: {name}")
        return val

    @staticmethod
    def optional_str(name: str, default: Optional[str] = None) -> Optional[str]:
        return os.getenv(name, default)

    # INTEGER
    @staticmethod
    def int(name: str, default: Optional[int] = None) -> int:
        val = os.getenv(name)
        if val is None:
            if default is None:
                raise KeyError(f"Missing required environment variable: {name}")
            return default
        return int(val)

    @staticmethod
    def optional_int(name: str, default: Optional[int] = None) -> Optional[int]:
        val = os.getenv(name)
        return int(val) if val is not None else default

    # FLOAT
    @staticmethod
    def float(name: str, default: Optional[float] = None) -> float:
        val = os.getenv(name)
        if val is None:
            if default is None:
                raise KeyError(f"Missing required environment variable: {name}")
            return default
        return float(val)

    @staticmethod
    def optional_float(name: str, default: Optional[float] = None) -> Optional[float]:
        val = os.getenv(name)
        return float(val) if val else default

    # BOOLEAN
    TRUE_VALUES = {"1", "true", "yes", "on", "y", "t"}
    FALSE_VALUES = {"0", "false", "no", "off", "n", "f"}

    @staticmethod
    def bool(name: str, default: Optional[bool] = None) -> bool:
        val = os.getenv(name)
        if val is None:
            if default is None:
                raise KeyError(f"Missing required environment variable: {name}")
            return default

        val_lower = val.strip().lower()
        if val_lower in Env.TRUE_VALUES:
            return True
        if val_lower in Env.FALSE_VALUES:
            return False
        raise ValueError(f"Invalid boolean for {name}: {val}")

    @staticmethod
    def optional_bool(name: str, default: Optional[bool] = None) -> Optional[bool]:
        val = os.getenv(name)
        return Env.bool(name, default) if val is not None else default

    # List CSV
    @staticmethod
    def list(name: str, default: Optional[List[str]] = None) -> List[str]:
        val = os.getenv(name)
        if val is None:
            if default is None:
                raise KeyError(f"Missing required environment variable: {name}")
            return default
        return [item.strip() for item in val.split(",") if item.strip()]

    @staticmethod
    def optional_list(name: str, default: Optional[List[str]] = None) -> Optional[List[str]]:
        val = os.getenv(name)
        return [item.strip() for item in val.split(",")] if val else default

    # PATH
    @staticmethod
    def path(name: str, default: Optional[str] = None, must_exist: bool = False) -> Path:
        """
        Get a path from environment variable.

        Args:
            name: Environment variable name
            default: Default value if not found
            must_exist: If True, validates that path exists
        """
        val = os.getenv(name, default)
        if val is None:
            raise KeyError(f"Missing required environment variable: {name}")

        path = Path(val).expanduser().resolve()

        if must_exist and not path.exists():
            raise FileNotFoundError(f"Path from {name} does not exist: {path}")

        return path

    @staticmethod
    def optional_path(name: str, default: Optional[str] = None) -> Optional[Path]:
        val = os.getenv(name)
        return Path(val) if val else (Path(default) if default else None)
