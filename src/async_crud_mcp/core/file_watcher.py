"""OS filesystem watcher with debounce and coalesce for hash registry updates.

This module implements FileWatcher, which monitors configured directories
for external file changes and updates the HashRegistry in real-time.

Key features:
- Debounce: 100ms window to coalesce rapid events (editor temp files)
- Coalesce: DELETE+CREATE on same path becomes MODIFY
- Observer fallback: Native observer with polling fallback for network paths/inotify limits
- Hash registry integration: Updates hashes on MODIFY/CREATE, removes on DELETE

Cross-platform concerns:
- Network path detection: UNC paths (\\\\server\\share) on Windows, /mnt/ on Linux
- inotify limit handling: Falls back to PollingObserver on Linux when limit exceeded
- macOS FSEventsObserver: Used automatically by watchdog on macOS
"""

import logging
import os
import threading
import time
from typing import Any, Callable, List, Optional, Tuple

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer
from watchdog.observers.polling import PollingObserver

try:
    from .file_io import HashRegistry, compute_file_hash
except ImportError:
    from async_crud_mcp.core.file_io import HashRegistry, compute_file_hash

logger = logging.getLogger(__name__)


def _is_network_path(path: str) -> bool:
    """Detect if path is on a network filesystem.

    Args:
        path: Absolute path to check

    Returns:
        True if path appears to be on network filesystem

    Note:
        Checks for UNC paths (\\\\server\\share) on Windows and common
        network mount points (/mnt/, /net/) on Unix systems.
    """
    # Use original path for UNC/Unix detection (normpath on Windows converts / to \\)
    # Windows UNC paths
    if path.startswith('\\\\'):
        return True

    # Unix network mount points (check before normalization)
    if path.startswith('/mnt/') or path.startswith('/net/'):
        return True

    return False


