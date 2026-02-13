"""Bootstrap subcommand group for daemon service management."""

import subprocess

import typer
from rich.console import Console
from rich.table import Table

from async_crud_mcp.daemon.installer import get_installer

app = typer.Typer(help="Bootstrap daemon service")
console = Console()


@app.command()
def install():
    """Install the daemon service."""
    try:
        installer = get_installer()
        installer.install()
        console.print("[green]Service installed successfully[/green]")
    except subprocess.CalledProcessError as e:
        console.print(f"[red]Installation failed:[/red] {e}")
        raise typer.Exit(code=1)
    except OSError as e:
        console.print(f"[red]Installation failed:[/red] {e}")
        raise typer.Exit(code=1)


@app.command()
def uninstall():
    """Uninstall the daemon service."""
    try:
        installer = get_installer()
        installer.uninstall()
        console.print("[green]Service uninstalled successfully[/green]")
    except subprocess.CalledProcessError as e:
        console.print(f"[red]Uninstallation failed:[/red] {e}")
        raise typer.Exit(code=1)
    except OSError as e:
        console.print(f"[red]Uninstallation failed:[/red] {e}")
        raise typer.Exit(code=1)


@app.command()
def start():
    """Start the daemon service."""
    try:
        installer = get_installer()
        installer.start()
        console.print("[green]Service started successfully[/green]")
    except subprocess.CalledProcessError as e:
        console.print(f"[red]Start failed:[/red] {e}")
        raise typer.Exit(code=1)
    except OSError as e:
        console.print(f"[red]Start failed:[/red] {e}")
        raise typer.Exit(code=1)


@app.command()
def stop():
    """Stop the daemon service."""
    try:
        installer = get_installer()
        installer.stop()
        console.print("[green]Service stopped successfully[/green]")
    except subprocess.CalledProcessError as e:
        console.print(f"[red]Stop failed:[/red] {e}")
        raise typer.Exit(code=1)
    except OSError as e:
        console.print(f"[red]Stop failed:[/red] {e}")
        raise typer.Exit(code=1)


@app.command()
def status():
    """Check daemon service status."""
    try:
        installer = get_installer()
        svc_status = installer.status()

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

        for instance in instances:
            table.add_row(instance)

        console.print(table)
    except subprocess.CalledProcessError as e:
        console.print(f"[red]List failed:[/red] {e}")
        raise typer.Exit(code=1)
    except OSError as e:
        console.print(f"[red]List failed:[/red] {e}")
        raise typer.Exit(code=1)
