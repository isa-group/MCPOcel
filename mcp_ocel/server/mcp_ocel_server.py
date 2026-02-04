"""
OCEL MCP Server - SDK v1 Implementation.

Server lifecycle, state management, and initialization.
Tools are registered from the tools module.
"""

import os
import threading
from typing import Any, Dict, Optional, Type
from contextlib import asynccontextmanager

from mcp.server.fastmcp import FastMCP

from . import constants
from shared.ocel.config import get_cached_config
from shared.ocel.converter import ocel_to_dict
from shared.logger.logging_config import get_logger, setup_logging
from shared.lifecycle import register_shutdown_callback, install_signal_handlers
from .data_loading import OCELLoader
from .ocel_query_engine import OCELQueryEngine
from .process_mining import ProcessMiningEngine
from .visualization_engine import VisualizationEngine
from .tools import register_tools

# Lazy import for retrieval engine (optional dependency)
_retrieval_engine = None

logger = get_logger(__name__)


def _get_retrieval_engine() -> Optional[Type[Any]]:
    """Load the adaptive retrieval engine (SQLite FTS5 + BM25).
    
    Returns:
        The OCELRetrievalEngine class if available, False if import failed.
    """
    global _retrieval_engine
    if _retrieval_engine is None:
        try:
            from .retrieval import OCELRetrievalEngine
            _retrieval_engine = OCELRetrievalEngine
            logger.info("Adaptive retrieval engine loaded (SQLite FTS5 + BM25)")
        except ImportError as e:
            logger.warning(f"Retrieval engine not available: {e}")
            _retrieval_engine = False
    return _retrieval_engine


# Global state for OCEL data (initialized once at server startup, shared across all client sessions)
# With streamable-http transport, multiple clients connect via different sessions but all share
# the same _ocel_state for memory efficiency and index reuse.
_ocel_state: Dict[str, Any] = {}

# Lock for synchronizing concurrent access to critical sections (e.g., retrieval engine indexing)
_ocel_lock = threading.RLock()

# Flag to track if OCEL has been initialized
_ocel_initialized = False

def _cleanup_resources() -> None:
    """
    Cleanup and close all OCEL resources gracefully.
    
    This function is called during server shutdown to ensure:
    - Retrieval engine (SQLite) connections are properly closed
    - All data structures are cleaned up
    - Logging is flushed
    """
    global _ocel_state
    
    logger.info("Starting OCEL resource cleanup...")
    
    with _ocel_lock:
        try:
            if retrieval_engine := _ocel_state.get("retrieval_engine"):
                try:
                    if hasattr(retrieval_engine, "close"):
                        retrieval_engine.close()
                    logger.info("Retrieval engine closed")
                except Exception as e:
                    logger.warning(f"Error closing retrieval engine: {e}")

            _ocel_state.clear()
            logger.info("OCEL state cleared")
            
        except Exception as e:
            logger.error(f"Error during cleanup: {e}")


def _initialize_ocel_state(ocel_path: str, debug: bool = False) -> None:
    """
    Initialize OCEL state (load data, create engines, index for search).
    
    This function populates _ocel_state with all necessary components.
    Called once at server startup, either by lifespan or eager initialization.
    
    Args:
        ocel_path: Path to the OCEL file.
        debug: Enable debug logging.
    """
    global _ocel_initialized
    
    if _ocel_initialized:
        logger.info("OCEL already initialized, skipping...")
        return
    
    from shared.logger.logging_config import LoggingConfig
    
    level = "DEBUG" if debug else "INFO"
    config = LoggingConfig(level=level)
    setup_logging(config)
    
    logger.info(f"Initializing OCEL MCP Server with {ocel_path}")
    
    # Load OCEL and configuration
    ocel_config = get_cached_config(ocel_path)
    loader = OCELLoader(ocel_path)
    ocel_data = loader.load()
    
    # Initialize engines
    query_engine = OCELQueryEngine(ocel_data)
    mining_engine = ProcessMiningEngine(ocel_data)
    viz_engine = VisualizationEngine(ocel_data, mining_engine)
    
    # Initialize retrieval engine (adaptive: SQLite FTS5 / Hybrid / BM25)
    retrieval_engine = None
    RetrievalClass = _get_retrieval_engine()
    if RetrievalClass and RetrievalClass is not False:
        try:
            with _ocel_lock:
                retrieval_engine = RetrievalClass()
                ocel_dict = ocel_to_dict(ocel_data, ocel_config)
                num_chunks = retrieval_engine.index_ocel(ocel_dict)
                info = retrieval_engine.get_info()
                logger.info(
                    f"OCEL indexed with {info['strategy'].upper()} strategy - "
                    f"{num_chunks} chunks - {info['ocel_size_mb']}MB"
                )
        except Exception as e:
            logger.warning(f"Failed to initialize retrieval engine: {e}")
    
    # Store in global state
    _ocel_state["config"] = ocel_config
    _ocel_state["ocel_data"] = ocel_data
    _ocel_state["ocel_path"] = ocel_path
    _ocel_state["query_engine"] = query_engine
    _ocel_state["mining_engine"] = mining_engine
    _ocel_state["viz_engine"] = viz_engine
    _ocel_state["retrieval_engine"] = retrieval_engine
    
    _ocel_initialized = True
    
    logger.info(
        f"Server ready: {len(ocel_config.event_types)} event types, "
        f"{len(ocel_config.object_types)} object types"
    )


