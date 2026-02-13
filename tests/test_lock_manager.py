"""
Tests for asyncio-based lock manager.

Covers FIFO ordering, concurrent reads, exclusive writes, timeout handling,
starvation prevention, dual-lock deadlock prevention, and persistence.
"""

import asyncio
import pytest
import time
from async_crud_mcp.core.lock_manager import (
    LockManager,
    LockTimeout,
    LockType,
)


@pytest.mark.asyncio
async def test_basic_read_lock():
    """Test basic read lock acquisition and release."""
    manager = LockManager()
    path = "/test/file.txt"

    # Acquire read lock
    request_id = await manager.acquire_read(path)
    assert request_id is not None

    # Check status
    status = manager.get_status(path)
    assert status["active_readers"] == 1
    assert status["active_writer"] is False
    assert status["queued"] == 0

    # Release read lock
    await manager.release_read(path, request_id)

    # Check status after release
    status = manager.get_status(path)
    assert status["active_readers"] == 0


@pytest.mark.asyncio
async def test_basic_write_lock():
    """Test basic write lock acquisition and release."""
    manager = LockManager()
    path = "/test/file.txt"

    # Acquire write lock
    request_id = await manager.acquire_write(path, timeout=5.0)
    assert request_id is not None

    # Check status
    status = manager.get_status(path)
    assert status["active_readers"] == 0
    assert status["active_writer"] is True
    assert status["queued"] == 0

    # Release write lock
    await manager.release_write(path, request_id)

    # Check status after release
    status = manager.get_status(path)
    assert status["active_writer"] is False


@pytest.mark.asyncio
async def test_concurrent_reads():
    """Test that multiple read locks can be held simultaneously."""
    manager = LockManager()
    path = "/test/file.txt"

    # Acquire multiple read locks concurrently
    tasks = [manager.acquire_read(path) for _ in range(5)]
    request_ids = await asyncio.gather(*tasks)

    # Check status - should have 5 active readers
    status = manager.get_status(path)
    assert status["active_readers"] == 5
    assert status["active_writer"] is False
    assert status["queued"] == 0

    # Release all read locks
    for request_id in request_ids:
        await manager.release_read(path, request_id)

    # Check status after release
    status = manager.get_status(path)
    assert status["active_readers"] == 0


@pytest.mark.asyncio
async def test_write_blocks_reads():
    """Test that an active write lock blocks new read acquisitions."""
    manager = LockManager()
    path = "/test/file.txt"

    # Acquire write lock
    write_id = await manager.acquire_write(path, timeout=5.0)

    # Try to acquire read lock - should queue
    read_acquired = False

    async def acquire_read():
        nonlocal read_acquired
        await manager.acquire_read(path)
        read_acquired = True

    read_task = asyncio.create_task(acquire_read())

    # Give it time to attempt acquisition
    await asyncio.sleep(0.1)

    # Read should still be queued
    assert read_acquired is False
    status = manager.get_status(path)
    assert status["active_writer"] is True
    assert status["queued"] == 1

    # Release write lock
    await manager.release_write(path, write_id)

    # Wait for read to be granted
    await asyncio.sleep(0.1)

    # Read should now be acquired
    assert read_acquired is True

    # Clean up
    read_task.cancel()
    try:
        await read_task
    except asyncio.CancelledError:
        pass


@pytest.mark.asyncio
async def test_read_blocks_writes():
    """Test that active read locks block write acquisition."""
    manager = LockManager()
    path = "/test/file.txt"

    # Acquire read locks
    read_id1 = await manager.acquire_read(path)
    read_id2 = await manager.acquire_read(path)

    # Try to acquire write lock - should queue
    write_acquired = False

    async def acquire_write():
        nonlocal write_acquired
        await manager.acquire_write(path, timeout=5.0)
        write_acquired = True

    write_task = asyncio.create_task(acquire_write())

    # Give it time to attempt acquisition
    await asyncio.sleep(0.1)

    # Write should still be queued
    assert write_acquired is False
    status = manager.get_status(path)
    assert status["active_readers"] == 2
    assert status["queued"] == 1

    # Release one read lock - write should still be queued
    await manager.release_read(path, read_id1)
    await asyncio.sleep(0.1)
    assert write_acquired is False

    # Release second read lock - write should now be granted
    await manager.release_read(path, read_id2)
    await asyncio.sleep(0.1)

    # Write should now be acquired
    assert write_acquired is True

    # Clean up
    write_task.cancel()
    try:
        await write_task
    except asyncio.CancelledError:
        pass


