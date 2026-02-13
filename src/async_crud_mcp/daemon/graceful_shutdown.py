"""Graceful shutdown handling for MCP daemons.

This module provides signal handling and graceful shutdown logic
for MCP server daemons.

Usage:
    from graceful_shutdown import ShutdownHandler, graceful_stop

    handler = ShutdownHandler()
    handler.register()

    while handler.running:
        do_work()

    # Or use as context manager
    with ShutdownHandler() as handler:
        while handler.running:
            do_work()

Features:
    - Cross-platform signal handling (SIGTERM, SIGINT)
    - Graceful timeout for in-flight requests
    - Context manager support
    - Async support via asyncio events
"""

import signal
import sys
import threading
import time
from typing import Optional, Callable, List
from contextlib import contextmanager


class ShutdownHandler:
    """Handle graceful shutdown signals.

    Catches SIGTERM and SIGINT and sets a flag that can be
    polled by the main loop.
    """

    def __init__(self, timeout: float = 10.0):
        """Initialize the shutdown handler.

        Args:
            timeout: Maximum time to wait for graceful shutdown
        """
        self.timeout = timeout
        self.running = True
        self._shutdown_event = threading.Event()
        self._callbacks: List[Callable[[], None]] = []
        self._registered = False

    def register(self) -> None:
        """Register signal handlers.

        Call this once at startup to enable signal handling.
        Wrapped in try/except ValueError because signal.signal() raises
        ValueError when called from a non-main thread (expected when
        running as a Windows service).
        """
        if self._registered:
            return

        try:
            signal.signal(signal.SIGTERM, self._handle_signal)
            signal.signal(signal.SIGINT, self._handle_signal)

            # Windows doesn't have SIGHUP, but we can handle it on Unix
            if hasattr(signal, 'SIGHUP'):
                signal.signal(signal.SIGHUP, self._handle_signal)

            self._registered = True
        except ValueError:
            # "signal only works in main thread" - expected in Windows service context
            pass

    def _handle_signal(self, signum: int, frame) -> None:
        """Handle shutdown signal."""
        sig_name = signal.Signals(signum).name
        print(f"\nReceived {sig_name}, initiating graceful shutdown...")

        self.running = False
        self._shutdown_event.set()

        # Run callbacks
        for callback in self._callbacks:
            try:
                callback()
            except Exception as e:
                print(f"Error in shutdown callback: {e}")

    def add_callback(self, callback: Callable[[], None]) -> None:
        """Add a callback to run on shutdown.

        Args:
            callback: Function to call when shutdown signal received
        """
        self._callbacks.append(callback)

    def wait_for_shutdown(self, timeout: Optional[float] = None) -> bool:
        """Wait for shutdown signal.

        Args:
            timeout: Max time to wait (None = use default)

        Returns:
            True if shutdown was signaled, False if timeout
        """
        return self._shutdown_event.wait(timeout or self.timeout)

    def __enter__(self) -> "ShutdownHandler":
        """Context manager entry."""
        self.register()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Context manager exit."""
        pass  # Nothing to clean up


def graceful_stop(
    server,
    timeout: float = 10.0,
    force_after: float = 15.0,
) -> bool:
    """Stop a server gracefully with timeout.

    Attempts graceful shutdown, then forces if timeout exceeded.

    Args:
        server: Object with stop() method
        timeout: Time to wait for graceful stop
        force_after: Time before forcing termination

    Returns:
        True if stopped gracefully, False if forced

    Example:
        >>> graceful_stop(mcp_server, timeout=10)
        True
    """
    import threading

    stopped = threading.Event()
    graceful = True

    def do_stop():
        nonlocal graceful
        try:
            if hasattr(server, 'stop'):
                server.stop()
            elif hasattr(server, 'shutdown'):
                server.shutdown()
            elif hasattr(server, 'close'):
                server.close()
        except Exception as e:
            print(f"Error during graceful stop: {e}")
            graceful = False
        finally:
            stopped.set()

    # Start stop in background
    stop_thread = threading.Thread(target=do_stop, daemon=True)
    stop_thread.start()

    # Wait for graceful stop
    if stopped.wait(timeout):
        return graceful

    # Timeout - try to force
    print(f"Graceful stop timed out after {timeout}s, forcing...")

    if hasattr(server, 'force_stop'):
        try:
            server.force_stop()
        except Exception:
            pass

    # Wait a bit more for force to complete
    if stopped.wait(force_after - timeout):
        return False

    print(f"Force stop also timed out after {force_after}s")
    return False


@contextmanager
def shutdown_context(timeout: float = 10.0):
    """Context manager for shutdown handling.

    Usage:
        >>> with shutdown_context() as handler:
        ...     while handler.running:
        ...         do_work()
    """
    handler = ShutdownHandler(timeout)
    try:
        handler.register()
    except ValueError:
        # "signal only works in main thread" - expected in Windows service context
        pass
    try:
        yield handler
    finally:
        pass


# =============================================================================
# Async support
# =============================================================================

try:
    import asyncio

    class AsyncShutdownHandler:
        """Async-compatible shutdown handler."""

        def __init__(self, timeout: float = 10.0):
            self.timeout = timeout
            self.running = True
            self._shutdown_event: Optional[asyncio.Event] = None

        async def setup(self) -> None:
            """Set up async event and signal handlers."""
            self._shutdown_event = asyncio.Event()

            loop = asyncio.get_running_loop()

            for sig in (signal.SIGTERM, signal.SIGINT):
                try:
                    loop.add_signal_handler(sig, self._handle_signal)
                except NotImplementedError:
                    # Windows doesn't support add_signal_handler
                    signal.signal(sig, self._sync_handler)

        def _handle_signal(self) -> None:
            """Handle signal in async context."""
            self.running = False
            if self._shutdown_event:
                self._shutdown_event.set()

        def _sync_handler(self, signum: int, frame) -> None:
            """Sync signal handler for Windows."""
            self._handle_signal()

        async def wait_for_shutdown(self) -> None:
            """Wait for shutdown signal."""
            if self._shutdown_event:
                await self._shutdown_event.wait()

except ImportError:
    AsyncShutdownHandler = None  # type: ignore


# =============================================================================
# CLI for testing
# =============================================================================

if __name__ == "__main__":
    print("Testing shutdown handler...")
    print("Press Ctrl+C to test graceful shutdown")

    with shutdown_context() as handler:
        while handler.running:
            print(".", end="", flush=True)
            time.sleep(1)

    print("\nShutdown complete!")
