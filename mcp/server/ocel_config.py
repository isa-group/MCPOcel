"""Dynamic OCEL 2.0 schema configuration.
Automatically loads and caches schema without domain hardcoding.
"""

import json
import hashlib
import os
from dataclasses import dataclass
from typing import Dict, List, Optional
from pathlib import Path

from . import constants
from shared.logger.logging_config import get_logger

logger = get_logger(__name__)

@dataclass
class OCELConfig:
    """Dynamic OCEL schema configuration."""
    event_types: List[str]
    object_types: List[str]
    attribute_names: Dict[str, List[str]]
    
    @classmethod
    def from_ocel_json(cls, filepath: str) -> "OCELConfig":
        """
        Extracts schema from OCEL JSON file.
        
        Args:
            filepath: Path to OCEL JSON file.
            
        Returns:
            OCELConfig with extracted schema.
            
        Raises:
            FileNotFoundError: If file does not exist.
            ValueError: If JSON is not valid OCEL 2.0.
        """
        logger.debug(f"Loading OCEL configuration from: {filepath}")
        
        if not os.path.exists(filepath):
            raise FileNotFoundError(
                f"OCEL file not found: {filepath}"
            )
        
        try:
            with open(filepath, "r") as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in {filepath}: {e}")
        
        required_fields = ["ocel:event-types", "ocel:object-types", "ocel:attribute-names"]
        missing = [f for f in required_fields if f not in data]
        if missing:
            raise ValueError(
                f"Incomplete OCEL 2.0. Missing fields: {missing}"
            )
        
        event_types = data.get("ocel:event-types", [])
        object_types = data.get("ocel:object-types", [])
        attribute_names = data.get("ocel:attribute-names", {})
        
        logger.info(
            f"OCEL configuration loaded: "
            f"{len(event_types)} event types, "
            f"{len(object_types)} object types"
        )
        
        return cls(
            event_types=event_types,
            object_types=object_types,
            attribute_names=attribute_names,
        )
    
    @classmethod
    def from_env(cls, env_var: str = "OCEL_FILE") -> "OCELConfig":
        """
        Loads from environment variable.
        
        Args:
            env_var: Name of environment variable.
            
        Returns:
            OCELConfig.
            
        Raises:
            ValueError: If environment variable is not defined.
        """
        filepath = os.getenv(env_var)
        if not filepath:
            logger.warning(f"Environment variable {env_var} not defined")
            raise ValueError(f"{env_var} not defined in environment")
        
        return cls.from_ocel_json(filepath)
    
    @classmethod
    def from_param_or_env(
        cls,
        ocel_path: Optional[str] = None,
        env_var: str = "OCEL_FILE",
    ) -> "OCELConfig":
        """
        Loads with priority: parameter > environment variable > default.
        
        Args:
            ocel_path: Path to OCEL file (parameter, highest priority).
            env_var: Environment variable as fallback.
            
        Returns:
            OCELConfig.
            
        Raises:
            ValueError: If no configuration source is valid.
        """
        if ocel_path:
            logger.debug(f"Using ocel_path parameter: {ocel_path}")
            return cls.from_ocel_json(ocel_path)

        env_path = os.getenv(env_var)
        if env_path:
            logger.debug(f"Using environment variable {env_var}: {env_path}")
            return cls.from_ocel_json(env_path)

        default_path = constants.DEFAULT_OCEL_PATH
        if os.path.exists(default_path):
            logger.debug(f"Using default path: {default_path}")
            return cls.from_ocel_json(default_path)
        
        raise ValueError(
            f"No valid OCEL configuration found. "
            f"Provide ocel_path, define {env_var}, or ensure {default_path} exists."
        )
    
    def cache_key(self) -> str:
        """
        Computes cache key (SHA256) of schema.
        
        Returns:
            64-character hexadecimal key.
        """
        content = json.dumps(
            {
                "event_types": sorted(self.event_types),
                "object_types": sorted(self.object_types),
                "attribute_keys": sorted(self.attribute_names.keys()),
            },
            sort_keys=True,
        )
        return hashlib.sha256(content.encode()).hexdigest()
    
    def to_dict(self) -> Dict:
        """Converts to dictionary."""
        return {
            "event_types": self.event_types,
            "object_types": self.object_types,
            "attribute_names": self.attribute_names,
        }


class ConfigCache:
    """In-memory cache for OCEL configurations."""
    
    def __init__(self):
        self._cache: Dict[str, OCELConfig] = {}
    
    def get(self, key: str) -> Optional[OCELConfig]:
        """Gets configuration from cache."""
        return self._cache.get(key)
    
    def set(self, key: str, config: OCELConfig) -> None:
        """Stores configuration in cache."""
        self._cache[key] = config
        logger.debug(f"Configuration cached with key: {key[:8]}...")
    
    def clear(self) -> None:
        """Clears the cache."""
        self._cache.clear()
        logger.debug("Configuration cache cleared")


_config_cache = ConfigCache()


def get_cached_config(
    ocel_path: Optional[str] = None,
    use_cache: bool = True,
) -> OCELConfig:
    """
    Gets OCEL configuration, using cache if available.
    
    Args:
        ocel_path: Path to OCEL file.
        use_cache: Whether to use in-memory cache.
        
    Returns:
        Cached or new OCELConfig.
    """
    config = OCELConfig.from_param_or_env(ocel_path)
    
    if use_cache:
        key = config.cache_key()
        cached = _config_cache.get(key)
        if cached:
            logger.debug("Configuration retrieved from cache")
            return cached
        _config_cache.set(key, config)
    
    return config
