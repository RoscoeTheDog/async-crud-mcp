"""Tests for async_update tool."""

import asyncio
import tempfile
from pathlib import Path

import pytest

from async_crud_mcp.core import HashRegistry, LockManager, PathValidator, compute_hash
from async_crud_mcp.core.content_scanner import ContentScanner
from async_crud_mcp.models import AsyncUpdateRequest, ErrorCode, Patch, RegexPatch
from async_crud_mcp.tools import async_update


@pytest.fixture
def temp_base_dir():
    """Create a temporary base directory for tests."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def path_validator(temp_base_dir):
    """Create PathValidator with temp base directory."""
    return PathValidator(base_directories=[str(temp_base_dir)])


@pytest.fixture
def lock_manager():
    """Create LockManager instance."""
    return LockManager()


@pytest.fixture
def hash_registry():
    """Create HashRegistry instance."""
    return HashRegistry()


def create_file_with_hash(file_path: Path, content: str) -> str:
    """Helper to create a file and return its hash.

    Uses binary write to avoid platform-specific line ending conversion.
    """
    encoded_bytes = content.encode('utf-8')
    file_path.write_bytes(encoded_bytes)
    file_hash = compute_hash(encoded_bytes)
    return file_hash


class TestAsyncUpdateRedactionGuard:
    """async_update rejects redacted read-output via content mode (livetest F7)."""

    @pytest.mark.asyncio
    async def test_content_with_placeholder_rejected(self, temp_base_dir, path_validator, lock_manager, hash_registry):
        file_path = temp_base_dir / "u_guard.txt"
        h = create_file_with_hash(file_path, 'api_key = "real-secret-value-123"\n')
        request = AsyncUpdateRequest(
            path=str(file_path), expected_hash=h,
            content="api_key = <<REDACTED:generic-api-key-assignment:1>>\n",
        )
        response = await async_update(request, path_validator, lock_manager, hash_registry)
        assert response.status == "error"
        assert response.error_code == ErrorCode.REDACTION_MARKERS_PRESENT
        # original file untouched
        assert file_path.read_text() == 'api_key = "real-secret-value-123"\n'

    @pytest.mark.asyncio
    async def test_content_with_placeholder_override_allowed(self, temp_base_dir, path_validator, lock_manager, hash_registry):
        file_path = temp_base_dir / "u_guard_ok.txt"
        h = create_file_with_hash(file_path, "before\n")
        new_content = "literal <<REDACTED:rule:1>> doc\n"
        request = AsyncUpdateRequest(
            path=str(file_path), expected_hash=h, content=new_content, allow_redaction_markers=True,
        )
        response = await async_update(request, path_validator, lock_manager, hash_registry)
        assert response.status == "ok"
        assert file_path.read_text() == new_content

    @pytest.mark.asyncio
    async def test_patches_path_unaffected_by_guard(self, temp_base_dir, path_validator, lock_manager, hash_registry):
        # The guard targets content mode only; patches remain the safe edit path.
        file_path = temp_base_dir / "u_patch.txt"
        h = create_file_with_hash(file_path, "alpha beta gamma\n")
        request = AsyncUpdateRequest(
            path=str(file_path), expected_hash=h,
            patches=[Patch(old_string="beta", new_string="BETA")],
        )
        response = await async_update(request, path_validator, lock_manager, hash_registry)
        assert response.status == "ok"
        assert file_path.read_text() == "alpha BETA gamma\n"


class TestAsyncUpdateContentSuccess:
    """Test successful full content replacement."""

    @pytest.mark.asyncio
    async def test_update_existing_file(self, temp_base_dir, path_validator, lock_manager, hash_registry):
        """Test successful update with full content replacement. AC-9.2"""
        file_path = temp_base_dir / "update_test.txt"
        original_content = "Original content"
        new_content = "New content after update"

        original_hash = create_file_with_hash(file_path, original_content)

        request = AsyncUpdateRequest(
            path=str(file_path),
            expected_hash=original_hash,
            content=new_content
        )

        response = await async_update(request, path_validator, lock_manager, hash_registry)

        assert response.status == "ok"
        assert response.path == str(file_path)
        assert response.previous_hash == original_hash
        assert response.hash != original_hash
        assert response.bytes_written == len(new_content.encode('utf-8'))

    @pytest.mark.asyncio
    async def test_update_returns_previous_and_new_hash(self, temp_base_dir, path_validator, lock_manager, hash_registry):
        """Verify previous_hash matches original, hash matches new content. AC-9.2"""
        file_path = temp_base_dir / "hash_test.txt"
        original_content = "Original"
        new_content = "Updated"

        original_hash = create_file_with_hash(file_path, original_content)
        expected_new_hash = compute_hash(new_content.encode('utf-8'))

        request = AsyncUpdateRequest(
            path=str(file_path),
            expected_hash=original_hash,
            content=new_content
        )

        response = await async_update(request, path_validator, lock_manager, hash_registry)

        assert response.status == "ok"
        assert response.previous_hash == original_hash  # type: ignore
        assert response.hash == expected_new_hash  # type: ignore

    @pytest.mark.asyncio
    async def test_update_writes_content_to_disk(self, temp_base_dir, path_validator, lock_manager, hash_registry):
        """Verify file on disk matches new content after update. AC-9.2"""
        file_path = temp_base_dir / "disk_test.txt"
        original_content = "Before update"
        new_content = "After update"

        original_hash = create_file_with_hash(file_path, original_content)

        request = AsyncUpdateRequest(
            path=str(file_path),
            expected_hash=original_hash,
            content=new_content
        )

        response = await async_update(request, path_validator, lock_manager, hash_registry)

        assert response.status == "ok"
        assert file_path.read_text(encoding='utf-8') == new_content

    @pytest.mark.asyncio
    async def test_update_updates_hash_registry(self, temp_base_dir, path_validator, lock_manager, hash_registry):
        """Verify HashRegistry is updated with new hash. AC-9.2"""
        file_path = temp_base_dir / "registry_test.txt"
        original_content = "Registry test original"
        new_content = "Registry test updated"

        original_hash = create_file_with_hash(file_path, original_content)

        request = AsyncUpdateRequest(
            path=str(file_path),
            expected_hash=original_hash,
            content=new_content
        )

        response = await async_update(request, path_validator, lock_manager, hash_registry)

        assert response.status == "ok"
        registered_hash = hash_registry.get(str(file_path))
        assert registered_hash == response.hash

    @pytest.mark.asyncio
    async def test_update_bytes_written_correct(self, temp_base_dir, path_validator, lock_manager, hash_registry):
        """Verify bytes_written matches encoded content length. AC-9.2"""
        file_path = temp_base_dir / "bytes_test.txt"
        original_content = "Original"
        new_content = "New content with unicode: café ☕"

        original_hash = create_file_with_hash(file_path, original_content)

        request = AsyncUpdateRequest(
            path=str(file_path),
            expected_hash=original_hash,
            content=new_content,
            encoding="utf-8"
        )

        response = await async_update(request, path_validator, lock_manager, hash_registry)

        assert response.status == "ok"
        assert response.bytes_written == len(new_content.encode('utf-8'))


class TestAsyncUpdatePatchSuccess:
    """Test successful patch mode updates."""

    @pytest.mark.asyncio
    async def test_single_patch_applied(self, temp_base_dir, path_validator, lock_manager, hash_registry):
        """Test single old_string/new_string patch is applied. AC-9.3"""
        file_path = temp_base_dir / "patch_single.txt"
        original_content = "Hello, World!"

        original_hash = create_file_with_hash(file_path, original_content)

        patches = [Patch(old_string="World", new_string="Universe")]
        request = AsyncUpdateRequest(
            path=str(file_path),
            expected_hash=original_hash,
            patches=patches
        )

        response = await async_update(request, path_validator, lock_manager, hash_registry)

        assert response.status == "ok"
        assert file_path.read_text(encoding='utf-8') == "Hello, Universe!"

    @pytest.mark.asyncio
    async def test_multiple_patches_applied_sequentially(self, temp_base_dir, path_validator, lock_manager, hash_registry):
        """Test multiple patches applied in order. AC-9.3"""
        file_path = temp_base_dir / "patch_multiple.txt"
        original_content = "Line 1\nLine 2\nLine 3"

        original_hash = create_file_with_hash(file_path, original_content)

        patches = [
            Patch(old_string="Line 1", new_string="First Line"),
            Patch(old_string="Line 2", new_string="Second Line"),
            Patch(old_string="Line 3", new_string="Third Line")
        ]
        request = AsyncUpdateRequest(
            path=str(file_path),
            expected_hash=original_hash,
            patches=patches
        )

        response = await async_update(request, path_validator, lock_manager, hash_registry)

        assert response.status == "ok"
        assert file_path.read_text(encoding='utf-8') == "First Line\nSecond Line\nThird Line"

    @pytest.mark.asyncio
    async def test_patch_replaces_first_occurrence(self, temp_base_dir, path_validator, lock_manager, hash_registry):
        """Verify only first match is replaced per patch. AC-9.3"""
        file_path = temp_base_dir / "patch_first.txt"
        original_content = "foo bar foo bar"

        original_hash = create_file_with_hash(file_path, original_content)

        patches = [Patch(old_string="foo", new_string="baz")]
        request = AsyncUpdateRequest(
            path=str(file_path),
            expected_hash=original_hash,
            patches=patches
        )

        response = await async_update(request, path_validator, lock_manager, hash_registry)

        assert response.status == "ok"
        # Only first "foo" should be replaced
        assert file_path.read_text(encoding='utf-8') == "baz bar foo bar"


class TestAsyncUpdateContention:
    """Test hash mismatch and contention responses."""

    @pytest.mark.asyncio
    async def test_contention_on_hash_mismatch_content_mode(self, temp_base_dir, path_validator, lock_manager, hash_registry):
        """Test ContentionResponse when file hash doesn't match (content mode). AC-9.1, AC-9.4"""
        file_path = temp_base_dir / "contention_content.txt"
        original_content = "Original"

        original_hash = create_file_with_hash(file_path, original_content)

        # Simulate external modification
        file_path.write_text("Externally modified", encoding='utf-8')

        request = AsyncUpdateRequest(
            path=str(file_path),
            expected_hash=original_hash,
            content="Agent's intended update"
        )

        response = await async_update(request, path_validator, lock_manager, hash_registry)

        assert response.status == "contention"
        assert response.expected_hash == original_hash
        assert response.current_hash != original_hash
        assert response.path == str(file_path)
        assert "modified" in response.message.lower()
        assert hasattr(response, 'diff')

        # File should be unchanged
        assert file_path.read_text(encoding='utf-8') == "Externally modified"

    @pytest.mark.asyncio
    async def test_contention_json_diff_format(self, temp_base_dir, path_validator, lock_manager, hash_registry):
        """Verify JSON diff structure in contention response. AC-9.4"""
        file_path = temp_base_dir / "contention_json.txt"
        original_content = "Line 1\nLine 2"

        original_hash = create_file_with_hash(file_path, original_content)

        # External modification
        file_path.write_text("Line 1\nModified Line 2", encoding='utf-8')

        request = AsyncUpdateRequest(
            path=str(file_path),
            expected_hash=original_hash,
            content="Agent content",
            diff_format="json"
        )

        response = await async_update(request, path_validator, lock_manager, hash_registry)

        assert response.status == "contention"
        assert response.diff.format == "json"
        assert hasattr(response.diff, 'changes')

    @pytest.mark.asyncio
    async def test_contention_unified_diff_format(self, temp_base_dir, path_validator, lock_manager, hash_registry):
        """Verify unified diff format in contention response. AC-9.4"""
        file_path = temp_base_dir / "contention_unified.txt"
        original_content = "Original line"

        original_hash = create_file_with_hash(file_path, original_content)

        # External modification
        file_path.write_text("Modified line", encoding='utf-8')

        request = AsyncUpdateRequest(
            path=str(file_path),
            expected_hash=original_hash,
            content="Agent line",
            diff_format="unified"
        )

        response = await async_update(request, path_validator, lock_manager, hash_registry)

        assert response.status == "contention"
        assert response.diff.format == "unified"
        assert hasattr(response.diff, 'content')
        assert isinstance(response.diff.content, str)

    @pytest.mark.asyncio
    async def test_contention_patches_applicable_true(self, temp_base_dir, path_validator, lock_manager, hash_registry):
        """Test patches_applicable=True when all patches can still apply. AC-9.5"""
        file_path = temp_base_dir / "contention_patches_ok.txt"
        original_content = "Line 1\nLine 2\nLine 3"

        original_hash = create_file_with_hash(file_path, original_content)

        # External modification that doesn't conflict with patches
        file_path.write_text("Line 1\nLine 2\nLine 3\nLine 4", encoding='utf-8')

        patches = [Patch(old_string="Line 1", new_string="First")]
        request = AsyncUpdateRequest(
            path=str(file_path),
            expected_hash=original_hash,
            patches=patches
        )

        response = await async_update(request, path_validator, lock_manager, hash_registry)

        assert response.status == "contention"
        assert response.patches_applicable is True
        assert response.conflicts is None or (response.conflicts is not None and len(response.conflicts) == 0)

    @pytest.mark.asyncio
    async def test_contention_patches_applicable_false(self, temp_base_dir, path_validator, lock_manager, hash_registry):
        """Test patches_applicable=False when patches conflict. AC-9.5"""
        file_path = temp_base_dir / "contention_patches_conflict.txt"
        original_content = "Line 1\nLine 2"

        original_hash = create_file_with_hash(file_path, original_content)

        # External modification removes "Line 1"
        file_path.write_text("Different content\nLine 2", encoding='utf-8')

        patches = [Patch(old_string="Line 1", new_string="First")]
        request = AsyncUpdateRequest(
            path=str(file_path),
            expected_hash=original_hash,
            patches=patches
        )

        response = await async_update(request, path_validator, lock_manager, hash_registry)

        assert response.status == "contention"
        assert response.patches_applicable is False
        assert response.conflicts is not None
        assert len(response.conflicts) > 0
        assert response.conflicts[0].patch_index == 0

    @pytest.mark.asyncio
    async def test_contention_non_conflicting_patches(self, temp_base_dir, path_validator, lock_manager, hash_registry):
        """Test non_conflicting_patches returns correct indices. AC-9.5"""
        file_path = temp_base_dir / "contention_mixed.txt"
        original_content = "Line 1\nLine 2\nLine 3"

        original_hash = create_file_with_hash(file_path, original_content)

        # External modification removes "Line 2"
        file_path.write_text("Line 1\nLine 3", encoding='utf-8')

        patches = [
            Patch(old_string="Line 1", new_string="First"),  # Can apply
            Patch(old_string="Line 2", new_string="Second"),  # Cannot apply
            Patch(old_string="Line 3", new_string="Third")   # Can apply
        ]
        request = AsyncUpdateRequest(
            path=str(file_path),
            expected_hash=original_hash,
            patches=patches
        )

        response = await async_update(request, path_validator, lock_manager, hash_registry)

        assert response.status == "contention"
        assert response.patches_applicable is False
        assert response.non_conflicting_patches is not None
        assert 0 in response.non_conflicting_patches
        assert 2 in response.non_conflicting_patches
        assert response.conflicts is not None and len(response.conflicts) == 1

    @pytest.mark.asyncio
    async def test_contention_does_not_modify_file(self, temp_base_dir, path_validator, lock_manager, hash_registry):
        """Verify file is unchanged after contention. AC-9.1"""
        file_path = temp_base_dir / "contention_no_modify.txt"
        original_content = "Original"

        original_hash = create_file_with_hash(file_path, original_content)

        # External modification
        modified_content = "Externally modified"
        file_path.write_text(modified_content, encoding='utf-8')

        request = AsyncUpdateRequest(
            path=str(file_path),
            expected_hash=original_hash,
            content="Agent update"
        )

        response = await async_update(request, path_validator, lock_manager, hash_registry)

        assert response.status == "contention"
        # File should still have externally modified content
        assert file_path.read_text(encoding='utf-8') == modified_content


