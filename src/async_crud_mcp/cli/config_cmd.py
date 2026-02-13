"""Config subcommand group for configuration management."""

import json
import os
import platform
import subprocess

import typer
from pydantic import ValidationError
from rich.console import Console
from rich.json import JSON
from rich.panel import Panel

from async_crud_mcp.config import get_settings
from async_crud_mcp.daemon.config_init import get_config_file_path as get_config_file_path_init
from async_crud_mcp.daemon.config_init import init_config
from async_crud_mcp.daemon.paths import get_config_file_path

app = typer.Typer(help="Configuration management")
console = Console()


@app.command()
def init(
    force: bool = typer.Option(False, "--force", "-f", help="Overwrite existing config"),
    port: int | None = typer.Option(None, "--port", "-p", help="Server port number"),
    no_interactive: bool = typer.Option(False, "--no-interactive", help="Disable interactive prompts"),
    username: str | None = typer.Option(None, "--username", "-u", help="Username for multi-user scenarios"),
):
    """Initialize default configuration."""
    try:
        config_path = init_config(
            force=force,
            port=port,
            interactive=not no_interactive,
            username=username,
        )
        console.print(f"[green]Configuration initialized:[/green] {config_path}")
    except FileExistsError as e:
        console.print(f"[yellow]{e}[/yellow]")
        console.print("[dim]Use --force to overwrite[/dim]")
        raise typer.Exit(code=1)
    except Exception as e:
        console.print(f"[red]Configuration initialization failed:[/red] {e}")
        raise typer.Exit(code=1)


@app.command()
def show(
    username: str | None = typer.Option(None, "--username", "-u", help="Username for multi-user scenarios"),
    json_output: bool = typer.Option(False, "--json", help="Output raw JSON instead of formatted panel"),
):
    """Show current configuration."""
    try:
        if username:
            config_path = get_config_file_path_init(username)
        else:
            config_path = get_config_file_path()

        if not config_path.exists():
            console.print(f"[yellow]Config file not found:[/yellow] {config_path}")
            console.print("[dim]Run 'async-crud-mcp config init' to create one[/dim]")
            raise typer.Exit(code=1)

        with open(config_path, "r", encoding="utf-8") as f:
            config_data = json.load(f)

        if json_output:
            typer.echo(json.dumps(config_data, indent=2))
        else:
            json_obj = JSON(json.dumps(config_data, indent=2))
            panel = Panel(json_obj, title=f"Configuration: {config_path}", border_style="cyan")
            console.print(panel)

    except json.JSONDecodeError as e:
        console.print(f"[red]Invalid JSON in config file:[/red] {e}")
        raise typer.Exit(code=1)
    except Exception as e:
        console.print(f"[red]Failed to read config:[/red] {e}")
        raise typer.Exit(code=1)


@app.command()
def edit():
    """Edit configuration file in default editor."""
    try:
        config_path = get_config_file_path()

        if not config_path.exists():
            console.print(f"[yellow]Config file not found:[/yellow] {config_path}")
            console.print("[dim]Run 'async-crud-mcp config init' to create one[/dim]")
            raise typer.Exit(code=1)

        if platform.system() == "Windows":
            default_editor = "notepad.exe"
        else:
            default_editor = "nano"

        editor = os.environ.get("EDITOR", default_editor)

        console.print(f"[cyan]Opening config in {editor}...[/cyan]")
        subprocess.run([editor, str(config_path)], check=True)

    except subprocess.CalledProcessError as e:
        console.print(f"[red]Editor failed:[/red] {e}")
        raise typer.Exit(code=1)
    except Exception as e:
        console.print(f"[red]Failed to edit config:[/red] {e}")
        raise typer.Exit(code=1)


@app.command()
def validate(
    username: str | None = typer.Option(None, "--username", "-u", help="Username for multi-user scenarios"),
):
    """Validate configuration file."""
    try:
        if username:
            config_path = get_config_file_path_init(username)
        else:
            config_path = get_config_file_path()

        if not config_path.exists():
            console.print(f"[yellow]Config file not found:[/yellow] {config_path}")
            console.print("[dim]Run 'async-crud-mcp config init' to create one[/dim]")
            raise typer.Exit(code=1)

        settings = get_settings(config_path)

        console.print("[green]Configuration is valid[/green]")
        console.print(f"[dim]Daemon enabled: {settings.daemon.enabled}[/dim]")
        console.print(f"[dim]Server: {settings.daemon.host}:{settings.daemon.port}[/dim]")

    except ValidationError as e:
        console.print("[red]Configuration validation failed:[/red]")
        for error in e.errors():
            loc = " -> ".join(str(x) for x in error["loc"])
            console.print(f"  [yellow]{loc}:[/yellow] {error['msg']}")
        raise typer.Exit(code=1)
    except Exception as e:
        console.print(f"[red]Validation failed:[/red] {e}")
        raise typer.Exit(code=1)
