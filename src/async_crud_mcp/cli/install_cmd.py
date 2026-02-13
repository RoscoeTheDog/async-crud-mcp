"""Install subcommand group for quick installation commands."""

import typer
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

from async_crud_mcp.daemon.config_init import init_config
from async_crud_mcp.daemon.installer import get_installer
from async_crud_mcp.daemon.paths import get_config_file_path

app = typer.Typer(help="Quick installation commands")
console = Console()


@app.command()
def quick_install(
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompts")
):
    """Run full setup sequence: config init, install, and start."""
    try:
        if not yes:
            confirm = typer.confirm("This will initialize config, install, and start the daemon. Continue?")
            if not confirm:
                console.print("[yellow]Installation cancelled[/yellow]")
                raise typer.Exit(code=0)

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            task = progress.add_task("Initializing configuration...", total=None)

            config_path = get_config_file_path()
            if not config_path.exists():
                init_config(force=False, interactive=False)
                console.print(f"[green]Configuration initialized:[/green] {config_path}")
            else:
                console.print(f"[dim]Using existing config:[/dim] {config_path}")

            progress.update(task, description="Installing daemon service...")
            installer = get_installer()
            installer.install()
            console.print("[green]Daemon service installed[/green]")

            progress.update(task, description="Starting daemon service...")
            installer.start()
            console.print("[green]Daemon service started[/green]")

        console.print("\n[bold green]Quick installation complete![/bold green]")
        console.print("[dim]Use 'async-crud-mcp daemon status' to check daemon health[/dim]")

    except FileExistsError:
        console.print("[yellow]Config already exists, using existing config[/yellow]")
    except Exception as e:
        console.print(f"[red]Installation failed:[/red] {e}")
        raise typer.Exit(code=1)


@app.command()
def uninstall(
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompts")
):
    """Stop and uninstall the daemon service."""
    try:
        if not yes:
            confirm = typer.confirm("This will stop and uninstall the daemon. Continue?")
            if not confirm:
                console.print("[yellow]Uninstallation cancelled[/yellow]")
                raise typer.Exit(code=0)

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            task = progress.add_task("Stopping daemon service...", total=None)

            installer = get_installer()
            try:
                installer.stop()
                console.print("[green]Daemon service stopped[/green]")
            except Exception as e:
                console.print(f"[yellow]Warning: failed to stop daemon:[/yellow] {e}")

            progress.update(task, description="Uninstalling daemon service...")
            installer.uninstall()
            console.print("[green]Daemon service uninstalled[/green]")

        console.print("\n[bold green]Uninstallation complete![/bold green]")

    except Exception as e:
        console.print(f"[red]Uninstallation failed:[/red] {e}")
        raise typer.Exit(code=1)