class TestAsyncUpdateErrors:
    """Test error conditions."""

    @pytest.mark.asyncio
    async def test_file_not_found(self, temp_base_dir, path_validator, lock_manager, hash_registry):
        """Test updating non-existent file returns FILE_NOT_FOUND. AC-9.1"""
        file_path = temp_base_dir / "nonexistent.txt"

        request = AsyncUpdateRequest(
            path=str(file_path),
            expected_hash="sha256:dummy",
            content="New content"
        )

        response = await async_update(request, path_validator, lock_manager, hash_registry)

        assert response.status == "error"
        assert response.error_code == ErrorCode.FILE_NOT_FOUND

    @pytest.mark.asyncio
    async def test_path_outside_base(self, temp_base_dir, path_validator, lock_manager, hash_registry):
        """Test path validation failure. AC-9.1"""
        file_path = "/etc/passwd"  # Outside base directory

        request = AsyncUpdateRequest(
            path=file_path,
            expected_hash="sha256:dummy",
            content="New content"
        )

        response = await async_update(request, path_validator, lock_manager, hash_registry)

        assert response.status == "error"
        assert response.error_code == ErrorCode.PATH_OUTSIDE_BASE

    @pytest.mark.asyncio
    async def test_invalid_patch_old_string_not_found(self, temp_base_dir, path_validator, lock_manager, hash_registry):
        """Test INVALID_PATCH when old_string not found during update. AC-9.3"""
        file_path = temp_base_dir / "invalid_patch.txt"
        original_content = "Line 1\nLine 2"

        original_hash = create_file_with_hash(file_path, original_content)

        patches = [
            Patch(old_string="Line 1", new_string="First"),
            Patch(old_string="NonexistentLine", new_string="Won't work")
        ]
        request = AsyncUpdateRequest(
            path=str(file_path),
            expected_hash=original_hash,
            patches=patches
        )

        response = await async_update(request, path_validator, lock_manager, hash_registry)

        assert response.status == "error"
        assert response.error_code == ErrorCode.INVALID_PATCH
        assert "NonexistentLine" in response.message

    @pytest.mark.asyncio
    async def test_lock_timeout(self, temp_base_dir, path_validator, lock_manager, hash_registry):
        """Test LOCK_TIMEOUT when lock is held. AC-9.1"""
        file_path = temp_base_dir / "locked.txt"
        original_content = "Content"

        original_hash = create_file_with_hash(file_path, original_content)

        # Acquire lock externally
        lock_id = await lock_manager.acquire_write(str(file_path), timeout=30.0)

        try:
            request = AsyncUpdateRequest(
                path=str(file_path),
                expected_hash=original_hash,
                content="New content",
                timeout=0.1  # Very short timeout
            )

            response = await async_update(request, path_validator, lock_manager, hash_registry)

            assert response.status == "error"
            assert response.error_code == ErrorCode.LOCK_TIMEOUT
        finally:
            await lock_manager.release_write(str(file_path), lock_id)

    @pytest.mark.asyncio
    async def test_content_or_patches_required(self, temp_base_dir, path_validator, lock_manager, hash_registry):
        """Test CONTENT_OR_PATCHES_REQUIRED (defense in depth). AC-9.6"""
        # This should be caught by Pydantic validation, but test defense in depth
        # We can't actually construct an invalid request through Pydantic,
        # so this test documents the expected behavior
        file_path = temp_base_dir / "test.txt"
        original_hash = create_file_with_hash(file_path, "content")

        # Pydantic will catch this during model construction
        with pytest.raises(ValueError, match="Exactly one of content, patches, or regex_patches must be provided"):
            AsyncUpdateRequest(
                path=str(file_path),
                expected_hash=original_hash,
                content=None,
                patches=None
            )


