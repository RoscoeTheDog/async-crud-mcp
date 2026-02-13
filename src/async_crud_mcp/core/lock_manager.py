"""
Asyncio-based read/write lock manager with FIFO queue semantics.

This module provides per-file locking for the MCP server's file operations,
ensuring safe concurrent access with proper ordering and starvation prevention.
"""

import asyncio
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple


class LockType(Enum):
    """Type of lock being requested."""
    READ = "read"
    WRITE = "write"


class LockTimeout(Exception):
    """Raised when lock acquisition times out."""
    pass


@dataclass
class LockEntry:
    """
    Represents a single pending lock request in the FIFO queue.

    Attributes:
        request_id: Unique identifier for this lock request
        lock_type: Type of lock (READ or WRITE)
        event: Asyncio event to signal when lock is granted
        created_at: Monotonic timestamp when request was created
        timeout: Timeout in seconds (None for reads, required for writes)
        ttl_expires_at: Optional TTL expiry timestamp for persistence mode
    """
    request_id: str
    lock_type: LockType
    event: asyncio.Event
    created_at: float
    timeout: Optional[float] = None
    ttl_expires_at: Optional[float] = None


class FileLock:
    """
    Per-file lock state with FIFO queue semantics.

    Manages read/write locking for a single file path. Supports concurrent
    reads, exclusive writes, and strict FIFO ordering with starvation prevention.
    """

    def __init__(self) -> None:
        """Initialize an empty file lock."""
        self.active_readers: int = 0
        self.active_writer: bool = False
        self.queue: deque[LockEntry] = deque()
        self._condition: asyncio.Condition = asyncio.Condition()

    async def acquire_read(self, request_id: str, timeout: Optional[float] = None) -> None:
        """
        Acquire a read lock on this file.

        Args:
            request_id: Unique identifier for this request
            timeout: Not used for reads (per PRD spec)

        Note:
            Read locks have no timeout and will wait indefinitely.
        """
        entry = LockEntry(
            request_id=request_id,
            lock_type=LockType.READ,
            event=asyncio.Event(),
            created_at=time.monotonic(),
            timeout=None
        )

        async with self._condition:
            # If no active writer and queue is empty, grant immediately
            if not self.active_writer and len(self.queue) == 0:
                self.active_readers += 1
                return

            # Otherwise, queue and wait
            self.queue.append(entry)

        # Wait for lock to be granted
        await entry.event.wait()

    async def acquire_write(self, request_id: str, timeout: float) -> None:
        """
        Acquire a write lock on this file.

        Args:
            request_id: Unique identifier for this request
            timeout: Maximum time to wait in seconds

        Raises:
            LockTimeout: If lock cannot be acquired within timeout
        """
        entry = LockEntry(
            request_id=request_id,
            lock_type=LockType.WRITE,
            event=asyncio.Event(),
            created_at=time.monotonic(),
            timeout=timeout
        )

        async with self._condition:
            # If no active readers/writer and queue is empty, grant immediately
            if self.active_readers == 0 and not self.active_writer and len(self.queue) == 0:
                self.active_writer = True
                return

            # Otherwise, queue and wait
            self.queue.append(entry)

        # Wait for lock to be granted with timeout
        try:
            await asyncio.wait_for(entry.event.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            # Remove from queue and raise LockTimeout
            async with self._condition:
                try:
                    self.queue.remove(entry)
                except ValueError:
                    # Entry was already removed (race condition)
                    pass
            raise LockTimeout(f"Failed to acquire write lock within {timeout}s")

    async def release_read(self, request_id: str) -> None:
        """
        Release a read lock.

        Args:
            request_id: Identifier of the lock to release (not currently used)
        """
        async with self._condition:
            if self.active_readers > 0:
                self.active_readers -= 1
            await self._promote_next()

    async def release_write(self, request_id: str) -> None:
        """
        Release a write lock.

        Args:
            request_id: Identifier of the lock to release (not currently used)
        """
        async with self._condition:
            self.active_writer = False
            await self._promote_next()

    async def _promote_next(self) -> None:
        """
        Promote eligible waiters from the front of the queue.

        This implements the FIFO queue algorithm:
        - If front is WRITE and no active readers/writer: grant it
        - If front is READ and no active writer: grant it AND all consecutive READs
        - If front is WRITE but active readers exist: wait for readers to drain

        Must be called while holding self._condition lock.
        """
        while len(self.queue) > 0:
            front = self.queue[0]

            if front.lock_type == LockType.WRITE:
                # Write needs exclusive access
                if self.active_readers == 0 and not self.active_writer:
                    self.queue.popleft()
                    self.active_writer = True
                    front.event.set()
                    break  # Only one write at a time
                else:
                    break  # Wait for active locks to clear

            elif front.lock_type == LockType.READ:
                # Read can be granted if no active writer
                if not self.active_writer:
                    # Batch promote: grant all consecutive reads from front
                    while len(self.queue) > 0 and self.queue[0].lock_type == LockType.READ:
                        entry = self.queue.popleft()
                        self.active_readers += 1
                        entry.event.set()
                    break  # Done promoting this batch
                else:
                    break  # Wait for writer to release


class LockManager:
    """
    Top-level lock manager coordinating per-file locks.

    Manages a dictionary of FileLock instances keyed by normalized file paths.
    Provides high-level acquire/release operations and utilities for persistence.
    """

    def __init__(self, ttl_multiplier: float = 2.0):
        """
        Initialize the lock manager.

        Args:
            ttl_multiplier: Multiplier for TTL calculation (ttl = timeout * multiplier)
        """
        self._locks: Dict[str, FileLock] = {}
        self._ttl_multiplier = ttl_multiplier
        self._global_lock = asyncio.Lock()

    def _get_or_create_lock(self, path: str) -> FileLock:
        """
        Get or create a FileLock for the given path.

        Args:
            path: Normalized absolute file path

        Returns:
            FileLock instance for this path

        Note:
            Caller must hold self._global_lock
        """
        if path not in self._locks:
            self._locks[path] = FileLock()
        return self._locks[path]

    async def acquire_read(self, path: str) -> str:
        """
        Acquire a read lock on a file.

        Args:
            path: Normalized absolute file path

        Returns:
            Request ID for this lock (for release)
        """
        request_id = str(uuid.uuid4())

        async with self._global_lock:
            file_lock = self._get_or_create_lock(path)

        await file_lock.acquire_read(request_id)
        return request_id

    async def acquire_write(self, path: str, timeout: float = 30.0) -> str:
        """
        Acquire a write lock on a file.

        Args:
            path: Normalized absolute file path
            timeout: Maximum time to wait in seconds (default: 30.0)

        Returns:
            Request ID for this lock (for release)

        Raises:
            LockTimeout: If lock cannot be acquired within timeout
        """
        request_id = str(uuid.uuid4())

        async with self._global_lock:
            file_lock = self._get_or_create_lock(path)

        # Calculate TTL for persistence mode
        ttl_expires_at = None
        if self._ttl_multiplier > 0:
            ttl_expires_at = time.monotonic() + (timeout * self._ttl_multiplier)

        await file_lock.acquire_write(request_id, timeout)
        return request_id

    async def release_read(self, path: str, request_id: str) -> None:
        """
        Release a read lock.

        Args:
            path: Normalized absolute file path
            request_id: Request ID returned from acquire_read
        """
        async with self._global_lock:
            if path not in self._locks:
                return  # Lock already released or never acquired
            file_lock = self._locks[path]

        await file_lock.release_read(request_id)

    async def release_write(self, path: str, request_id: str) -> None:
        """
        Release a write lock.

        Args:
            path: Normalized absolute file path
            request_id: Request ID returned from acquire_write
        """
        async with self._global_lock:
            if path not in self._locks:
                return  # Lock already released or never acquired
            file_lock = self._locks[path]

        await file_lock.release_write(request_id)

    async def acquire_dual_write(
        self,
        path_a: str,
        path_b: str,
        timeout: float = 30.0
    ) -> Tuple[str, str]:
        """
        Acquire write locks on two files in alphabetical order (deadlock prevention).

        Args:
            path_a: First file path
            path_b: Second file path
            timeout: Maximum time to wait for each lock

        Returns:
            Tuple of (request_id_a, request_id_b)

        Raises:
            LockTimeout: If either lock cannot be acquired

        Note:
            If the second lock fails, the first lock is released automatically.
        """
        # Sort paths alphabetically for consistent ordering
        paths = sorted([path_a, path_b])
        first_path = paths[0]
        second_path = paths[1]

        # Acquire first lock
        first_id = await self.acquire_write(first_path, timeout)

        # Try to acquire second lock
        try:
            second_id = await self.acquire_write(second_path, timeout)
        except LockTimeout:
            # Release first lock before re-raising
            await self.release_write(first_path, first_id)
            raise

        # Map back to original order
        if first_path == path_a:
            return (first_id, second_id)
        else:
            return (second_id, first_id)

    def get_status(self, path: str) -> Dict[str, Any]:
        """
        Get status of locks for a specific file.

        Args:
            path: Normalized absolute file path

        Returns:
            Dictionary with lock status information
        """
        if path not in self._locks:
            return {
                "path": path,
                "active_readers": 0,
                "active_writer": False,
                "queued": 0
            }

        file_lock = self._locks[path]
        return {
            "path": path,
            "active_readers": file_lock.active_readers,
            "active_writer": file_lock.active_writer,
            "queued": len(file_lock.queue)
        }

    def get_all_status(self) -> List[Dict[str, Any]]:
        """
        Get status of all file locks.

        Returns:
            List of status dictionaries for all files with active or queued locks
        """
        return [self.get_status(path) for path in self._locks.keys()]

    async def purge_expired(self) -> int:
        """
        Remove expired lock entries based on TTL.

        Returns:
            Number of entries purged

        Note:
            Used for persistence mode - called on server restart after loading state.
        """
        purged = 0
        current_time = time.monotonic()

        async with self._global_lock:
            for path, file_lock in list(self._locks.items()):
                async with file_lock._condition:
                    # Remove expired entries from queue
                    original_len = len(file_lock.queue)
                    file_lock.queue = deque([
                        entry for entry in file_lock.queue
                        if entry.ttl_expires_at is None or entry.ttl_expires_at > current_time
                    ])
                    purged += original_len - len(file_lock.queue)

                    # If queue is empty and no active locks, remove the FileLock
                    if (len(file_lock.queue) == 0 and
                        file_lock.active_readers == 0 and
                        not file_lock.active_writer):
                        del self._locks[path]

        return purged

    def snapshot(self) -> Dict[str, Any]:
        """
        Create a serializable snapshot of current lock state.

        Returns:
            Dictionary representing all lock state

        Note:
            Used for persistence - state can be saved and restored across restarts.
        """
        snapshot = {}

        for path, file_lock in self._locks.items():
            snapshot[path] = {
                "active_readers": file_lock.active_readers,
                "active_writer": file_lock.active_writer,
                "queue": [
                    {
                        "request_id": entry.request_id,
                        "lock_type": entry.lock_type.value,
                        "created_at": entry.created_at,
                        "timeout": entry.timeout,
                        "ttl_expires_at": entry.ttl_expires_at
                    }
                    for entry in file_lock.queue
                ]
            }

        return snapshot

    async def restore(self, state: Dict[str, Any]) -> None:
        """
        Restore lock state from a snapshot.

        Args:
            state: Snapshot dictionary from snapshot()

        Note:
            Used for persistence - loads state after server restart.
            Call purge_expired() after restore to clean up stale entries.
        """
        async with self._global_lock:
            self._locks.clear()

            for path, file_state in state.items():
                file_lock = FileLock()
                file_lock.active_readers = file_state["active_readers"]
                file_lock.active_writer = file_state["active_writer"]

                for entry_data in file_state["queue"]:
                    entry = LockEntry(
                        request_id=entry_data["request_id"],
                        lock_type=LockType(entry_data["lock_type"]),
                        event=asyncio.Event(),
                        created_at=entry_data["created_at"],
                        timeout=entry_data["timeout"],
                        ttl_expires_at=entry_data["ttl_expires_at"]
                    )
                    file_lock.queue.append(entry)

                self._locks[path] = file_lock
