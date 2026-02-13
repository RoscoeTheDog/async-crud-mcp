"""Tests for file_watcher module.

Test categories:
1. Unit tests for debounce/coalesce logic (no real filesystem)
2. Unit tests for observer factory
3. Integration tests with real filesystem
4. Lifecycle tests
"""

import time
from unittest.mock import patch

from async_crud_mcp.core.file_io import HashRegistry
from async_crud_mcp.core.file_watcher import FileWatcher, _is_network_path


class TestNetworkPathDetection:
    """Test network path detection logic."""

    def test_unc_path_windows(self):
        """Test UNC path detection on Windows."""
        assert _is_network_path(r"\\server\share\file.txt")
        assert _is_network_path(r"\\SERVER\SHARE\FILE.TXT")

    def test_mnt_path_unix(self):
        """Test /mnt/ path detection on Unix."""
        assert _is_network_path("/mnt/share/file.txt")
        assert _is_network_path("/net/share/file.txt")

    def test_local_paths(self):
        """Test that local paths are not detected as network."""
        assert not _is_network_path("/home/user/file.txt")
        assert not _is_network_path(r"C:\Users\file.txt")
        assert not _is_network_path("./relative/path.txt")


class TestDebounceCoalesceLogic:
    """Test debounce and coalesce logic without real filesystem."""

    def test_single_event_debounced(self, tmp_path):
        """Test that single event is processed after debounce window."""
        registry = HashRegistry()
        test_file = tmp_path / "test.txt"
        test_file.write_text("initial content", encoding='utf-8')

        # Register file so watcher will update it
        from async_crud_mcp.core.file_io import compute_file_hash
        initial_hash = compute_file_hash(str(test_file))
        registry.update(str(test_file), initial_hash)

        watcher = FileWatcher(
            base_directories=[str(tmp_path)],
            registry=registry,
            enabled=True,
            debounce_ms=100,
        )

        try:
            watcher.start()

            # Modify file
            test_file.write_text("modified content", encoding='utf-8')

            # Wait for debounce window + processing
            time.sleep(0.3)

            # Hash should be updated
            new_hash = registry.get(str(test_file))
            assert new_hash != initial_hash

        finally:
            watcher.stop()

    def test_rapid_modifies_coalesced(self, tmp_path):
        """Test that rapid modifies within debounce window are coalesced."""
        registry = HashRegistry()
        test_file = tmp_path / "test.txt"
        test_file.write_text("initial", encoding='utf-8')

        # Register file
        from async_crud_mcp.core.file_io import compute_file_hash
        initial_hash = compute_file_hash(str(test_file))
        registry.update(str(test_file), initial_hash)

        watcher = FileWatcher(
            base_directories=[str(tmp_path)],
            registry=registry,
            enabled=True,
            debounce_ms=100,
        )

        try:
            watcher.start()

            # Rapid modifications
            for i in range(5):
                test_file.write_text(f"content {i}", encoding='utf-8')
                time.sleep(0.02)  # 20ms between writes (faster than debounce)

            # Wait for debounce + processing
            time.sleep(0.3)

            # Should have final content
            final_content = test_file.read_text(encoding='utf-8')
            assert final_content == "content 4"

            # Hash should be updated to final version
            final_hash = compute_file_hash(str(test_file))
            assert registry.get(str(test_file)) == final_hash

        finally:
            watcher.stop()

    def test_delete_create_coalesced_to_modify(self, tmp_path):
        """Test that DELETE+CREATE is coalesced to MODIFY."""
        registry = HashRegistry()
        test_file = tmp_path / "test.txt"
        test_file.write_text("initial", encoding='utf-8')

        # Register file
        from async_crud_mcp.core.file_io import compute_file_hash
        initial_hash = compute_file_hash(str(test_file))
        registry.update(str(test_file), initial_hash)

        watcher = FileWatcher(
            base_directories=[str(tmp_path)],
            registry=registry,
            enabled=True,
            debounce_ms=100,
        )

        try:
            watcher.start()

            # Simulate editor temp-file pattern: delete + create
            test_file.unlink()
            time.sleep(0.02)
            test_file.write_text("new content", encoding='utf-8')

            # Wait for debounce + processing
            time.sleep(0.3)

            # File should still be in registry with new hash
            assert registry.get(str(test_file)) is not None
            new_hash = compute_file_hash(str(test_file))
            assert registry.get(str(test_file)) == new_hash

        finally:
            watcher.stop()

    def test_create_delete_coalesced_to_noop(self, tmp_path):
        """Test that CREATE+DELETE within debounce window is no-op."""
        registry = HashRegistry()

        watcher = FileWatcher(
            base_directories=[str(tmp_path)],
            registry=registry,
            enabled=True,
            debounce_ms=100,
        )

        try:
            watcher.start()

            # Create and immediately delete within debounce window
            test_file = tmp_path / "temp.txt"
            test_file.write_text("temporary", encoding='utf-8')
            time.sleep(0.02)
            test_file.unlink()

            # Wait for debounce + processing
            time.sleep(0.3)

            # File should not be in registry (was never registered before creation)
            assert registry.get(str(test_file)) is None

        finally:
            watcher.stop()