class TestAsyncUpdateConcurrency:
    """Test concurrent update operations."""

    @pytest.mark.asyncio
    async def test_exclusive_lock_blocks_concurrent_updates(self, temp_base_dir, path_validator, lock_manager, hash_registry):
        """Test that concurrent updates use exclusive locking. AC-9.1"""
        file_path = temp_base_dir / "concurrent.txt"
        original_content = "Original"

        original_hash = create_file_with_hash(file_path, original_content)

        request1 = AsyncUpdateRequest(
            path=str(file_path),
            expected_hash=original_hash,
            content="Update 1",
            timeout=5.0
        )

        request2 = AsyncUpdateRequest(
            path=str(file_path),
            expected_hash=original_hash,
            content="Update 2",
            timeout=0.5  # Short timeout
        )

        # Start both updates concurrently
        results = await asyncio.gather(
            async_update(request1, path_validator, lock_manager, hash_registry),
            async_update(request2, path_validator, lock_manager, hash_registry),
            return_exceptions=False
        )

        # One should succeed, one should timeout OR get contention
        statuses = [r.status for r in results]
        assert "ok" in statuses
        # The second one will either timeout or see a hash mismatch (contention)
        assert "error" in statuses or "contention" in statuses


class TestAsyncUpdateModifiedBy:
    """Test modified_by field in ContentionResponse."""

    @pytest.mark.asyncio
    async def test_modified_by_unknown_when_no_registry_entry(self, temp_base_dir, path_validator, lock_manager, hash_registry):
        """modified_by is 'unknown' when hash registry has no entry for the file."""
        file_path = temp_base_dir / "test.txt"
        original_hash = create_file_with_hash(file_path, "original")

        # Externally modify - registry has no entry since we never wrote via MCP
        file_path.write_bytes(b"modified externally")

        request = AsyncUpdateRequest(
            path=str(file_path),
            expected_hash=original_hash,
            content="agent update",
        )
        result = await async_update(request, path_validator, lock_manager, hash_registry)

        assert result.status == "contention"
        assert result.modified_by == "unknown"

    @pytest.mark.asyncio
    async def test_modified_by_agent_when_registry_matches(self, temp_base_dir, path_validator, lock_manager, hash_registry):
        """modified_by is 'agent' when registry hash matches current file hash."""
        file_path = temp_base_dir / "test.txt"
        original_hash = create_file_with_hash(file_path, "original")

        # Simulate another agent's write: update file AND registry
        new_content = b"written by another agent"
        file_path.write_bytes(new_content)
        new_hash = compute_hash(new_content)
        hash_registry.update(str(file_path), new_hash)

        request = AsyncUpdateRequest(
            path=str(file_path),
            expected_hash=original_hash,
            content="my update",
        )
        result = await async_update(request, path_validator, lock_manager, hash_registry)

        assert result.status == "contention"
        assert result.modified_by == "agent"
        assert "agent" in result.message

    @pytest.mark.asyncio
    async def test_modified_by_external_when_registry_stale(self, temp_base_dir, path_validator, lock_manager, hash_registry):
        """modified_by is 'external' when registry hash differs from current file hash."""
        file_path = temp_base_dir / "test.txt"
        original_content = b"original"
        original_hash = create_file_with_hash(file_path, "original")

        # Register the original hash in registry (simulating a prior MCP write)
        hash_registry.update(str(file_path), original_hash)

        # Then externally modify the file (user edit, git checkout, etc.)
        file_path.write_bytes(b"user edited this file")

        request = AsyncUpdateRequest(
            path=str(file_path),
            expected_hash=original_hash,
            content="agent update",
        )
        result = await async_update(request, path_validator, lock_manager, hash_registry)

        assert result.status == "contention"
        assert result.modified_by == "external"
        assert "external" in result.message


