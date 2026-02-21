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
    """macOS launchd implementation using launchctl.

    Manages the daemon using macOS launchd by delegating to the
    launchd_installer.sh script located in the macos subdirectory.
    The script creates plist files in ~/Library/LaunchAgents and uses
    launchctl commands for service management.
    """

    def _get_script_path(self) -> str:
        """Get the absolute path to the launchd_installer.sh script."""
        import os
        script_dir = os.path.dirname(os.path.abspath(__file__))
        return os.path.join(script_dir, 'macos', 'launchd_installer.sh')

    def _run_script(self, command: str) -> subprocess.CompletedProcess:
        """Run the launchd installer script with the given command.

        Args:
            command: Command to pass to the script (install, uninstall, etc.)

        Returns:
            CompletedProcess with the result

        Raises:
            subprocess.CalledProcessError: If the script fails
            FileNotFoundError: If the script doesn't exist
        """
        script_path = self._get_script_path()
        return subprocess.run(
            ['bash', script_path, command],
            capture_output=True,
            text=True,
            check=True,
        )

    def install(self, **kwargs) -> None:
        """Install the macOS LaunchAgent.

        Delegates to launchd_installer.sh which will:
        - Detect the async-crud-mcp bootstrap path
        - Create required directories
        - Generate the plist file with resolved paths
        - Load the LaunchAgent using launchctl

        Raises:
            subprocess.CalledProcessError: If installation fails
        """
        self._run_script('install')

    def uninstall(self) -> None:
        """Uninstall the macOS LaunchAgent.

        Delegates to launchd_installer.sh which will:
        - Unload the LaunchAgent using launchctl
        - Remove the plist file

        Raises:
            subprocess.CalledProcessError: If uninstallation fails
        """
        self._run_script('uninstall')

    def start(self) -> None:
        """Start the macOS LaunchAgent.

        Delegates to launchd_installer.sh which will load the plist.

        Raises:
            subprocess.CalledProcessError: If start fails
        """
        self._run_script('start')

    def stop(self) -> None:
        """Stop the macOS LaunchAgent.

        Delegates to launchd_installer.sh which will unload the plist.

        Raises:
            subprocess.CalledProcessError: If stop fails
        """
        self._run_script('stop')

    def status(self) -> str:
        """Get the current status of the macOS LaunchAgent.

        Returns:
            str: 'RUNNING', 'STOPPED', or 'UNKNOWN'
        """
        try:
            result = self._run_script('status')
            if 'RUNNING' in result.stdout:
                return 'RUNNING'
            elif 'STOPPED' in result.stdout:
                return 'STOPPED'
            return 'UNKNOWN'
        except subprocess.CalledProcessError:
            return 'UNKNOWN'

    def list(self) -> list[str]:
        """List all LaunchAgents matching APP_NAME.

        Returns:
            list[str]: List of matching LaunchAgent labels
        """
        try:
            result = subprocess.run(
                ['launchctl', 'list'],
                capture_output=True,
                text=True,
                check=True,
            )
            agents = []
            for line in result.stdout.splitlines():
                if APP_NAME in line:
                    parts = line.split()
                    if len(parts) >= 3:
                        agents.append(parts[2])
            return agents
        except subprocess.CalledProcessError:
            return []


class SystemdInstaller(InstallerBase):
    """Linux systemd implementation using systemctl --user.

    Manages the daemon using systemd user services by delegating to the
    systemd_installer.sh script located in the linux subdirectory.
    The script creates unit files in ~/.config/systemd/user/ and uses
    systemctl --user commands for service management.
    """

    def _get_script_path(self) -> str:
        """Get the absolute path to the systemd_installer.sh script."""
        import os
        script_dir = os.path.dirname(os.path.abspath(__file__))
        return os.path.join(script_dir, 'linux', 'systemd_installer.sh')

    def _run_script(self, command: str) -> subprocess.CompletedProcess:
        """Run the systemd installer script with the given command.

        Args:
            command: Command to pass to the script (install, uninstall, etc.)

        Returns:
            CompletedProcess with the result

        Raises:
            subprocess.CalledProcessError: If the script fails
            FileNotFoundError: If the script doesn't exist
        """
        script_path = self._get_script_path()
        return subprocess.run(
            ['bash', script_path, command],
            capture_output=True,
            text=True,
            check=True,
        )

    def _service_name(self) -> str:
        """Get the systemd unit name."""
        return f'{SERVICE_NAME}.service'

    def install(self, **kwargs) -> None:
        """Install the systemd user service.

        Delegates to systemd_installer.sh which will:
        - Detect the async-crud-mcp bootstrap path
        - Create required XDG-compliant directories
        - Generate the service unit file with resolved paths
        - Reload systemd, enable and start the service

        Raises:
            subprocess.CalledProcessError: If installation fails
        """
        self._run_script('install')

    def uninstall(self) -> None:
        """Uninstall the systemd user service.

        Delegates to systemd_installer.sh which will:
        - Stop the service if running
        - Disable the service
        - Remove the unit file
        - Reload systemd

        Raises:
            subprocess.CalledProcessError: If uninstallation fails
        """
        self._run_script('uninstall')

    def start(self) -> None:
        """Start the systemd user service.

        Delegates to systemd_installer.sh which uses systemctl --user start.

        Raises:
            subprocess.CalledProcessError: If start fails
        """
        self._run_script('start')

    def stop(self) -> None:
        """Stop the systemd user service.

        Delegates to systemd_installer.sh which uses systemctl --user stop.

        Raises:
            subprocess.CalledProcessError: If stop fails
        """
        self._run_script('stop')

    def status(self) -> str:
        """Get the current status of the systemd user service.

        Returns:
            str: 'RUNNING', 'STOPPED', or 'UNKNOWN'
        """
        try:
            result = subprocess.run(
                ['systemctl', '--user', 'is-active', self._service_name()],
                capture_output=True,
                text=True,
                check=False,
            )
            status = result.stdout.strip()
            if status == 'active':
                return 'RUNNING'
            elif status in ('inactive', 'failed'):
                return 'STOPPED'
            return 'UNKNOWN'
        except subprocess.CalledProcessError:
            return 'UNKNOWN'

    def list(self) -> list[str]:
        """List all systemd user services matching APP_NAME.

        Returns:
            list[str]: List of matching service unit names
        """
        try:
            result = subprocess.run(
                ['systemctl', '--user', 'list-units', '--all', '--no-pager', '--no-legend'],
                capture_output=True,
                text=True,
                check=True,
            )
            services = []
            for line in result.stdout.splitlines():
                if APP_NAME in line and '.service' in line:
                    parts = line.split()
                    if parts:
                        services.append(parts[0])
            return services
        except subprocess.CalledProcessError:
            return []


def get_installer(username: str | None = None) -> InstallerBase:
    """Factory function to get the appropriate platform-specific installer.

    Args:
        username: Optional username for per-user service installation

    Returns:
        InstallerBase: Platform-specific installer instance
    """
    if sys.platform == 'win32':
        installer = WindowsServiceInstaller()
    elif sys.platform == 'darwin':
        installer = LaunchdInstaller()
    else:
        installer = SystemdInstaller()

    # Store username for future use by platform implementations
    installer._username = username  # type: ignore
    return installer
