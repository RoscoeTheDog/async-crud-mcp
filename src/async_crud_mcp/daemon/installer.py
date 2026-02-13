"""Platform-agnostic daemon installer interface.

This module provides a unified interface for installing, uninstalling, and
managing the async-crud-mcp daemon across different operating systems. It uses a
factory pattern to select the appropriate platform-specific installer.

Architecture:
    - InstallerBase: Abstract base class defining the installer interface
    - WindowsServiceInstaller: Windows implementation using Windows Services
    - LaunchdInstaller: macOS implementation skeleton (future)
    - SystemdInstaller: Linux implementation skeleton (future)
    - get_installer(): Factory function to get platform-specific installer

Placeholders:
    async-crud-mcp      - Lowercase-hyphenated app name (e.g., my-mcp-server)
    async_crud_mcp  - Python package name (e.g., my_mcp_server)

Example:
    >>> from installer import get_installer
    >>> installer = get_installer()
    >>> installer.install()
    >>> installer.start()
    >>> print(installer.status())
    'RUNNING'
"""

import subprocess
import sys
from abc import ABC, abstractmethod


APP_NAME = 'async-crud-mcp'
SERVICE_NAME = f'{APP_NAME}-daemon'


class InstallerBase(ABC):
    """Abstract base class for platform-specific daemon installers.

    All platform-specific installers must inherit from this class and
    implement all abstract methods. This ensures a consistent interface
    across platforms.
    """

    @abstractmethod
    def install(self, **kwargs) -> None:
        """Install the daemon service on the system.

        Registers the daemon with the system's service manager so it can
        be controlled and optionally configured to start at boot.

        Args:
            **kwargs: Platform-specific installation options

        Raises:
            OSError: If installation fails
        """
        pass

    @abstractmethod
    def uninstall(self) -> None:
        """Uninstall the daemon service from the system.

        Removes the daemon from the system's service manager.

        Raises:
            OSError: If uninstallation fails
        """
        pass

    @abstractmethod
    def start(self) -> None:
        """Start the daemon service.

        Raises:
            OSError: If start fails
        """
        pass

    @abstractmethod
    def stop(self) -> None:
        """Stop the daemon service.

        Raises:
            OSError: If stop fails
        """
        pass

    @abstractmethod
    def status(self) -> str:
        """Get the current status of the daemon service.

        Returns:
            str: Status string such as 'RUNNING', 'STOPPED', or 'UNKNOWN'
        """
        pass

    @abstractmethod
    def list(self) -> list[str]:
        """List all installed daemon instances.

        Returns:
            list[str]: List of service names or identifiers
        """
        pass


class WindowsServiceInstaller(InstallerBase):
    """Windows Service implementation of the daemon installer.

    Uses subprocess to call 'sc' commands for start/stop/status/list.
    Delegates install/uninstall to the windows_service module which uses
    direct win32service.CreateService() API (not HandleCommandLine).

    Security:
        All operations require administrator elevation (UAC prompt).
    """

    def _service_name(self) -> str:
        """Get the system-wide Windows service name."""
        return SERVICE_NAME

    def install(self, **kwargs) -> None:
        """Install the Windows service.

        Delegates to windows_service.install_service() which uses
        direct win32service.CreateService() API.

        Args:
            **kwargs: Passed to install_service()

        Raises:
            OSError: If installation fails (typically ACCESS_DENIED)
            ImportError: If pywin32 is not installed
        """
        from .windows_service import install_service
        install_service(**kwargs)

    def uninstall(self) -> None:
        """Uninstall the Windows service.

        Raises:
            OSError: If uninstallation fails
            ImportError: If pywin32 is not installed
        """
        from .windows_service import uninstall_service
        uninstall_service()

    def start(self) -> None:
        """Start the Windows service using 'sc start' command.

        Raises:
            subprocess.CalledProcessError: If sc command fails
        """
        subprocess.run(
            ['sc', 'start', self._service_name()],
            capture_output=True,
            text=True,
            check=True,
        )

    def stop(self) -> None:
        """Stop the Windows service using 'sc stop' command.

        Raises:
            subprocess.CalledProcessError: If sc command fails
        """
        subprocess.run(
            ['sc', 'stop', self._service_name()],
            capture_output=True,
            text=True,
            check=True,
        )

    def status(self) -> str:
        """Get the current status of the Windows service.

        Returns:
            str: 'RUNNING', 'STOPPED', or 'UNKNOWN'
        """
        try:
            result = subprocess.run(
                ['sc', 'query', self._service_name()],
                capture_output=True,
                text=True,
                check=True,
            )
            for line in result.stdout.splitlines():
                if 'STATE' in line:
                    if 'RUNNING' in line:
                        return 'RUNNING'
                    elif 'STOPPED' in line:
                        return 'STOPPED'
            return 'UNKNOWN'
        except subprocess.CalledProcessError:
            return 'UNKNOWN'

    def list(self) -> list[str]:
        """List all daemon services matching APP_NAME.

        Returns:
            list[str]: List of matching service names
        """
        try:
            result = subprocess.run(
                ['sc', 'query', 'type=', 'service', 'state=', 'all'],
                capture_output=True,
                text=True,
                check=True,
            )
            services = []
            for line in result.stdout.splitlines():
                if 'SERVICE_NAME' in line and APP_NAME in line:
                    parts = line.split(':', 1)
                    if len(parts) == 2:
                        services.append(parts[1].strip())
            return services
        except subprocess.CalledProcessError:
            return []


class LaunchdInstaller(InstallerBase):
    """macOS launchd implementation skeleton for future development.

    Will manage the daemon using macOS launchd by creating plist files
    in ~/Library/LaunchAgents and using launchctl commands.
    """

    def install(self, **kwargs) -> None:
        raise NotImplementedError("macOS launchd support is not yet implemented")

    def uninstall(self) -> None:
        raise NotImplementedError("macOS launchd support is not yet implemented")

    def start(self) -> None:
        raise NotImplementedError("macOS launchd support is not yet implemented")

    def stop(self) -> None:
        raise NotImplementedError("macOS launchd support is not yet implemented")

    def status(self) -> str:
        return "SKELETON_IMPLEMENTATION"

    def list(self) -> list[str]:
        return []


class SystemdInstaller(InstallerBase):
    """Linux systemd implementation skeleton for future development.

    Will manage the daemon using systemd user services by creating
    unit files in ~/.config/systemd/user/ and using systemctl --user.
    """

    def install(self, **kwargs) -> None:
        raise NotImplementedError("Linux systemd support is not yet implemented")

    def uninstall(self) -> None:
        raise NotImplementedError("Linux systemd support is not yet implemented")

    def start(self) -> None:
        raise NotImplementedError("Linux systemd support is not yet implemented")

    def stop(self) -> None:
        raise NotImplementedError("Linux systemd support is not yet implemented")

    def status(self) -> str:
        return "SKELETON_IMPLEMENTATION"

    def list(self) -> list[str]:
        return []


def get_installer() -> InstallerBase:
    """Factory function to get the appropriate platform-specific installer.

    Returns:
        InstallerBase: Platform-specific installer instance
    """
    if sys.platform == 'win32':
        return WindowsServiceInstaller()
    elif sys.platform == 'darwin':
        return LaunchdInstaller()
    else:
        return SystemdInstaller()
