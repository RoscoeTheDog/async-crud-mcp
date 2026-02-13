"""Setup subcommand group for interactive setup wizard."""

import json
import sys
import time
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt

from async_crud_mcp.daemon.config_init import DEFAULT_PORT, find_available_port, init_config
from async_crud_mcp.daemon.health import _is_port_listening
from async_crud_mcp.daemon.installer import get_installer
from async_crud_mcp.daemon.paths import get_config_dir, get_config_file_path, get_logs_dir

app = typer.Typer(help="Interactive setup wizard")
console = Console()


@app.command()
def wizard(
    port: int = typer.Option(None, "--port", help="Server port"),
    no_interactive: bool = typer.Option(False, "--no-interactive", help="Disable interactive prompts"),
    force: bool = typer.Option(False, "--force", help="Overwrite existing configuration"),
):
    """Run interactive setup wizard."""
    try:
        console.print(Panel.fit(
            "[bold cyan]Async CRUD MCP Setup Wizard[/bold cyan]\n"
            "This wizard will help you configure and install the daemon.",
            border_style="cyan"
        ))

        # Step 1: Check Prerequisites
        console.print("\n[bold]Step 1: Check Prerequisites[/bold]")
        prerequisites_ok = _check_prerequisites(console, no_interactive)
        if not prerequisites_ok:
            raise typer.Exit(code=1)

        # Step 2: Find Available Port
        console.print("\n[bold]Step 2: Find Available Port[/bold]")
        discovered_port = _find_and_verify_port(console, port, no_interactive)

        # Step 3: Create Per-User Directories
        console.print("\n[bold]Step 3: Create Per-User Directories[/bold]")
        _create_directories(console)

        # Step 4: Configuration and Daemon Installation
        console.print("\n[bold]Step 4: Write Configuration and Install Daemon[/bold]")
        config_path = get_config_file_path()
        skip_config = False

        if config_path.exists() and not force:
            if not no_interactive:
                console.print(f"\n[yellow]Configuration already exists:[/yellow] {config_path}")
                overwrite = Confirm.ask("Overwrite existing configuration?", default=False)
                if not overwrite:
                    console.print("[dim]Using existing configuration[/dim]")
                    skip_config = True
                else:
                    skip_config = False
            else:
                # Non-interactive mode: skip if no force
                console.print(f"[dim]Using existing configuration: {config_path}[/dim]")
                skip_config = True

        if not skip_config:
            # Gather configuration parameters
            final_port = discovered_port
            final_host = "127.0.0.1"
            final_transport = "sse"
            final_log_level = "INFO"

            if not no_interactive:
                port_str = Prompt.ask(
                    "Server port",
                    default=str(discovered_port)
                )
                final_port = int(port_str)

                final_host = Prompt.ask(
                    "Server host",
                    default="127.0.0.1"
                )

                final_transport = Prompt.ask(
                    "Transport protocol",
                    choices=["sse", "stdio"],
                    default="sse"
                )

                final_log_level = Prompt.ask(
                    "Log level",
                    choices=["DEBUG", "INFO", "WARNING", "ERROR"],
                    default="INFO"
                )

            console.print("[cyan]Writing configuration...[/cyan]")
            config_path = init_config(
                force=True,  # We already checked overwrite above
                port=final_port,
                host=final_host,
                log_level=final_log_level,
                interactive=False
            )
            console.print(f"[green]Configuration written to:[/green] {config_path}")
        else:
            # Load existing config to get host/port for later steps
            try:
                with open(config_path, 'r', encoding='utf-8') as f:
                    existing_config = json.load(f)
                final_host = existing_config.get('daemon', {}).get('host', '127.0.0.1')
                final_port = existing_config.get('daemon', {}).get('port', discovered_port)
            except (json.JSONDecodeError, OSError, KeyError):
                final_host = "127.0.0.1"
                final_port = discovered_port

        # Install daemon
        install_daemon = True
        if not no_interactive:
            install_daemon = Confirm.ask("Install and start the daemon service?", default=True)

        daemon_started = False
        if install_daemon:
            try:
                installer = get_installer()

                console.print("[cyan]Installing daemon service...[/cyan]")
                installer.install()
                console.print("[green]Daemon service installed[/green]")

                console.print("[cyan]Starting daemon service...[/cyan]")
                installer.start()
                console.print("[green]Daemon service started[/green]")
                daemon_started = True
            except OSError as e:
                console.print(f"[yellow]Warning: Daemon installation failed:[/yellow] {e}")
                console.print("[dim]You may need administrator privileges to install the service.[/dim]")
                console.print("[dim]Try running 'async-crud-mcp install quick-install' with admin rights.[/dim]")
                # Continue with the wizard even if daemon install fails

        # Step 5: Configure Claude Code CLI
        console.print("\n[bold]Step 5: Configure Claude Code CLI[/bold]")
        _configure_claude_cli(console, final_host, final_port)

        # Step 6: Verify Server Connectivity
        if daemon_started:
            console.print("\n[bold]Step 6: Verify Server Connectivity[/bold]")
            _verify_connectivity(console, final_host, final_port)

        console.print("\n[bold green]Setup complete![/bold green]")
        console.print("[dim]Use 'async-crud-mcp daemon status' to check daemon health[/dim]")

    except KeyboardInterrupt:
        console.print("\n[yellow]Setup cancelled[/yellow]")
        raise typer.Exit(code=0)
    except Exception as e:
        console.print(f"\n[red]Setup failed:[/red] {e}")
        raise typer.Exit(code=1)


