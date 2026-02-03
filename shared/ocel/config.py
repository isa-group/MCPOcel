"""Dynamic OCEL 2.0 schema configuration.

Automatically loads and caches schema without domain hardcoding.
Extracts event types, object types, and attribute names from OCEL JSON files.
"""

import json
import hashlib
import os
from dataclasses import dataclass
from typing import Dict, List, Optional

from shared.logger.logging_config import get_logger
from .constants import EVT_TYPES, OBJ_TYPES_KEY, EVENTS, OBJECTS

logger = get_logger(__name__)

# Default OCEL path constant
DEFAULT_OCEL_PATH: str = "./log.json"


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
        
        # OCEL 2.0 format with camelCase keys (eventTypes, objectTypes, events, objects)
        if EVT_TYPES not in data and OBJ_TYPES_KEY not in data:
            raise ValueError(
                f"Invalid OCEL 2.0 format. Expected keys: {EVT_TYPES}, {OBJ_TYPES_KEY}, {EVENTS}, {OBJECTS}"
            )
        
        event_types_data = data.get(EVT_TYPES, [])
        object_types_data = data.get(OBJ_TYPES_KEY, [])
        
        # Extract event type names from the structure
        if event_types_data and isinstance(event_types_data[0], dict):
            event_types = [et.get("name", "") for et in event_types_data if et.get("name")]
        else:
            event_types = event_types_data
        
        # Extract object type names from the structure
        if object_types_data and isinstance(object_types_data[0], dict):
            object_types = [ot.get("name", "") for ot in object_types_data if ot.get("name")]
        else:
            object_types = object_types_data
        
        # Build attribute names from event types and object types
        attribute_names: Dict[str, List[str]] = {}
        for et in event_types_data:
            if isinstance(et, dict) and "attributes" in et:
                attr_list = [a.get("name", "") for a in et.get("attributes", []) if isinstance(a, dict)]
                if attr_list:
                    attribute_names[et.get("name", "")] = attr_list
        for ot in object_types_data:
            if isinstance(ot, dict) and "attributes" in ot:
                attr_list = [a.get("name", "") for a in ot.get("attributes", []) if isinstance(a, dict)]
                if attr_list:
                    attribute_names[ot.get("name", "")] = attr_list
        
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
        env_var: str = "OCEL_FILE"
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
        
        raise ValueError(
            f"No valid OCEL configuration found. "
            f"Provide ocel_path or define {env_var}"
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