class TestAsyncUpdateRegexPatchSuccess:
    """Test regex patch mode."""

    @pytest.mark.asyncio
    async def test_single_regex_patch_applied(self, temp_base_dir, path_validator, lock_manager, hash_registry):
        """Test basic regex replacement."""
        file_path = temp_base_dir / "test.txt"
        original_content = "def foo_bar():\n    pass\n"
        original_hash = create_file_with_hash(file_path, original_content)

        request = AsyncUpdateRequest(
            path=str(file_path),
            expected_hash=original_hash,
            regex_patches=[RegexPatch(pattern=r"foo_bar", replacement="baz_qux")],
        )
        result = await async_update(request, path_validator, lock_manager, hash_registry)

        assert result.status == "ok"
        assert file_path.read_text(encoding="utf-8") == "def baz_qux():\n    pass\n"
        assert result.regex_applied is not None
        assert len(result.regex_applied) == 1
        assert result.regex_applied[0].matched == "foo_bar"
        assert result.regex_applied[0].replaced_with == "baz_qux"

    @pytest.mark.asyncio
    async def test_regex_patch_with_backreference(self, temp_base_dir, path_validator, lock_manager, hash_registry):
        """Test regex with capture group backreferences."""
        file_path = temp_base_dir / "test.txt"
        original_content = "def old_name(x):\n    return x\n"
        original_hash = create_file_with_hash(file_path, original_content)

        request = AsyncUpdateRequest(
            path=str(file_path),
            expected_hash=original_hash,
            regex_patches=[RegexPatch(pattern=r"def (\w+)\(", replacement=r"def new_\1(")],
        )
        result = await async_update(request, path_validator, lock_manager, hash_registry)

        assert result.status == "ok"
        assert "def new_old_name(" in file_path.read_text(encoding="utf-8")

    @pytest.mark.asyncio
    async def test_regex_patch_count_limits_replacements(self, temp_base_dir, path_validator, lock_manager, hash_registry):
        """Test that count parameter limits number of replacements."""
        file_path = temp_base_dir / "test.txt"
        original_content = "aaa bbb aaa bbb aaa\n"
        original_hash = create_file_with_hash(file_path, original_content)

        request = AsyncUpdateRequest(
            path=str(file_path),
            expected_hash=original_hash,
            regex_patches=[RegexPatch(pattern=r"aaa", replacement="ccc", count=2)],
        )
        result = await async_update(request, path_validator, lock_manager, hash_registry)

        assert result.status == "ok"
        content = file_path.read_text(encoding="utf-8")
        assert content.count("ccc") == 2
        assert content.count("aaa") == 1  # Third occurrence preserved

    @pytest.mark.asyncio
    async def test_regex_patch_no_match_returns_success_no_changes(self, temp_base_dir, path_validator, lock_manager, hash_registry):
        """Test regex with no matches still succeeds (no-op)."""
        file_path = temp_base_dir / "test.txt"
        original_content = "hello world\n"
        original_hash = create_file_with_hash(file_path, original_content)

        request = AsyncUpdateRequest(
            path=str(file_path),
            expected_hash=original_hash,
            regex_patches=[RegexPatch(pattern=r"nonexistent", replacement="replaced")],
        )
        result = await async_update(request, path_validator, lock_manager, hash_registry)

        assert result.status == "ok"
        assert file_path.read_text(encoding="utf-8") == original_content
        # No matches means no regex metadata
        assert result.regex_applied is None
        assert result.regex_blocked is None

    @pytest.mark.asyncio
    async def test_multiple_regex_patches(self, temp_base_dir, path_validator, lock_manager, hash_registry):
        """Test applying multiple regex patches sequentially."""
        file_path = temp_base_dir / "test.txt"
        original_content = "color=red\nflavour=sweet\n"
        original_hash = create_file_with_hash(file_path, original_content)

        request = AsyncUpdateRequest(
            path=str(file_path),
            expected_hash=original_hash,
            regex_patches=[
                RegexPatch(pattern=r"color", replacement="colour"),
                RegexPatch(pattern=r"red", replacement="blue"),
            ],
        )
        result = await async_update(request, path_validator, lock_manager, hash_registry)

        assert result.status == "ok"
        content = file_path.read_text(encoding="utf-8")
        assert "colour=blue" in content


