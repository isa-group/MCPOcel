import os
from pathlib import Path
from typing import Optional, List
from dotenv import load_dotenv

load_dotenv()

class Env:
    """
    Wrapper simple y robusto para obtener variables de entorno
    con validación, valores por defecto y conversión de tipos.
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
        try:
            return int(val)
        except ValueError:
            raise ValueError(f"Environment variable '{name}' must be an integer, got: '{val}'")

    @staticmethod
    def optional_int(name: str, default: Optional[int] = None) -> Optional[int]:
        val = os.getenv(name)
        if val is None or val.strip() == "":
            return default
        try:
            return int(val.strip())
        except ValueError:
            raise ValueError(f"Environment variable '{name}' must be an integer, got: '{val}'")

    # FLOAT
    @staticmethod
    def float(name: str, default: Optional[float] = None) -> float:
        val = os.getenv(name)
        if val is None:
            if default is None:
                raise KeyError(f"Missing required environment variable: {name}")
            return default
        try:
            return float(val)
        except ValueError:
            raise ValueError(f"Environment variable '{name}' must be a float, got: '{val}'")

    @staticmethod
    def optional_float(name: str, default: Optional[float] = None) -> Optional[float]:
        val = os.getenv(name)
        if val is None:
            return default
        try:
            return float(val)
        except ValueError:
            raise ValueError(f"Environment variable '{name}' must be a float, got: '{val}'")

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
        if val is None:
            return default
        return Env.bool(name, default)

    # LIST (CSV)
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
        if val is None:
            return default
        return [item.strip() for item in val.split(",") if item.strip()]

    # PATH
    @staticmethod
    def path(name: str, default: Optional[str] = None, must_exist: bool = False) -> Path:
        val = os.getenv(name, default)
        if val is None:
            raise KeyError(f"Missing required environment variable: {name}")

        path = Path(val).expanduser().resolve()

        if must_exist and not path.exists():
            raise FileNotFoundError(f"Path from {name} does not exist: {path}")

        return path

    @staticmethod
    def optional_path(name: str, default: Optional[str] = None) -> Optional[Path]:
        val = os.getenv(name, default)
        if val:
            return Path(val).expanduser().resolve()
        return None