class _DebouncedEventHandler(FileSystemEventHandler):
    """Debounce and coalesce filesystem events before updating hash registry.

    Event processing logic:
    1. Buffer events per normalized path with timestamp
    2. Coalesce DELETE+CREATE into MODIFY within debounce window
    3. After debounce window expires, flush to hash registry update logic

    Thread-safety:
        Uses threading.Lock for _pending dict access. Timer runs in daemon thread.
    """

    def __init__(
        self,
        registry: HashRegistry,
        debounce_ms: int,
        max_file_size_bytes: int,
    ):
        """Initialize debounced event handler.

        Args:
            registry: HashRegistry instance to update
            debounce_ms: Debounce window in milliseconds (default 100)
            max_file_size_bytes: Maximum file size to hash (from CrudConfig)
        """
        super().__init__()
        self._registry = registry
        self._debounce_seconds = debounce_ms / 1000.0
        self._max_file_size_bytes = max_file_size_bytes
        self._pending: dict[str, Tuple[str, float]] = {}  # path -> (event_type, timestamp)
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._flush_thread = threading.Thread(target=self._flush_loop, daemon=True)
        self._flush_thread.start()

    def stop(self) -> None:
        """Stop the debounce flush thread."""
        self._stop_event.set()
        self._flush_thread.join(timeout=1.0)

    def _normalize_path(self, path: str) -> str:
        """Normalize path for consistent comparison."""
        return os.path.normcase(os.path.normpath(os.path.realpath(path)))

    def _add_event(self, event_type: str, path: str) -> None:
        """Add event to pending buffer with coalesce logic.

        Args:
            event_type: Event type ('created', 'modified', 'deleted')
            path: File path

        Coalesce rules:
            - DELETE + CREATE -> MODIFY
            - CREATE + DELETE -> remove pending (net no-op)
            - MODIFY + anything -> keep as MODIFY
        """
        normalized = self._normalize_path(path)
        current_time = time.monotonic()

        with self._lock:
            if normalized in self._pending:
                existing_type, _ = self._pending[normalized]

                # Coalesce DELETE + CREATE -> MODIFY
                if existing_type == 'deleted' and event_type == 'created':
                    self._pending[normalized] = ('modified', current_time)
                    logger.debug(f"Coalesced DELETE+CREATE to MODIFY: {path}")
                # Coalesce CREATE + DELETE -> remove (net no-op)
                elif existing_type == 'created' and event_type == 'deleted':
                    del self._pending[normalized]
                    logger.debug(f"Coalesced CREATE+DELETE to no-op: {path}")
                # Keep as MODIFY if already MODIFY
                elif existing_type == 'modified':
                    self._pending[normalized] = ('modified', current_time)
                # Otherwise update to new event type
                else:
                    self._pending[normalized] = (event_type, current_time)
            else:
                self._pending[normalized] = (event_type, current_time)

    def _flush_loop(self) -> None:
        """Background thread loop that flushes expired events."""
        while not self._stop_event.is_set():
            try:
                self._flush_expired_events()
            except Exception as e:
                logger.error(f"Error in flush loop: {e}", exc_info=True)

            # Sleep for half the debounce interval
            time.sleep(self._debounce_seconds / 2)

    def _flush_expired_events(self) -> None:
        """Flush events that have expired past debounce window."""
        current_time = time.monotonic()
        to_flush: List[Tuple[str, str]] = []  # (path, event_type)

        with self._lock:
            expired_paths = [
                path
                for path, (_, timestamp) in self._pending.items()
                if current_time - timestamp >= self._debounce_seconds
            ]

            for path in expired_paths:
                event_type, _ = self._pending.pop(path)
                to_flush.append((path, event_type))

        # Process outside lock to avoid blocking event handler
        for path, event_type in to_flush:
            self._process_event(event_type, path)

    def _process_event(self, event_type: str, path: str) -> None:
        """Process a flushed event and update hash registry.

        Args:
            event_type: Event type ('created', 'modified', 'deleted')
            path: Normalized file path
        """
        try:
            if event_type in ('created', 'modified'):
                # Only update if file exists in registry (per PRD: new files registered on first access)
                if self._registry.get(path) is not None:
                    try:
                        new_hash = compute_file_hash(path, self._max_file_size_bytes)
                        self._registry.update(path, new_hash)
                        logger.debug(f"Updated hash for {path}: {new_hash}")
                    except FileNotFoundError:
                        # Race condition: file deleted between event and hash
                        logger.debug(f"File vanished before hash: {path}")
                        self._registry.remove(path)
                    except Exception as e:
                        logger.warning(f"Failed to hash {path}: {e}")
                else:
                    logger.debug(f"Ignoring {event_type} for unregistered file: {path}")

            elif event_type == 'deleted':
                self._registry.remove(path)
                logger.debug(f"Removed from registry: {path}")

        except Exception as e:
            logger.error(f"Error processing {event_type} event for {path}: {e}", exc_info=True)

    def on_created(self, event: FileSystemEvent) -> None:
        """Handle file created event."""
        if not event.is_directory:
            self._add_event('created', str(event.src_path))

    def on_modified(self, event: FileSystemEvent) -> None:
        """Handle file modified event."""
        if not event.is_directory:
            self._add_event('modified', str(event.src_path))

    def on_deleted(self, event: FileSystemEvent) -> None:
        """Handle file deleted event."""
        if not event.is_directory:
            self._add_event('deleted', str(event.src_path))

    def on_moved(self, event: FileSystemEvent) -> None:
        """Handle file moved event (treat as DELETE old + CREATE new)."""
        if not event.is_directory:
            self._add_event('deleted', str(event.src_path))
            # Watchdog's moved events have dest_path
            dest = getattr(event, 'dest_path', None)
            if dest:
                self._add_event('created', str(dest))


