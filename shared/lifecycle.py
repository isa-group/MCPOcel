"""
Application lifecycle management: signal handling and graceful shutdown.

This module provides centralized shutdown management for both sync and async contexts,
allowing registration of cleanup callbacks and installation of OS signal handlers.
"""

import logging
import sys
import signal
import asyncio
import threading
from typing import Optional, Callable, Any, Iterable, List

logger = logging.getLogger(__name__)


class ShutdownManager:
    """
    Centralized management of graceful shutdown for both sync and async contexts.
    
    Allows registration of cleanup callbacks (sync or async), installation of OS signal
    handlers (SIGINT, SIGTERM, SIGHUP, SIGQUIT, SIGABRT), and triggering shutdown
    programmatically or via OS signals.
    
    **Important:** Signal handlers must be installed from the main thread only.
    Attempting to install from other threads will log a warning and fail silently.
    
    **Platform notes:**
    - Windows: SIGHUP and SIGQUIT are not available; the manager will safely skip them.
    - Unix/Linux: SIGHUP, SIGQUIT, SIGABRT, SIGINT, SIGTERM are all supported.
    
    **Cleanup philosophy:**
    - Callbacks should ONLY dispose of existing resources, never create new ones.
    - During shutdown, if async callbacks need an event loop, they are skipped gracefully.
    - No new resources (event loops, connections, etc.) are created during shutdown.
    
    Example (sync context):
        manager = ShutdownManager()
        manager.register_callback(lambda: print("Cleaning up..."))
        manager.install_signal_handlers()
        # When Ctrl+C is pressed or SIGTERM is sent, callbacks execute and process exits.
    
    Example (async context):
        manager = ShutdownManager()
        manager.register_callback(async_cleanup_coro)
        manager.install_signal_handlers()
        # Async callbacks are awaited if an event loop is running (best-effort).
    """
    
    def __init__(self):
        """Initialize the shutdown manager."""
        self._callbacks: List[Callable[..., Any]] = []
        self._lock = threading.Lock()
        self._shutdown_called = False
    
    def register_callback(self, callback: Callable[..., Any]) -> None:
        """
        Register a cleanup callback (sync or async).
        
        Callbacks are executed in registration order. If a callback raises an exception,
        it is logged and execution continues with the next callback.
        
        Args:
            callback: A callable (function or coroutine function) to invoke during shutdown.
                     Should NOT create new resources, only dispose/close existing ones.
        """
        with self._lock:
            self._callbacks.append(callback)
            callback_name = callback.__name__ if hasattr(callback, '__name__') else str(callback)
            logger.debug(f"Registered shutdown callback: {callback_name}")
    
    def install_signal_handlers(self, signals_list: Optional[Iterable[int]] = None) -> None:
        """
        Install OS signal handlers for graceful shutdown.
        
        By default, installs handlers for SIGINT, SIGTERM, and (on Unix) SIGHUP, SIGQUIT, SIGABRT.
        Can be customized by passing a list of signal numbers.
        
        **Must be called from the main thread.**
        
        Args:
            signals_list: Optional list of signal numbers to handle. If None, defaults to
                         [SIGINT, SIGTERM] + [SIGHUP, SIGQUIT, SIGABRT] on Unix systems.
        
        Returns:
            None
        """
        # Check if called from main thread
        if threading.current_thread() != threading.main_thread():
            logger.warning("Signal handlers must be installed from the main thread; skipping.")
            return
        
        if signals_list is None:
            signals_list = [signal.SIGINT, signal.SIGTERM]
            # Add Unix-specific signals if available
            if hasattr(signal, 'SIGHUP'):
                signals_list.append(signal.SIGHUP)
            if hasattr(signal, 'SIGQUIT'):
                signals_list.append(signal.SIGQUIT)
            if hasattr(signal, 'SIGABRT'):
                signals_list.append(signal.SIGABRT)
        
        for sig in signals_list:
            if not hasattr(signal, 'signal'):
                continue
            
            try:
                signal.signal(sig, self._signal_handler)
                signal_name = signal.Signals(sig).name if hasattr(signal, 'Signals') else str(sig)
                logger.debug(f"Registered signal handler for {signal_name} ({sig})")
            except (ValueError, OSError, AttributeError) as e:
                # ValueError: signal only works in main thread (already checked)
                # OSError: signal not supported on this platform
                signal_name = signal.Signals(sig).name if hasattr(signal, 'Signals') else str(sig)
                logger.debug(f"Could not register handler for signal {signal_name}: {e}")
    
    def _signal_handler(self, signum: int, _frame: Any) -> None:
        """
        Internal signal handler that triggers shutdown.
        
        Args:
            signum: Signal number received.
            _frame: Current stack frame (unused).
        """
        signal_name = signal.Signals(signum).name if hasattr(signal, 'Signals') else str(signum)
        logger.info(f"Received signal {signal_name} ({signum}), initiating graceful shutdown...")
        self.trigger_shutdown(signum)
    
    def trigger_shutdown(self, signum: Optional[int] = None, exit_code: int = 0) -> None:
        """
        Trigger graceful shutdown by executing all registered callbacks.
        
        Callbacks are executed in the order they were registered. If a callback
        raises an exception, it is logged and execution continues with the next callback.
        
        **Async callbacks:** If a running event loop exists, the callback is awaited
        via run_coroutine_threadsafe(). If no event loop exists, the callback is
        SKIPPED (not executed) - we do NOT create new event loops during shutdown.
        
        After all callbacks complete, the process exits with the specified exit code.
        
        Args:
            signum: Optional signal number that triggered the shutdown (for logging).
            exit_code: Exit code to use when terminating the process (default: 0).
        """
        with self._lock:
            if self._shutdown_called:
                logger.debug("Shutdown already in progress, ignoring duplicate trigger.")
                return
            self._shutdown_called = True
        
        logger.info("Starting graceful shutdown...")
        
        # Execute all callbacks
        for callback in self._callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    # Try to get the running event loop
                    try:
                        loop = asyncio.get_running_loop()
                        # If we're in an async context, use run_coroutine_threadsafe
                        asyncio.run_coroutine_threadsafe(callback(), loop).result(timeout=2)
                    except RuntimeError:
                        # No running event loop - skip this callback (best-effort)
                        # Do NOT create new event loops during shutdown
                        callback_name = callback.__name__ if hasattr(callback, '__name__') else str(callback)
                        logger.debug(
                            f"Skipping async callback {callback_name}: no event loop available (best-effort shutdown)"
                        )
                else:
                    # Sync callback
                    callback()
            except Exception as e:
                logger.error(f"Error executing shutdown callback: {e}")
        
        logger.info("All shutdown callbacks completed. Exiting...")
        sys.exit(exit_code)


# Global shutdown manager instance
_default_manager = ShutdownManager()


def register_shutdown_callback(callback: Callable[..., Any]) -> None:
    """
    Register a cleanup callback with the global shutdown manager.
    
    Convenience function for registering callbacks without direct manager access.
    
    Args:
        callback: A callable (sync or async) to execute during shutdown.
                 Should dispose/close resources, not create new ones.
    """
    _default_manager.register_callback(callback)


def install_signal_handlers(signals_list: Optional[Iterable[int]] = None) -> None:
    """
    Install OS signal handlers using the global shutdown manager.
    
    Must be called from the main thread.
    
    Args:
        signals_list: Optional list of signal numbers to handle.
    """
    _default_manager.install_signal_handlers(signals_list)


def trigger_shutdown(signum: Optional[int] = None, exit_code: int = 0) -> None:
    """
    Trigger graceful shutdown using the global shutdown manager.
    
    Args:
        signum: Optional signal number for logging.
        exit_code: Process exit code (default: 0).
    """
    _default_manager.trigger_shutdown(signum, exit_code)
