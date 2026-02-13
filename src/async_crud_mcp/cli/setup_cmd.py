"""Setup subcommand group for interactive setup wizard."""

import typer
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt

from async_crud_mcp.daemon.config_init import find_available_port, init_config
from async_crud_mcp.daemon.installer import get_installer
from async_crud_mcp.daemon.paths import get_config_file_path

app = typer.Typer(help="Interactive setup wizard")
console = Console()


@app.command()
def wizard():
    """Run interactive setup wizard."""
    try:
        console.print(Panel.fit(
            "[bold cyan]Async CRUD MCP Setup Wizard[/bold cyan]\n"
            "This wizard will help you configure and install the daemon.",
            border_style="cyan"
        ))

        config_path = get_config_file_path()
        if config_path.exists():
            console.print(f"\n[yellow]Configuration already exists:[/yellow] {config_path}")
            overwrite = Confirm.ask("Overwrite existing configuration?", default=False)
            if not overwrite:
                console.print("[dim]Using existing configuration[/dim]")
                force = False
                skip_config = True
            else:
                force = True
                skip_config = False
        else:
            force = False
            skip_config = False

        if not skip_config:
            console.print("\n[bold]Step 1: Server Configuration[/bold]")

            default_port = find_available_port()
            port_str = Prompt.ask(
                "Server port",
                default=str(default_port)
            )
            port = int(port_str)

            host = Prompt.ask(
                "Server host",
                default="127.0.0.1"
            )

            transport = Prompt.ask(
                "Transport protocol",
                choices=["sse", "stdio"],
                default="sse"
            )

            log_level = Prompt.ask(
                "Log level",
                choices=["DEBUG", "INFO", "WARNING", "ERROR"],
                default="INFO"
            )

            console.print("\n[bold]Step 2: Writing Configuration[/bold]")
            config_path = init_config(
                force=force,
                port=port,
                host=host,
                log_level=log_level,
                interactive=False
            )
            console.print(f"[green]Configuration written to:[/green] {config_path}")

        console.print("\n[bold]Step 3: Daemon Installation[/bold]")
        install_daemon = Confirm.ask("Install and start the daemon service?", default=True)

        if install_daemon:
            installer = get_installer()

            console.print("[cyan]Installing daemon service...[/cyan]")
            installer.install()
            console.print("[green]Daemon service installed[/green]")

            console.print("[cyan]Starting daemon service...[/cyan]")
            installer.start()
            console.print("[green]Daemon service started[/green]")

            console.print("\n[bold green]Setup complete![/bold green]")
            console.print("[dim]Use 'async-crud-mcp daemon status' to check daemon health[/dim]")
        else:
            console.print("\n[yellow]Setup complete (daemon not installed)[/yellow]")
            console.print("[dim]Run 'async-crud-mcp install quick-install' to install later[/dim]")

    except KeyboardInterrupt:
        console.print("\n[yellow]Setup cancelled[/yellow]")
        raise typer.Exit(code=0)
    except Exception as e:
        console.print(f"\n[red]Setup failed:[/red] {e}")
        raise typer.Exit(code=1)
