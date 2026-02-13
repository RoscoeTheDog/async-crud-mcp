"""Install subcommand group for quick installation commands."""

import shutil
import sys
import typer

try:
    from rich.console import Console
    from rich.progress import Progress, SpinnerColumn, TextColumn
    _RICH_AVAILABLE = True
except ImportError:
    _RICH_AVAILABLE = False

from async_crud_mcp.daemon.config_init import init_config
from async_crud_mcp.daemon.installer import get_installer
from async_crud_mcp.daemon.paths import get_config_dir, get_config_file_path, get_logs_dir

app = typer.Typer(help="Quick installation commands")


def _get_console():
    """Get console object with fallback for missing Rich dependency."""
    if _RICH_AVAILABLE:
        return Console()

    class FallbackConsole:
        """Minimal console fallback when Rich is unavailable."""
        def print(self, text: str, **kwargs):
            # Strip Rich markup for plain output
            import re
            plain_text = re.sub(r'\[.*?\]', '', text)
            typer.echo(plain_text)

    return FallbackConsole()


console = _get_console()


def _is_admin() -> bool:
    """Check if running with administrator/root privileges.

    Returns:
        True if running as admin/root, False otherwise.
        On non-Windows platforms, returns True (no admin needed for user services).
    """
    if sys.platform != 'win32':
        return True  # Unix systems use user-level services (launchd/systemd --user)

    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


@app.command()
def quick_install(
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompts"),
    force: bool = typer.Option(False, "--force", help="Overwrite existing configuration"),
    port: int = typer.Option(None, "--port", help="Override default port (default: 8720)"),
    no_start: bool = typer.Option(False, "--no-start", help="Skip starting the daemon after installation")
):
    """Run full setup sequence: config init, install, and optionally start."""
    try:
        # Check for Windows admin privileges before service installation
        if sys.platform == 'win32' and not _is_admin():
            console.print("[red]Error: Administrator privileges required on Windows[/red]")
            console.print("[yellow]Please run this command from an elevated Command Prompt or PowerShell[/yellow]")
            raise typer.Exit(code=1)

        if not yes:
            confirm = typer.confirm("This will initialize config, install, and start the daemon. Continue?")
            if not confirm:
                console.print("[yellow]Installation cancelled[/yellow]")
                raise typer.Exit(code=0)

        if _RICH_AVAILABLE:
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=console,
            ) as progress:
                task = progress.add_task("Initializing configuration...", total=None)
                _do_quick_install(force, port, no_start, progress, task)
        else:
            _do_quick_install(force, port, no_start)

        console.print("\n[bold green]Quick installation complete![/bold green]")
        if not no_start:
            console.print("[dim]Use 'async-crud-mcp daemon status' to check daemon health[/dim]")

    except FileExistsError:
        console.print("[yellow]Config already exists, using existing config[/yellow]")
    except Exception as e:
        console.print(f"[red]Installation failed:[/red] {e}")
        raise typer.Exit(code=1)


def _do_quick_install(force: bool, port: int | None, no_start: bool, progress=None, task=None):
    """Execute quick installation steps.

    Args:
        force: Whether to overwrite existing configuration
        port: Optional port override
        no_start: Whether to skip starting the daemon
        progress: Optional Rich Progress instance
        task: Optional Rich task ID
    """
    config_path = get_config_file_path()

    # Initialize configuration
    if not config_path.exists() or force:
        kwargs = {'force': force, 'interactive': False}
        if port is not None:
            kwargs['port'] = port
        init_config(**kwargs)
        console.print(f"[green]Configuration initialized:[/green] {config_path}")
    else:
        console.print(f"[dim]Using existing config:[/dim] {config_path}")

    # Install daemon service
    if progress and task:
        progress.update(task, description="Installing daemon service...")
    else:
        console.print("Installing daemon service...")

    installer = get_installer()
    installer.install()
    console.print("[green]Daemon service installed[/green]")

    # Start daemon service (unless --no-start)
    if not no_start:
        if progress and task:
            progress.update(task, description="Starting daemon service...")
        else:
            console.print("Starting daemon service...")

        installer.start()
        console.print("[green]Daemon service started[/green]")
    else:
        console.print("[dim]Skipped starting daemon (--no-start)[/dim]")


@app.command()
def uninstall(
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompts"),
    force: bool = typer.Option(False, "--force", help="Force uninstall without confirmation"),
    remove_config: bool = typer.Option(False, "--remove-config", help="Remove configuration directory"),
    remove_logs: bool = typer.Option(False, "--remove-logs", help="Remove logs directory")
):
    """Stop and uninstall the daemon service."""
    try:
        # Force acts as --yes
        skip_confirm = yes or force

        if not skip_confirm:
            confirm = typer.confirm("This will stop and uninstall the daemon. Continue?")
            if not confirm:
                console.print("[yellow]Uninstallation cancelled[/yellow]")
                raise typer.Exit(code=0)

        if _RICH_AVAILABLE:
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=console,
            ) as progress:
                task = progress.add_task("Stopping daemon service...", total=None)
                _do_uninstall(remove_config, remove_logs, progress, task)
        else:
            _do_uninstall(remove_config, remove_logs)

        console.print("\n[bold green]Uninstallation complete![/bold green]")

    except Exception as e:
        console.print(f"[red]Uninstallation failed:[/red] {e}")
        raise typer.Exit(code=1)


def _do_uninstall(remove_config: bool, remove_logs: bool, progress=None, task=None):
    """Execute uninstallation steps.

    Args:
        remove_config: Whether to remove configuration directory
        remove_logs: Whether to remove logs directory
        progress: Optional Rich Progress instance
        task: Optional Rich task ID
    """
    installer = get_installer()

    # Stop daemon service
    try:
        installer.stop()
        console.print("[green]Daemon service stopped[/green]")
    except Exception as e:
        console.print(f"[yellow]Warning: failed to stop daemon:[/yellow] {e}")

    # Uninstall daemon service
    if progress and task:
        progress.update(task, description="Uninstalling daemon service...")
    else:
        console.print("Uninstalling daemon service...")

    installer.uninstall()
    console.print("[green]Daemon service uninstalled[/green]")

    # Remove configuration directory if requested
    if remove_config:
        config_dir = get_config_dir()
        if config_dir.exists():
            if progress and task:
                progress.update(task, description="Removing configuration directory...")
            else:
                console.print("Removing configuration directory...")

            shutil.rmtree(config_dir)
            console.print(f"[green]Removed configuration directory:[/green] {config_dir}")
        else:
            console.print(f"[dim]Configuration directory not found:[/dim] {config_dir}")

    # Remove logs directory if requested
    if remove_logs:
        logs_dir = get_logs_dir()
        if logs_dir.exists():
            if progress and task:
                progress.update(task, description="Removing logs directory...")
            else:
                console.print("Removing logs directory...")

            shutil.rmtree(logs_dir)
            console.print(f"[green]Removed logs directory:[/green] {logs_dir}")
        else:
            console.print(f"[dim]Logs directory not found:[/dim] {logs_dir}")
