"""Bootstrap subcommand group for daemon service management."""

import json
import os
import subprocess
import sys

import typer
from rich.console import Console
from rich.table import Table

from async_crud_mcp.daemon.installer import get_installer

app = typer.Typer(help="Bootstrap daemon service")
console = Console()


def _check_admin() -> bool:
    """Check if the current process has administrator privileges.

    Returns:
        bool: True if running as admin, False otherwise
    """
    if sys.platform == 'win32':
        try:
            import ctypes
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except Exception:
            return False
    else:
        return os.geteuid() == 0


@app.command()
def install(
    force: bool = typer.Option(False, "--force", "-f", help="Force installation even if service exists"),
    use_task_scheduler: bool = typer.Option(False, "--use-task-scheduler", help="Use Task Scheduler instead of Windows Service")
):
    """Install the daemon service."""
    if not _check_admin():
        console.print("[red]Admin privileges required. Please run as administrator.[/red]")
        raise typer.Exit(code=1)

    try:
        installer = get_installer()
        installer.install(force=force, force_task_scheduler=use_task_scheduler)
        console.print("[green]Service installed successfully[/green]")
    except subprocess.CalledProcessError as e:
        console.print(f"[red]Installation failed:[/red] {e}")
        raise typer.Exit(code=1)
    except OSError as e:
        console.print(f"[red]Installation failed:[/red] {e}")
        raise typer.Exit(code=1)


@app.command()
def uninstall(
    username: str | None = typer.Option(None, "--username", "-u", help="Target specific user's service"),
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation prompt")
):
    """Uninstall the daemon service."""
    if not _check_admin():
        console.print("[red]Admin privileges required. Please run as administrator.[/red]")
        raise typer.Exit(code=1)

    if not force:
        confirm = typer.confirm("Are you sure you want to uninstall the service?")
        if not confirm:
            console.print("[yellow]Uninstall cancelled[/yellow]")
            raise typer.Exit(code=0)

    try:
        installer = get_installer(username=username)
        installer.stop()
        installer.uninstall()
        console.print("[green]Service uninstalled successfully[/green]")
    except subprocess.CalledProcessError as e:
        console.print(f"[red]Uninstallation failed:[/red] {e}")
        raise typer.Exit(code=1)
    except OSError as e:
        console.print(f"[red]Uninstallation failed:[/red] {e}")
        raise typer.Exit(code=1)


@app.command()
def start(
    username: str | None = typer.Option(None, "--username", "-u", help="Target specific user's service")
):
    """Start the daemon service."""
    try:
        installer = get_installer(username=username)
        installer.start()
        console.print("[green]Service started successfully[/green]")
    except subprocess.CalledProcessError as e:
        console.print(f"[red]Start failed:[/red] {e}")
        raise typer.Exit(code=1)
    except OSError as e:
        console.print(f"[red]Start failed:[/red] {e}")
        raise typer.Exit(code=1)


@app.command()
def stop(
    username: str | None = typer.Option(None, "--username", "-u", help="Target specific user's service")
):
    """Stop the daemon service."""
    try:
        installer = get_installer(username=username)
        installer.stop()
        console.print("[green]Service stopped successfully[/green]")
    except subprocess.CalledProcessError as e:
        console.print(f"[red]Stop failed:[/red] {e}")
        raise typer.Exit(code=1)
    except OSError as e:
        console.print(f"[red]Stop failed:[/red] {e}")
        raise typer.Exit(code=1)


@app.command()
def status(
    username: str | None = typer.Option(None, "--username", "-u", help="Target specific user's service"),
    json_output: bool = typer.Option(False, "--json", "-j", help="Output status as JSON")
):
    """Check daemon service status."""
    try:
        installer = get_installer(username=username)
        svc_status = installer.status()

        if json_output:
            output = {
                "service_name": "async-crud-mcp-daemon",
                "status": svc_status,
                "username": username
            }
            console.print(json.dumps(output))
        else:
            if svc_status == "RUNNING":
                console.print("[green]Status: RUNNING[/green]")
            elif svc_status == "STOPPED":
                console.print("[yellow]Status: STOPPED[/yellow]")
            else:
                console.print(f"[dim]Status: {svc_status}[/dim]")
    except subprocess.CalledProcessError as e:
        console.print(f"[red]Status check failed:[/red] {e}")
        raise typer.Exit(code=1)
    except OSError as e:
        console.print(f"[red]Status check failed:[/red] {e}")
        raise typer.Exit(code=1)


@app.command()
def list():
    """List all installed daemon instances."""
    try:
        installer = get_installer()
        instances = installer.list()

        if not instances:
            console.print("[dim]No daemon instances found[/dim]")
            return

        table = Table(title="Installed Daemon Instances")
        table.add_column("Instance", style="cyan")
        table.add_column("Username", style="yellow")
        table.add_column("Status", style="green")

        for instance in instances:
            # Try to get status for each instance
            try:
                instance_installer = get_installer()
                instance_status = instance_installer.status()
            except Exception:
                instance_status = "UNKNOWN"

            # Extract username from instance name if present
            # Format: async-crud-mcp-daemon or async-crud-mcp-daemon-{username}
            username = "system"
            if "-" in instance:
                parts = instance.split("-")
                if len(parts) > 4:
                    username = "-".join(parts[4:])

            table.add_row(instance, username, instance_status)

        console.print(table)
    except subprocess.CalledProcessError as e:
        console.print(f"[red]List failed:[/red] {e}")
        raise typer.Exit(code=1)
    except OSError as e:
        console.print(f"[red]List failed:[/red] {e}")
        raise typer.Exit(code=1)