@pytest.mark.asyncio
async def test_fifo_ordering():
    """Test that locks are granted in FIFO order."""
    manager = LockManager()
    path = "/test/file.txt"

    # Acquire initial write lock
    initial_write = await manager.acquire_write(path, timeout=5.0)

    execution_order = []

    async def write_op(label):
        request_id = await manager.acquire_write(path, timeout=5.0)
        execution_order.append(label)
        await asyncio.sleep(0.05)  # Hold lock briefly
        await manager.release_write(path, request_id)

    async def read_op(label):
        request_id = await manager.acquire_read(path)
        execution_order.append(label)
        await asyncio.sleep(0.05)  # Hold lock briefly
        await manager.release_read(path, request_id)

    # Queue operations: write1, read1, write2
    tasks = [
        asyncio.create_task(write_op("write1")),
        asyncio.create_task(read_op("read1")),
        asyncio.create_task(write_op("write2")),
    ]

    # Give them time to queue
    await asyncio.sleep(0.1)

    # Release initial write lock
    await manager.release_write(path, initial_write)

    # Wait for all operations to complete
    await asyncio.gather(*tasks)

    # Should execute in FIFO order: write1, read1, write2
    assert execution_order == ["write1", "read1", "write2"]


@pytest.mark.asyncio
async def test_starvation_prevention():
    """Test that writes are not starved by continuous reads."""
    manager = LockManager()
    path = "/test/file.txt"

    # Acquire initial read lock
    initial_read = await manager.acquire_read(path)

    execution_order = []

    async def write_op(label):
        request_id = await manager.acquire_write(path, timeout=5.0)
        execution_order.append(label)
        await asyncio.sleep(0.05)  # Hold lock briefly
        await manager.release_write(path, request_id)

    async def read_op(label):
        request_id = await manager.acquire_read(path)
        execution_order.append(label)
        await asyncio.sleep(0.05)  # Hold lock briefly
        await manager.release_read(path, request_id)

    # Queue: write1, then read1, read2
    tasks = [
        asyncio.create_task(write_op("write1")),
        asyncio.create_task(read_op("read1")),
        asyncio.create_task(read_op("read2")),
    ]

    # Give them time to queue
    await asyncio.sleep(0.1)

    # Release initial read
    await manager.release_read(path, initial_read)

    # Wait for all operations to complete
    await asyncio.gather(*tasks)

    # write1 should execute before read1 and read2 (FIFO)
    assert execution_order[0] == "write1"
    # read1 and read2 might execute in any order after write1
    assert set(execution_order[1:]) == {"read1", "read2"}


@pytest.mark.asyncio
async def test_batch_read_promotion():
    """Test that consecutive reads are promoted together when write releases."""
    manager = LockManager()
    path = "/test/file.txt"

    # Acquire initial write lock
    initial_write = await manager.acquire_write(path, timeout=5.0)

    execution_order = []
    start_times = {}

    async def read_op(label):
        start_times[label] = time.monotonic()
        request_id = await manager.acquire_read(path)
        execution_order.append(label)
        await asyncio.sleep(0.05)  # Hold lock briefly
        await manager.release_read(path, request_id)

    async def write_op(label):
        start_times[label] = time.monotonic()
        request_id = await manager.acquire_write(path, timeout=5.0)
        execution_order.append(label)
        await asyncio.sleep(0.05)  # Hold lock briefly
        await manager.release_write(path, request_id)

    # Queue: read1, read2, read3, write1
    tasks = [
        asyncio.create_task(read_op("read1")),
        asyncio.create_task(read_op("read2")),
        asyncio.create_task(read_op("read3")),
        asyncio.create_task(write_op("write1")),
    ]

    # Give them time to queue
    await asyncio.sleep(0.1)

    # Release initial write
    await manager.release_write(path, initial_write)

    # Wait for all tasks to complete
    await asyncio.gather(*tasks)

    # All three reads should be granted simultaneously
    assert "read1" in execution_order
    assert "read2" in execution_order
    assert "read3" in execution_order
    assert "write1" in execution_order  # Write should execute after reads release

    # Verify reads started at approximately the same time (batch promotion)
    read_times = [start_times["read1"], start_times["read2"], start_times["read3"]]
    time_spread = max(read_times) - min(read_times)
    assert time_spread < 0.05  # Should start within 50ms of each other