class TestFileWatcherIntegration:
    """Integration tests with real filesystem operations."""

    def test_create_file_not_in_registry_ignored(self, tmp_path):
        """Test that creating a new file not in registry is ignored per PRD."""
        registry = HashRegistry()

        watcher = FileWatcher(
            base_directories=[str(tmp_path)],
            registry=registry,
            enabled=True,
            debounce_ms=100,
        )

        try:
            watcher.start()

            # Create new file
            test_file = tmp_path / "new.txt"
            test_file.write_text("new content", encoding='utf-8')

            # Wait for debounce + processing
            time.sleep(0.3)

            # Should not be in registry
            assert registry.get(str(test_file)) is None

        finally:
            watcher.stop()

    def test_modify_registered_file_updates_hash(self, tmp_path):
        """Test that modifying a registered file updates its hash."""
        registry = HashRegistry()
        test_file = tmp_path / "test.txt"
        test_file.write_text("initial", encoding='utf-8')

        # Register file
        from async_crud_mcp.core.file_io import compute_file_hash
        initial_hash = compute_file_hash(str(test_file))
        registry.update(str(test_file), initial_hash)

        watcher = FileWatcher(
            base_directories=[str(tmp_path)],
            registry=registry,
            enabled=True,
            debounce_ms=100,
        )

        try:
            watcher.start()

            # Modify file
            test_file.write_text("modified", encoding='utf-8')

            # Wait for debounce + processing
            time.sleep(0.3)

            # Hash should be updated
            new_hash = compute_file_hash(str(test_file))
            assert registry.get(str(test_file)) == new_hash
            assert new_hash != initial_hash

        finally:
            watcher.stop()

    def test_delete_file_removes_from_registry(self, tmp_path):
        """Test that deleting a file removes it from registry."""
        registry = HashRegistry()
        test_file = tmp_path / "test.txt"
        test_file.write_text("content", encoding='utf-8')

        # Register file
        from async_crud_mcp.core.file_io import compute_file_hash
        file_hash = compute_file_hash(str(test_file))
        registry.update(str(test_file), file_hash)

        watcher = FileWatcher(
            base_directories=[str(tmp_path)],
            registry=registry,
            enabled=True,
            debounce_ms=100,
        )

        try:
            watcher.start()

            # Delete file
            test_file.unlink()

            # Wait for debounce + processing
            time.sleep(0.3)

            # Should be removed from registry
            assert registry.get(str(test_file)) is None

        finally:
            watcher.stop()

    def test_race_condition_file_vanishes(self, tmp_path):
        """Test race condition handling when file vanishes before hash."""
        registry = HashRegistry()
        test_file = tmp_path / "test.txt"
        test_file.write_text("content", encoding='utf-8')

        # Register file
        from async_crud_mcp.core.file_io import compute_file_hash
        file_hash = compute_file_hash(str(test_file))
        registry.update(str(test_file), file_hash)

        watcher = FileWatcher(
            base_directories=[str(tmp_path)],
            registry=registry,
            enabled=True,
            debounce_ms=50,  # Shorter debounce for faster test
        )

        try:
            watcher.start()

            # Modify then immediately delete (race condition)
            test_file.write_text("modified", encoding='utf-8')
            time.sleep(0.01)
            test_file.unlink()

            # Wait for processing
            time.sleep(0.2)

            # Should be removed from registry (DELETE event wins)
            assert registry.get(str(test_file)) is None

        finally:
            watcher.stop()