@asynccontextmanager
async def ocel_lifespan(_app: FastMCP):
    """
    Initialize OCEL resources when the server starts.
    This runs once when the server boots up.
    
    Args:
        app: The FastMCP server instance (required by FastMCP lifespan interface).
    """
    ocel_path = os.getenv("OCEL_FILE", constants.DEFAULT_OCEL_PATH)
    debug = os.getenv("OCEL_DEBUG", "false").lower() == "true"
    
    try:
        _initialize_ocel_state(ocel_path, debug)
        yield
        
    except Exception as e:
        logger.error(f"Error initializing server: {e}")
        raise
    finally:
        _cleanup_resources()


# Create the MCP server with lifespan
mcp = FastMCP(
    name=constants.MCP_IMPLEMENTATION_NAME,
    lifespan=ocel_lifespan,
)

# Register all tools and resources from the tools module
register_tools(mcp, _ocel_state, _ocel_lock)

# ============================================================================
# Server initialization functions
# ============================================================================

def _initialize_ocel_eager(ocel_path: Optional[str] = None, debug: bool = False) -> None:
    """
    Eagerly initialize OCEL data at server startup (before accepting client connections).
    
    This function ensures:
    - OCEL is loaded exactly ONCE, not per client session
    - All query engines and indices are initialized before FastMCP starts
    - Multiple clients share the same _ocel_state (memory efficient, index reuse)
    - Fail-fast: if OCEL file is missing or invalid, server fails at startup
    
    Called by run_server() before mcp.run(), ensuring eager-loading instead of lazy-loading.
    
    Args:
        ocel_path: Path to OCEL file (uses env var if not provided).
        debug: Enable debug logging.
    """
    logger.info("Starting eager OCEL initialization...")
    
    path = ocel_path or os.getenv("OCEL_FILE", constants.DEFAULT_OCEL_PATH)
    
    try:
        _initialize_ocel_state(path, debug)
        logger.info("Eager initialization complete - OCEL ready for client connections")
    except Exception as e:
        logger.error(f"Eager initialization failed: {e}")
        raise


# ============================================================================
# Server runner functions
# ============================================================================

def run_server(
    host: str = "127.0.0.1",
    port: int = 8000,
    ocel_path: Optional[str] = None,
    debug: bool = False,
    transport: str = "streamable-http",
) -> None:
    """
    Run the MCP server with eager OCEL initialization.
    
    Architecture:
    - Eagerly loads OCEL at startup (before listening for connections)
    - All client sessions share the same _ocel_state for efficiency
    - Synchronized access prevents race conditions with threading.RLock()
    - Graceful shutdown via registered cleanup callback and signal handlers
    
    Args:
        host: Host to bind (default: 127.0.0.1)
        port: HTTP port (default: 8000)
        ocel_path: Path to OCEL file
        debug: Enable debug logging
        transport: Transport mode: 'streamable-http', 'sse', or 'stdio'
    """
    if ocel_path:
        os.environ["OCEL_FILE"] = ocel_path
    if debug:
        os.environ["OCEL_DEBUG"] = "true"
    
    mcp.settings.host = host
    mcp.settings.port = port
    
    # Register cleanup callback with the global shutdown manager BEFORE initializing OCEL
    register_shutdown_callback(_cleanup_resources)
    
    # Install signal handlers (must be called from main thread)
    install_signal_handlers()
    
    # Initialize OCEL BEFORE starting the server. This ensures:
    # 1. Fail-fast if file is missing or invalid
    # 2. All client connections share the same _ocel_state
    try:
        logger.info("Initializing OCEL before server startup...")
        _initialize_ocel_eager(ocel_path, debug)
    except Exception as e:
        logger.error(f"Failed to initialize OCEL. Server will not start: {e}")
        raise
    
    try:
        if transport == "stdio":
            print(f"Starting MCP Server in STDIO mode")
            print(f"OCEL file: {os.getenv('OCEL_FILE', constants.DEFAULT_OCEL_PATH)}")
            mcp.run(transport="stdio")
        else:
            print(f"Starting MCP Server on http://{host}:{port}/mcp")
            print(f"OCEL file: {os.getenv('OCEL_FILE', constants.DEFAULT_OCEL_PATH)}")
            mcp.run(transport=transport)
    except KeyboardInterrupt:
        logger.info("KeyboardInterrupt caught, initiating graceful shutdown...")
        _cleanup_resources()
    except Exception as e:
        logger.error(f"Server error: {e}")
        _cleanup_resources()
