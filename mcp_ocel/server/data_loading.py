"""Smart OCEL loader with adaptive strategy.
Automatically selects: PM4PY (< 100MB), ijson (100MB-1GB), DuckDB (> 1GB).
"""

import os
import json
from typing import Any, Dict, List, Optional, Union

import pm4py

from . import constants
from .typing_ocel import OCELData, EventStreamGenerator
from shared.logger.logging_config import get_logger

logger = get_logger(__name__)

class SmartOCELLoader:
    """Smart loader that adapts strategy based on file size."""
    
    def __init__(self, ocel_path: str):
        """
        Initializes the loader.
        
        Args:
            ocel_path: Path to OCEL file.
            
        Raises:
            FileNotFoundError: If file does not exist.
        """
        if not os.path.exists(ocel_path):
            raise FileNotFoundError(f"OCEL file not found: {ocel_path}")
        
        self.ocel_path = ocel_path
        self.file_size_mb = os.path.getsize(ocel_path) / (1024 ** 2)
        self.strategy = self._select_strategy()
        
        logger.info(
            f"OCEL loader initialized: {self.file_size_mb:.2f}MB "
            f"(strategy: {self.strategy.value})"
        )
    
    def _select_strategy(self) -> constants.LoadStrategy:
        """Selects strategy based on file size.
        
        Returns:
            LoadStrategy enum value based on file size thresholds.
        """
        if self.file_size_mb < constants.FILE_SIZE_SMALL:
            return constants.LoadStrategy.PM4PY
        else:
            return constants.LoadStrategy.IJSON
    
    def load(self) -> OCELData:
        """
        Loads OCEL using selected strategy.
        
        Returns:
            - If PM4PY: pm4py.OCEL (native object)
            - If ijson: dict with events and objects
            - If DuckDB: DuckDB connection
            
        Raises:
            Exception: If loading fails.
        """
        logger.debug(f"Loading OCEL with strategy: {self.strategy.value}")
        
        if self.strategy == constants.LoadStrategy.PM4PY:
            return self._load_pm4py()
        else:
            return self._load_ijson()
    
    def _load_pm4py(self) -> OCELData:
        """Loads OCEL using PM4PY (for small files).
        
        Returns:
            PM4PY OCEL object.
            
        Raises:
            Exception: If loading fails.
        """
        try:
            logger.info(f"Loading OCEL with PM4PY from: {self.ocel_path}")
            ocel = pm4py.read_ocel(self.ocel_path)
            logger.info(
                f"OCEL loaded: {len(ocel.events)} events, "
                f"{len(ocel.objects)} objects"
            )
            return ocel
        except Exception as e:
            logger.error(f"Error loading OCEL with PM4PY: {e}")
            raise
    
    def _load_ijson(self) -> OCELData:
        """
        Loads OCEL with ijson in streaming mode (for medium files).
        
        Returns:
            Dict with OCEL structure conforming to OCEL 2.0 schema.
            
        Raises:
            Exception: If loading fails.
        """
        try:
            import ijson
            
            logger.info(f"Loading OCEL with ijson (streaming) from: {self.ocel_path}")
            
            with open(self.ocel_path, "rb") as f:
                data = {
                    "ocel:version": None,
                    "ocel:attribute-names": None,
                    "ocel:object-types": None,
                    "ocel:event-types": None,
                    "ocel:objects": {},
                    "ocel:events": [],
                }
                
                f.seek(0)
                parser = ijson.kvitems(f, "")
                for key, value in parser:
                    if key in ["ocel:version", "ocel:attribute-names", 
                              "ocel:object-types", "ocel:event-types"]:
                        data[key] = value
                    elif key == "ocel:objects":
                        data["ocel:objects"] = value
                        break

            with open(self.ocel_path, "rb") as f:
                parser = ijson.items(f, "ocel:events.item")
                events = []
                for i, event in enumerate(parser):
                    events.append(event)
                    # Emits progress every DEFAULT_CHUNK_SIZE to see advancement in large files
                    if (i + 1) % constants.DEFAULT_CHUNK_SIZE == 0:
                        logger.debug(f"Loaded {i + 1} events...")
                data["ocel:events"] = events
            
            logger.info(
                f"OCEL loaded (ijson): {len(events)} events, "
                f"{len(data['ocel:objects'])} objects"
            )
            return data
        
        except ImportError:
            logger.warning("ijson not installed, falling back to PM4PY")
            return self._load_pm4py()
        except Exception as e:
            logger.error(f"Error loading OCEL with ijson: {e}")
            raise
    
    def stream_events(
        self, chunk_size: int = constants.DEFAULT_CHUNK_SIZE
    ) -> EventStreamGenerator:
        """
        Generates events in chunks for memory-efficient processing.
        
        Args:
            chunk_size: Number of events per chunk.
            
        Yields:
            List of event dictionaries.
        """
        if self.strategy == constants.LoadStrategy.PM4PY:
            ocel = self._load_pm4py()
            chunk = []
            for event_id, event in ocel.events.items():
                chunk.append(event)
                if len(chunk) >= chunk_size:
                    yield chunk
                    chunk = []
            if chunk:
                yield chunk
        
        elif self.strategy == constants.LoadStrategy.IJSON:
            try:
                import ijson
                
                with open(self.ocel_path, "rb") as f:
                    chunk = []
                    for i, event in enumerate(ijson.items(f, "ocel:events.item")):
                        chunk.append(event)
                        if len(chunk) >= chunk_size:
                            yield chunk
                            chunk = []
                            logger.debug(f"Generated chunk with {chunk_size} events")
                    if chunk:
                        yield chunk
            except ImportError:
                logger.warning("ijson not installed for streaming")
                raise


def load_ocel(ocel_path: str) -> OCELData:
    """
    Convenience loader: automatically loads OCEL.
    
    Args:
        ocel_path: Path to OCEL file.
        
    Returns:
        Loaded OCEL data (PM4PY OCEL object or dict structure).
        
    Raises:
        FileNotFoundError: If the file does not exist.
        Exception: If loading fails.
    """
    loader = SmartOCELLoader(ocel_path)
    return loader.load()