class TestAsyncUpdateRegexPatchErrors:
    """Test regex patch error handling."""

    @pytest.mark.asyncio
    async def test_invalid_regex_pattern_rejected_before_lock(self, temp_base_dir, path_validator, lock_manager, hash_registry):
        """Test that invalid regex patterns fail before acquiring lock."""
        file_path = temp_base_dir / "test.txt"
        original_hash = create_file_with_hash(file_path, "content")

        request = AsyncUpdateRequest(
            path=str(file_path),
            expected_hash=original_hash,
            regex_patches=[RegexPatch(pattern=r"[invalid", replacement="x")],
        )
        result = await async_update(request, path_validator, lock_manager, hash_registry)

        assert result.status == "error"
        assert result.error_code == ErrorCode.INVALID_PATTERN
        assert "invalid regex pattern" in result.message

    def test_regex_patches_mutually_exclusive_with_content(self):
        """Test that regex_patches cannot be used with content."""
        with pytest.raises(ValueError, match="Exactly one of content, patches, or regex_patches"):
            AsyncUpdateRequest(
                path="test.txt",
                expected_hash="sha256:abc",
                content="new content",
                regex_patches=[RegexPatch(pattern="a", replacement="b")],
            )

    def test_regex_patches_mutually_exclusive_with_patches(self):
        """Test that regex_patches cannot be used with patches."""
        with pytest.raises(ValueError, match="Exactly one of content, patches, or regex_patches"):
            AsyncUpdateRequest(
                path="test.txt",
                expected_hash="sha256:abc",
                patches=[Patch(old_string="a", new_string="b")],
                regex_patches=[RegexPatch(pattern="a", replacement="b")],
            )