class FileWatcher:
    """OS filesystem watcher with debounce and hash registry integration.

    Monitors configured base_directories for external file changes and updates
    HashRegistry in real-time. Uses native observers with polling fallback for
    network paths and inotify limit errors.

    Lifecycle:
        1. Create FileWatcher with base_directories and HashRegistry
        2. Call start() to begin watching
        3. Call stop() to cleanup observers and threads
    """

    def __init__(
        self,
        base_directories: List[str],
        registry: HashRegistry,
        enabled: bool = True,
        debounce_ms: int = 100,
        max_file_size_bytes: int = 10_485_760,
        shutdown_callback: Optional[Callable[[], None]] = None,
    ):
        """Initialize file watcher.

        Args:
            base_directories: List of absolute paths to watch
            registry: HashRegistry instance to update
            enabled: Whether watcher is enabled (default True)
            debounce_ms: Debounce window in milliseconds (default 100)
            max_file_size_bytes: Maximum file size to hash (default 10MB)
            shutdown_callback: Optional callback for shutdown handler registration
        """
        self._base_directories = base_directories
        self._registry = registry
        self._enabled = enabled
        self._debounce_ms = debounce_ms
        self._max_file_size_bytes = max_file_size_bytes
        self._observers: List[Any] = []  # List of Observer or PollingObserver
        self._event_handler: Optional[_DebouncedEventHandler] = None

        # Register with shutdown handler if provided
        if shutdown_callback is not None:
            shutdown_callback()

    def _create_observer(self, path: str) -> Any:
        """Create appropriate observer for the given path.

        Args:
            path: Directory path to watch

        Returns:
            Observer instance (native or polling)

        Selection logic:
            1. If network path -> PollingObserver
            2. Try native Observer, fall back to PollingObserver on inotify error
            3. Default: native Observer
        """
        # Check for network path
        if _is_network_path(path):
            logger.warning(f"Network path detected, using PollingObserver: {path}")
            return PollingObserver(timeout=2)

        # Try native observer
        try:
            observer = Observer()
            # Start briefly to check for inotify errors
            observer.start()
            observer.stop()
            observer.join(timeout=1.0)
            return Observer()
        except OSError as e:
            # Check for inotify limit error
            if 'inotify' in str(e).lower() or getattr(e, 'errno', None) == 28:
                logger.warning(
                    f"inotify limit reached, falling back to PollingObserver: {e}"
                )
                return PollingObserver(timeout=2)
            # Re-raise other OSErrors
            raise

    def start(self) -> None:
        """Start watching configured directories.

        Creates observers for each base_directory and starts monitoring.
        If a directory doesn't exist, logs warning and continues.

        Note:
            If enabled=False, this is a no-op.
        """
        if not self._enabled:
            logger.info("File watcher is disabled, skipping start")
            return

        if self._event_handler is not None:
            logger.warning("File watcher already started")
            return

        logger.info(f"Starting file watcher for {len(self._base_directories)} directories")

        # Create shared event handler
        self._event_handler = _DebouncedEventHandler(
            registry=self._registry,
            debounce_ms=self._debounce_ms,
            max_file_size_bytes=self._max_file_size_bytes,
        )

        # Create and start observers for each directory
        for directory in self._base_directories:
            if not os.path.exists(directory):
                logger.warning(f"Directory does not exist, skipping watch: {directory}")
                continue

            try:
                observer = self._create_observer(directory)
                observer.schedule(self._event_handler, directory, recursive=True)
                observer.start()
                self._observers.append(observer)
                logger.info(f"Started watching: {directory}")
            except Exception as e:
                logger.error(f"Failed to start watching {directory}: {e}", exc_info=True)

    def stop(self) -> None:
        """Stop all observers and cleanup resources.

        Stops all running observers and the debounce flush thread.
        Safe to call multiple times.
        """
        logger.info("Stopping file watcher")

        # Stop event handler flush thread
        if self._event_handler is not None:
            self._event_handler.stop()
            self._event_handler = None

        # Stop all observers
        for observer in self._observers:
            try:
                observer.stop()
                observer.join(timeout=2.0)
            except Exception as e:
                logger.error(f"Error stopping observer: {e}", exc_info=True)

        self._observers.clear()
        logger.info("File watcher stopped")