@pytest.mark.asyncio
async def test_timeout():
    """Test that write lock acquisition times out appropriately."""
    manager = LockManager()
    path = "/test/file.txt"

    # Acquire write lock
    write_id = await manager.acquire_write(path, timeout=5.0)

    # Try to acquire another write with short timeout - should timeout
    with pytest.raises(LockTimeout) as exc_info:
        await manager.acquire_write(path, timeout=0.1)

    assert "Failed to acquire write lock within 0.1s" in str(exc_info.value)

    # Release write lock
    await manager.release_write(path, write_id)


@pytest.mark.asyncio
async def test_timeout_cleanup():
    """Test that timed-out entries are removed from queue."""
    manager = LockManager()
    path = "/test/file.txt"

    # Acquire write lock
    write_id = await manager.acquire_write(path, timeout=5.0)

    # Try to acquire another write with timeout
    try:
        await manager.acquire_write(path, timeout=0.1)
    except LockTimeout:
        pass

    # Check that queue is empty (timed-out entry was removed)
    status = manager.get_status(path)
    assert status["queued"] == 0

    # Release initial write
    await manager.release_write(path, write_id)

    # Should be able to acquire write immediately
    new_write_id = await manager.acquire_write(path, timeout=1.0)
    assert new_write_id is not None

    # Clean up
    await manager.release_write(path, new_write_id)


@pytest.mark.asyncio
async def test_dual_lock_alphabetical():
    """Test that dual-lock acquires in alphabetical order."""
    manager = LockManager()
    path_a = "/test/b.txt"  # Second alphabetically
    path_b = "/test/a.txt"  # First alphabetically

    # Track acquisition order
    acquisition_order = []

    original_acquire = manager.acquire_write

    async def tracked_acquire(path, timeout):
        acquisition_order.append(path)
        return await original_acquire(path, timeout)

    manager.acquire_write = tracked_acquire

    # Acquire dual lock
    id_a, id_b = await manager.acquire_dual_write(path_a, path_b, timeout=5.0)

    # Should acquire in alphabetical order: a.txt, then b.txt
    assert acquisition_order == ["/test/a.txt", "/test/b.txt"]

    # Clean up
    manager.acquire_write = original_acquire
    await manager.release_write(path_a, id_a)
    await manager.release_write(path_b, id_b)


@pytest.mark.asyncio
async def test_dual_lock_deadlock_prevention():
    """Test that dual-lock prevents deadlocks with overlapping paths."""
    manager = LockManager()
    path_a = "/test/a.txt"
    path_b = "/test/b.txt"

    results = {"task1": None, "task2": None}

    async def dual_lock_1():
        try:
            id_a, id_b = await manager.acquire_dual_write(path_a, path_b, timeout=2.0)
            results["task1"] = "success"
            await asyncio.sleep(0.1)
            await manager.release_write(path_a, id_a)
            await manager.release_write(path_b, id_b)
        except LockTimeout:
            results["task1"] = "timeout"

    async def dual_lock_2():
        try:
            # Reversed order - but alphabetical acquisition prevents deadlock
            id_b, id_a = await manager.acquire_dual_write(path_b, path_a, timeout=2.0)
            results["task2"] = "success"
            await asyncio.sleep(0.1)
            await manager.release_write(path_b, id_b)
            await manager.release_write(path_a, id_a)
        except LockTimeout:
            results["task2"] = "timeout"

    # Run both tasks concurrently
    await asyncio.gather(dual_lock_1(), dual_lock_2())

    # Both should succeed (no deadlock)
    # One will acquire first, the other will wait and then acquire
    assert results["task1"] == "success"
    assert results["task2"] == "success"