class TestAsyncUpdateRegexPatchContentScanner:
    """Test regex patch content scanner guard."""

    @pytest.fixture
    def content_scanner_with_deny(self):
        """Create a content scanner that blocks AWS key patterns."""
        from async_crud_mcp.config import ContentRule
        rules = [
            ContentRule(
                name="aws-access-key",
                pattern=r"AKIA[0-9A-Z]{16}",
                action="deny",
                priority=100,
            ),
        ]
        return ContentScanner(rules=rules, enabled=True)

    @pytest.mark.asyncio
    async def test_scanner_blocks_flagged_match(
        self, temp_base_dir, path_validator, lock_manager, hash_registry, content_scanner_with_deny
    ):
        """Test that regex matches containing sensitive content are blocked."""
        file_path = temp_base_dir / "config.txt"
        # Content with an AWS-like key that the scanner should flag
        original_content = "key=AKIAIOSFODNN7EXAMPLE\nname=test\n"
        original_hash = create_file_with_hash(file_path, original_content)

        request = AsyncUpdateRequest(
            path=str(file_path),
            expected_hash=original_hash,
            regex_patches=[RegexPatch(pattern=r"key=\S+", replacement="key=REDACTED")],
        )
        result = await async_update(
            request, path_validator, lock_manager, hash_registry,
            content_scanner=content_scanner_with_deny,
        )

        assert result.status == "ok"
        content = file_path.read_text(encoding="utf-8")
        # The match should have been blocked, so original content preserved at that position
        assert "AKIAIOSFODNN7EXAMPLE" in content
        assert result.regex_blocked is not None
        assert len(result.regex_blocked) == 1
        assert "aws-access-key" in result.regex_blocked[0].error

    @pytest.mark.asyncio
    async def test_scanner_allows_clean_match(
        self, temp_base_dir, path_validator, lock_manager, hash_registry, content_scanner_with_deny
    ):
        """Test that non-sensitive regex matches are applied normally."""
        file_path = temp_base_dir / "test.txt"
        original_content = "name=alice\nage=30\n"
        original_hash = create_file_with_hash(file_path, original_content)

        request = AsyncUpdateRequest(
            path=str(file_path),
            expected_hash=original_hash,
            regex_patches=[RegexPatch(pattern=r"name=(\w+)", replacement=r"name=bob")],
        )
        result = await async_update(
            request, path_validator, lock_manager, hash_registry,
            content_scanner=content_scanner_with_deny,
        )

        assert result.status == "ok"
        content = file_path.read_text(encoding="utf-8")
        assert "name=bob" in content
        assert result.regex_applied is not None
        assert len(result.regex_applied) == 1
        assert result.regex_blocked is None or len(result.regex_blocked) == 0
