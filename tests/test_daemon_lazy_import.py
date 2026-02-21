"""Tests for daemon __init__ module imports (ADR-016: Eager imports).

Verifies that importing the daemon package correctly loads cross-platform
modules eagerly, and that Windows-specific modules are conditionally
imported based on sys.platform.

ADR-016: Flat daemon module layout with eager conditional imports.
No lazy __getattr__ pattern, no platform subpackages.
"""

import importlib
import sys

import pytest


class TestDaemonEagerInit:
    """Test that daemon/__init__.py uses eager imports (ADR-016)."""

    def test_import_daemon_loads_cross_platform_modules(self):
        """Importing the daemon package should eagerly load cross-platform modules."""
        to_remove = [k for k in sys.modules if k.startswith('async_crud_mcp.daemon')]
        for key in to_remove:
            del sys.modules[key]

        try:
            importlib.import_module('async_crud_mcp.daemon')

            # Cross-platform modules should be eagerly loaded
            cross_platform = [
                'async_crud_mcp.daemon.bootstrap_daemon',
                'async_crud_mcp.daemon.config_init',
                'async_crud_mcp.daemon.config_watcher',
                'async_crud_mcp.daemon.graceful_shutdown',
                'async_crud_mcp.daemon.health',
                'async_crud_mcp.daemon.installer',
                'async_crud_mcp.daemon.logging_setup',
                'async_crud_mcp.daemon.paths',
                'async_crud_mcp.daemon.session_detector',
            ]

            for mod_name in cross_platform:
                assert mod_name in sys.modules, (
                    f"{mod_name} should be eagerly imported by daemon/__init__.py (ADR-016)"
                )
        finally:
            to_remove = [k for k in sys.modules if k.startswith('async_crud_mcp.daemon')]
            for key in to_remove:
                del sys.modules[key]

    def test_no_lazy_getattr(self):
        """daemon/__init__.py must NOT have __getattr__ (ADR-016: prohibited pattern)."""
        to_remove = [k for k in sys.modules if k.startswith('async_crud_mcp.daemon')]
        for key in to_remove:
            del sys.modules[key]

        try:
            daemon = importlib.import_module('async_crud_mcp.daemon')
            # __getattr__ should not be defined as a module-level function
            assert not hasattr(daemon, '_LAZY_IMPORTS'), (
                "daemon/__init__.py must not have _LAZY_IMPORTS (ADR-016)"
            )
        finally:
            to_remove = [k for k in sys.modules if k.startswith('async_crud_mcp.daemon')]
            for key in to_remove:
                del sys.modules[key]

    def test_all_exports_are_accessible(self):
        """Every name in __all__ should be directly accessible."""
        to_remove = [k for k in sys.modules if k.startswith('async_crud_mcp.daemon')]
        for key in to_remove:
            del sys.modules[key]

        try:
            daemon = importlib.import_module('async_crud_mcp.daemon')
            for name in daemon.__all__:
                assert hasattr(daemon, name), (
                    f"{name} is in __all__ but not accessible on the module"
                )
        finally:
            to_remove = [k for k in sys.modules if k.startswith('async_crud_mcp.daemon')]
            for key in to_remove:
                del sys.modules[key]

    def test_unknown_attribute_raises(self):
        """Accessing a nonexistent name raises AttributeError."""
        to_remove = [k for k in sys.modules if k.startswith('async_crud_mcp.daemon')]
        for key in to_remove:
            del sys.modules[key]

        try:
            daemon = importlib.import_module('async_crud_mcp.daemon')
            with pytest.raises(AttributeError):
                _ = daemon.nonexistent_attribute
        finally:
            to_remove = [k for k in sys.modules if k.startswith('async_crud_mcp.daemon')]
            for key in to_remove:
                del sys.modules[key]


class TestFlatModuleLayout:
    """Test that daemon uses flat layout with no platform subpackages (ADR-016)."""

    def test_no_windows_subpackage(self):
        """daemon/windows/ subpackage must not exist."""
        from pathlib import Path
        daemon_dir = Path(__file__).parent.parent / 'src' / 'async_crud_mcp' / 'daemon'
        windows_pkg = daemon_dir / 'windows' / '__init__.py'
        assert not windows_pkg.exists(), (
            "daemon/windows/__init__.py must not exist (ADR-016: flat layout)"
        )

    def test_no_linux_subpackage(self):
        """daemon/linux/__init__.py must not exist as a Python package."""
        from pathlib import Path
        daemon_dir = Path(__file__).parent.parent / 'src' / 'async_crud_mcp' / 'daemon'
        linux_pkg = daemon_dir / 'linux' / '__init__.py'
        assert not linux_pkg.exists(), (
            "daemon/linux/__init__.py must not exist (ADR-016: flat layout)"
        )

    def test_no_macos_subpackage(self):
        """daemon/macos/__init__.py must not exist as a Python package."""
        from pathlib import Path
        daemon_dir = Path(__file__).parent.parent / 'src' / 'async_crud_mcp' / 'daemon'
        macos_pkg = daemon_dir / 'macos' / '__init__.py'
        assert not macos_pkg.exists(), (
            "daemon/macos/__init__.py must not exist (ADR-016: flat layout)"
        )


@pytest.mark.skipif(sys.platform != 'win32', reason="Windows-only test")
class TestWindowsEagerImports:
    """Test that Windows-specific modules are eagerly loaded on Windows."""

    def test_windows_modules_loaded_on_windows(self):
        """On Windows, dispatcher and windows_service should be eagerly loaded."""
        to_remove = [k for k in sys.modules if k.startswith('async_crud_mcp.daemon')]
        for key in to_remove:
            del sys.modules[key]

        try:
            importlib.import_module('async_crud_mcp.daemon')

            # On Windows with pywin32, these should be eagerly loaded
            assert 'async_crud_mcp.daemon.windows_service' in sys.modules, (
                "windows_service should be eagerly imported on Windows (ADR-016)"
            )
            assert 'async_crud_mcp.daemon.dispatcher' in sys.modules, (
                "dispatcher should be eagerly imported on Windows (ADR-016)"
            )
        finally:
            to_remove = [k for k in sys.modules if k.startswith('async_crud_mcp.daemon')]
            for key in to_remove:
                del sys.modules[key]

    def test_windows_service_does_not_directly_import_dispatcher(self):
        """windows_service.py itself should not import dispatcher at module level.

        Note: importing async_crud_mcp.daemon.windows_service triggers
        daemon/__init__.py which eagerly imports dispatcher (ADR-016).
        This test verifies the windows_service MODULE doesn't have a direct
        dependency on dispatcher (it uses a local import in SvcDoRun).
        """
        to_remove = [k for k in sys.modules if k.startswith('async_crud_mcp.daemon')]
        for key in to_remove:
            del sys.modules[key]

        try:
            mod = importlib.import_module('async_crud_mcp.daemon.windows_service')
            # Check module source doesn't have top-level dispatcher import
            import inspect
            source = inspect.getsource(mod)
            # The only dispatcher import should be inside SvcDoRun (local import)
            lines = source.split('\n')
            top_level_dispatcher_imports = [
                line for line in lines
                if 'from .dispatcher' in line or 'import dispatcher' in line
                if not line.strip().startswith('#')
                if not any(line.startswith(' ' * i) for i in range(4, 20))
            ]
            assert len(top_level_dispatcher_imports) == 0, (
                "windows_service.py should not have top-level dispatcher imports"
            )
        finally:
            to_remove = [k for k in sys.modules if k.startswith('async_crud_mcp.daemon')]
            for key in to_remove:
                del sys.modules[key]