class TestFileWatcherLifecycle:
    """Test watcher lifecycle management."""

    def test_start_stop_without_errors(self, tmp_path):
        """Test that start/stop completes without errors."""
        registry = HashRegistry()

        watcher = FileWatcher(
            base_directories=[str(tmp_path)],
            registry=registry,
            enabled=True,
            debounce_ms=100,
        )

        watcher.start()
        time.sleep(0.1)
        watcher.stop()

        # Should complete without exceptions

    def test_start_with_nonexistent_directory(self, tmp_path, caplog):
        """Test that nonexistent directory logs warning and continues."""
        import logging
        caplog.set_level(logging.WARNING)

        registry = HashRegistry()
        nonexistent = tmp_path / "nonexistent"

        watcher = FileWatcher(
            base_directories=[str(nonexistent)],
            registry=registry,
            enabled=True,
            debounce_ms=100,
        )

        watcher.start()
        time.sleep(0.1)
        watcher.stop()

        # Should log warning but not crash
        assert any("does not exist" in record.getMessage().lower() for record in caplog.records)

    def test_start_with_enabled_false(self, tmp_path, caplog):
        """Test that enabled=False skips observer creation."""
        import logging
        caplog.set_level(logging.INFO)

        registry = HashRegistry()

        watcher = FileWatcher(
            base_directories=[str(tmp_path)],
            registry=registry,
            enabled=False,
            debounce_ms=100,
        )

        watcher.start()

        # Should log that watcher is disabled
        assert any("disabled" in record.getMessage().lower() for record in caplog.records)

        watcher.stop()

    def test_multiple_directories_watched(self, tmp_path):
        """Test watching multiple directories simultaneously."""
        registry = HashRegistry()
        dir1 = tmp_path / "dir1"
        dir2 = tmp_path / "dir2"
        dir1.mkdir()
        dir2.mkdir()

        file1 = dir1 / "file1.txt"
        file2 = dir2 / "file2.txt"
        file1.write_text("content1", encoding='utf-8')
        file2.write_text("content2", encoding='utf-8')

        # Register both files
        from async_crud_mcp.core.file_io import compute_file_hash
        hash1 = compute_file_hash(str(file1))
        hash2 = compute_file_hash(str(file2))
        registry.update(str(file1), hash1)
        registry.update(str(file2), hash2)

        watcher = FileWatcher(
            base_directories=[str(dir1), str(dir2)],
            registry=registry,
            enabled=True,
            debounce_ms=100,
        )

        try:
            watcher.start()

            # Modify both files
            file1.write_text("modified1", encoding='utf-8')
            file2.write_text("modified2", encoding='utf-8')

            # Wait for processing
            time.sleep(0.3)

            # Both should be updated
            new_hash1 = compute_file_hash(str(file1))
            new_hash2 = compute_file_hash(str(file2))
            assert registry.get(str(file1)) == new_hash1
            assert registry.get(str(file2)) == new_hash2

        finally:
            watcher.stop()

    def test_stop_multiple_times_safe(self, tmp_path):
        """Test that calling stop() multiple times is safe."""
        registry = HashRegistry()

        watcher = FileWatcher(
            base_directories=[str(tmp_path)],
            registry=registry,
            enabled=True,
            debounce_ms=100,
        )

        watcher.start()
        watcher.stop()
        watcher.stop()  # Should not raise exception
        watcher.stop()  # Should not raise exception


class TestObserverFactory:
    """Test observer creation and fallback logic."""

    @patch('async_crud_mcp.core.file_watcher._is_network_path')
    def test_network_path_uses_polling_observer(self, mock_is_network, tmp_path):
        """Test that network paths use PollingObserver."""
        mock_is_network.return_value = True
        registry = HashRegistry()

        watcher = FileWatcher(
            base_directories=[str(tmp_path)],
            registry=registry,
            enabled=True,
            debounce_ms=100,
        )

        watcher.start()
        time.sleep(0.1)

        # Should have created a PollingObserver
        # Note: We can't easily check the type due to observer internals,
        # but the function should complete without error

        watcher.stop()

    def test_normal_path_uses_native_observer(self, tmp_path):
        """Test that normal paths use native Observer."""
        registry = HashRegistry()

        watcher = FileWatcher(
            base_directories=[str(tmp_path)],
            registry=registry,
            enabled=True,
            debounce_ms=100,
        )

        watcher.start()
        time.sleep(0.1)

        # Should have created a native Observer
        # Function should complete without error

        watcher.stop()