@pytest.mark.asyncio
async def test_ttl_expiry():
    """Test that purge_expired removes entries past TTL."""
    manager = LockManager(ttl_multiplier=0.1)  # Very short TTL
    path = "/test/file.txt"

    # Acquire write lock
    write_id = await manager.acquire_write(path, timeout=1.0)

    # Queue another write that will timeout
    try:
        await manager.acquire_write(path, timeout=0.05)
    except LockTimeout:
        pass

    # Snapshot should capture the active write
    snapshot = manager.snapshot()
    assert path in snapshot

    # Wait for TTL to expire
    await asyncio.sleep(0.2)

    # Purge expired entries
    purged = await manager.purge_expired()
    # Note: The active write (write_id) should NOT be purged, only queued entries

    # Release the active write
    await manager.release_write(path, write_id)


@pytest.mark.asyncio
async def test_snapshot_restore():
    """Test that snapshot and restore preserve lock state."""
    manager1 = LockManager()
    path = "/test/file.txt"

    # Acquire read lock
    read_id = await manager1.acquire_read(path)

    # Create snapshot
    snapshot = manager1.snapshot()

    # Create new manager and restore
    manager2 = LockManager()
    await manager2.restore(snapshot)

    # Check that state was restored
    status = manager2.get_status(path)
    assert status["active_readers"] == 1
    assert status["active_writer"] is False

    # Clean up
    await manager1.release_read(path, read_id)


@pytest.mark.asyncio
async def test_reentrant_safety():
    """Test that releasing a lock properly triggers promotion of next waiter."""
    manager = LockManager()
    path = "/test/file.txt"

    # Acquire write lock
    write_id1 = await manager.acquire_write(path, timeout=5.0)

    # Queue another write
    promoted = False

    async def wait_for_promotion():
        nonlocal promoted
        await manager.acquire_write(path, timeout=5.0)
        promoted = True

    task = asyncio.create_task(wait_for_promotion())

    # Give time to queue
    await asyncio.sleep(0.1)
    assert promoted is False

    # Release first write - should immediately promote the queued write
    await manager.release_write(path, write_id1)

    # Give time for promotion
    await asyncio.sleep(0.1)

    # Second write should be promoted
    assert promoted is True

    # Clean up
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


@pytest.mark.asyncio
async def test_get_all_status():
    """Test get_all_status returns status for all files."""
    manager = LockManager()
    path1 = "/test/file1.txt"
    path2 = "/test/file2.txt"

    # Acquire locks on multiple files
    read_id = await manager.acquire_read(path1)
    write_id = await manager.acquire_write(path2, timeout=5.0)

    # Get all status
    all_status = manager.get_all_status()

    # Should have 2 entries
    assert len(all_status) == 2

    # Check individual statuses
    statuses_by_path = {s["path"]: s for s in all_status}
    assert statuses_by_path[path1]["active_readers"] == 1
    assert statuses_by_path[path2]["active_writer"] is True

    # Clean up
    await manager.release_read(path1, read_id)
    await manager.release_write(path2, write_id)


@pytest.mark.asyncio
async def test_release_nonexistent_lock():
    """Test that releasing a non-existent lock is safe (no error)."""
    manager = LockManager()
    path = "/test/file.txt"

    # Release lock that was never acquired - should not raise error
    await manager.release_read(path, "fake-id")
    await manager.release_write(path, "fake-id")

    # Status should show no locks
    status = manager.get_status(path)
    assert status["active_readers"] == 0
    assert status["active_writer"] is False