def _check_prerequisites(console: Console, no_interactive: bool) -> bool:
    """Check prerequisites: Python version and required packages.

    Returns:
        True if all prerequisites pass, False otherwise.
    """
    all_ok = True

    # Check Python version
    if sys.version_info >= (3, 10):
        console.print("[green]\u2713[/green] Python >= 3.10")
    else:
        console.print(f"[red]\u2717[/red] Python >= 3.10 (found {sys.version_info.major}.{sys.version_info.minor})")
        all_ok = False

    # Check required packages
    required_packages = ["fastmcp", "pydantic", "loguru"]
    for pkg in required_packages:
        try:
            __import__(pkg)
            console.print(f"[green]\u2713[/green] {pkg} is importable")
        except ImportError:
            console.print(f"[red]\u2717[/red] {pkg} is importable")
            all_ok = False

    if not all_ok:
        console.print("\n[red]Prerequisites check failed. Please install missing packages.[/red]")

    return all_ok


def _find_and_verify_port(console: Console, cli_port: int | None, no_interactive: bool) -> int:
    """Find and verify an available port.

    Args:
        console: Rich console for output
        cli_port: Port specified via --port CLI option
        no_interactive: Whether in non-interactive mode

    Returns:
        Available port number
    """
    start_port = cli_port or DEFAULT_PORT

    # Try the specified/default port first
    try:
        discovered_port = find_available_port(start=start_port)
        if discovered_port == start_port:
            console.print(f"[green]Port {discovered_port} is available[/green]")
        else:
            console.print(f"[yellow]Port {start_port} is in use, using {discovered_port} instead[/yellow]")

        # In interactive mode, allow user to override
        if not no_interactive and cli_port is None:
            override = Confirm.ask(f"Use port {discovered_port}?", default=True)
            if not override:
                port_str = Prompt.ask("Enter port number", default=str(discovered_port))
                discovered_port = int(port_str)

        return discovered_port
    except RuntimeError as e:
        console.print(f"[red]Port discovery failed:[/red] {e}")
        return DEFAULT_PORT


def _create_directories(console: Console) -> None:
    """Create per-user configuration and logs directories."""
    config_dir = get_config_dir()
    logs_dir = get_logs_dir()

    config_dir.mkdir(parents=True, exist_ok=True)
    console.print(f"[green]\u2713[/green] Config directory: {config_dir}")

    logs_dir.mkdir(parents=True, exist_ok=True)
    console.print(f"[green]\u2713[/green] Logs directory: {logs_dir}")


def _configure_claude_cli(console: Console, host: str, port: int) -> None:
    """Configure Claude Code CLI with the MCP server.

    Best-effort configuration - warns but does not fail if Claude CLI is not found.
    """
    # Try to find Claude config file
    claude_config_path = Path.home() / ".claude" / "claude_desktop_config.json"

    if not claude_config_path.exists():
        console.print("[yellow]Claude Code CLI config not found - skipping[/yellow]")
        console.print(f"[dim]Expected location: {claude_config_path}[/dim]")
        return

    try:
        # Load existing config
        with open(claude_config_path, 'r', encoding='utf-8') as f:
            claude_config = json.load(f)

        # Ensure mcpServers section exists
        if "mcpServers" not in claude_config:
            claude_config["mcpServers"] = {}

        # Add/update async-crud-mcp entry
        claude_config["mcpServers"]["async-crud-mcp"] = {
            "url": f"http://{host}:{port}/sse"
        }

        # Write back
        with open(claude_config_path, 'w', encoding='utf-8') as f:
            json.dump(claude_config, f, indent=2)

        console.print(f"[green]\u2713[/green] Claude Code CLI configured: {claude_config_path}")
    except (json.JSONDecodeError, OSError, KeyError) as e:
        console.print(f"[yellow]Warning: Could not configure Claude CLI:[/yellow] {e}")
        console.print("[dim]You may need to manually add the server to Claude Code settings[/dim]")


def _verify_connectivity(console: Console, host: str, port: int) -> None:
    """Verify server connectivity by checking if the port is listening."""
    console.print("[cyan]Waiting for server to start...[/cyan]")
    time.sleep(2)

    if _is_port_listening(host, port):
        console.print(f"[green]\u2713[/green] Server is listening on {host}:{port}")
    else:
        console.print(f"[yellow]Warning: Server is not responding on {host}:{port}[/yellow]")
        console.print("[dim]The daemon may need more time to start. Check status with 'async-crud-mcp daemon status'[/dim]")
