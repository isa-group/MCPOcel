"""OCEL loader using PM4PY.
Loads OCEL files with PM4PY for analysis and process mining.
"""
import pm4py

from . import constants
from .typing_ocel import OCELData, EventStreamGenerator
from shared.logger.logging_config import get_logger

logger = get_logger(__name__)

class OCELLoader:
    """OCEL loader using PM4PY."""
    
    def __init__(self, ocel_path: str):
        """
        Initializes the loader.
        
        Args:
            ocel_path: Path to OCEL file.
            
        Raises:
            FileNotFoundError: If file does not exist.
        """
        import os
        if not os.path.exists(ocel_path):
            raise FileNotFoundError(f"OCEL file not found: {ocel_path}")
        
        self.ocel_path = ocel_path
        self.file_size_mb = os.path.getsize(ocel_path) / (1024 ** 2)
        
        logger.info(
            f"OCEL loader initialized: {self.file_size_mb:.2f}MB"
        )
    
    def load(self) -> OCELData:
        """
        Loads OCEL using PM4PY.
        
        Returns:
            PM4PY OCEL object.
            
        Raises:
            Exception: If loading fails.
        """
        try:
            logger.info(f"Loading OCEL with PM4PY from: {self.ocel_path}")
            ocel = pm4py.read_ocel2_json(self.ocel_path)
            logger.info(
                f"OCEL loaded: {len(ocel.events)} events, "
                f"{len(ocel.objects)} objects"
            )
            return ocel
        except Exception as e:
            logger.error(f"Error loading OCEL with PM4PY: {e}")
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
        ocel = self.load()
        chunk = []
        for _, event in ocel.events.iterrows():
            chunk.append(event.to_dict())
            if len(chunk) >= chunk_size:
                yield chunk
                chunk = []
        if chunk:
            yield chunk


def load_ocel(ocel_path: str) -> OCELData:
    """
    Convenience loader: automatically loads OCEL.
    
    Args:
        ocel_path: Path to OCEL file.
        
    Returns:
        Loaded OCEL data (PM4PY OCEL object).
        
    Raises:
        FileNotFoundError: If the file does not exist.
        Exception: If loading fails.
    """
    loader = OCELLoader(ocel_path)
    return loader.load()
