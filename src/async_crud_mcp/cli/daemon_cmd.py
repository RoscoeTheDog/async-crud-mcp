"""Daemon subcommand group for lifecycle management."""

import json
import time

import typer
from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax

from async_crud_mcp.daemon.config_init import generate_default_config
from async_crud_mcp.daemon.config_watcher import atomic_write_config
from async_crud_mcp.daemon.health import check_health
from async_crud_mcp.daemon.paths import get_config_file_path, get_logs_dir, get_user_config_file_path, get_user_logs_dir

app = typer.Typer(help="Daemon lifecycle management")
console = Console()


@app.command()
def start():
    """Start the daemon."""
    try:
        config_path = get_config_file_path()

        if config_path.exists():
            config = json.loads(config_path.read_text(encoding="utf-8"))
        else:
            config_path.parent.mkdir(parents=True, exist_ok=True)
            config = generate_default_config()

        config["daemon"]["enabled"] = True
        atomic_write_config(config_path, config)

        console.print("[green]Daemon start requested[/green]")
        console.print("[dim]The daemon will start automatically via the ConfigWatcher[/dim]")

    except Exception as e:
        console.print(f"[red]Failed to start daemon:[/red] {e}")
        raise typer.Exit(code=1)


@app.command()
def stop():
    """Stop the daemon."""
    try:
        config_path = get_config_file_path()

        if not config_path.exists():
            console.print("[yellow]Config file not found, daemon may not be running[/yellow]")
            raise typer.Exit(code=1)

        config = json.loads(config_path.read_text(encoding="utf-8"))
        config["daemon"]["enabled"] = False
        atomic_write_config(config_path, config)

        console.print("[green]Daemon stop requested[/green]")
        console.print("[dim]The daemon will stop automatically via the ConfigWatcher[/dim]")

    except Exception as e:
        console.print(f"[red]Failed to stop daemon:[/red] {e}")
        raise typer.Exit(code=1)


@app.command()
def restart():
    """Restart the daemon."""
    try:
        config_path = get_config_file_path()

        if not config_path.exists():
            console.print("[yellow]Config file not found, creating new config and starting daemon[/yellow]")
            config_path.parent.mkdir(parents=True, exist_ok=True)
            config = generate_default_config()
            config["daemon"]["enabled"] = True
            atomic_write_config(config_path, config)
            console.print("[green]Daemon started[/green]")
            return

        config = json.loads(config_path.read_text(encoding="utf-8"))

        console.print("[cyan]Stopping daemon...[/cyan]")
        stop_config = json.loads(json.dumps(config))
        stop_config["daemon"]["enabled"] = False
        atomic_write_config(config_path, stop_config)

        config_poll_seconds = config.get("daemon", {}).get("config_poll_seconds", 3)
        config_debounce_seconds = config.get("daemon", {}).get("config_debounce_seconds", 1.0)
        wait_time = config_poll_seconds + config_debounce_seconds

        console.print(f"[dim]Waiting {wait_time}s for daemon to stop...[/dim]")
        time.sleep(wait_time)

        console.print("[cyan]Starting daemon...[/cyan]")
        start_config = json.loads(json.dumps(config))
        start_config["daemon"]["enabled"] = True
        atomic_write_config(config_path, start_config)

        console.print("[green]Daemon restart requested[/green]")

    except Exception as e:
        console.print(f"[red]Restart failed:[/red] {e}")
        raise typer.Exit(code=1)


def _check_user_health(username: str) -> dict:
    """Check health for a specific user's daemon configuration.

    Args:
        username: Username whose config to check

    Returns:
        Health check result dictionary
    """
    user_config_path = get_user_config_file_path(username)

    if not user_config_path.exists():
        return {
            "status": "unknown",
            "message": f"Config not found for user: {username}",
            "config_readable": False,
        }

    try:
        user_config = json.loads(user_config_path.read_text(encoding="utf-8"))
        host = user_config.get("daemon", {}).get("host", "127.0.0.1")
        port = user_config.get("daemon", {}).get("port", 8720)

        import socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        result = sock.connect_ex((host, port))
        sock.close()

        return {
            "status": "healthy" if result == 0 else "degraded",
            "message": f"User {username} daemon",
            "config_readable": True,
            "daemon_enabled": user_config.get("daemon", {}).get("enabled", False),
            "host": host,
            "port": port,
            "port_listening": result == 0,
        }
    except Exception as e:
        return {
            "status": "error",
            "message": f"Error checking user {username}: {e}",
            "config_readable": False,
        }


@app.command()
def status(
    username: str = typer.Option(None, "--username", "-u", help="Check specific user's daemon"),
    all_users: bool = typer.Option(False, "--all", "-a", help="Check all known users"),
    json_output: bool = typer.Option(False, "--json", "-j", help="Output as JSON"),
):
    """Check daemon health status."""
    try:
        if all_users:
            console.print("[yellow]--all option: multi-user enumeration not yet implemented[/yellow]")
            console.print("[dim]Falling back to current user status[/dim]")

        if username:
            health = _check_user_health(username)
        else:
            health = check_health()

        if json_output:
            console.print(json.dumps(health, indent=2))
            return

        status_text = health.get("status", "unknown").upper()

        if health["status"] == "healthy":
            status_color = "green"
        elif health["status"] == "degraded":
            status_color = "yellow"
        else:
            status_color = "red"

        lines = [
            f"[{status_color}]Status: {status_text}[/{status_color}]",
            f"Message: {health.get('message', 'N/A')}",
            "",
            f"Config readable: {health.get('config_readable', False)}",
            f"Daemon enabled: {health.get('daemon_enabled', 'N/A')}",
            f"Logs dir exists: {health.get('logs_dir_exists', False)}",
            f"Port listening: {health.get('port_listening', 'N/A')}",
        ]

        if health.get("host"):
            lines.append(f"Host: {health['host']}")
        if health.get("port"):
            lines.append(f"Port: {health['port']}")

        panel = Panel("\n".join(lines), title="Daemon Health", border_style=status_color)
        console.print(panel)

    except Exception as e:
        console.print(f"[red]Status check failed:[/red] {e}")
        raise typer.Exit(code=1)


@app.command()
def logs(
    follow: bool = typer.Option(False, "--follow", "-f", help="Follow log output"),
    lines: int = typer.Option(None, "--lines", "-n", help="Show last N lines"),
    username: str = typer.Option(None, "--username", "-u", help="Show logs for specific user"),
    user: str = typer.Option(None, "--user", help="Alias for --username"),
):
    """View daemon logs."""
    try:
        target_username = username or user

        if target_username:
            log_dir = get_user_logs_dir(target_username)
        else:
            log_dir = get_logs_dir()

        log_file = log_dir / "daemon.log"

        if not log_file.exists():
            console.print(f"[yellow]Log file not found:[/yellow] {log_file}")
            return

        if follow:
            console.print(f"[cyan]Following logs from:[/cyan] {log_file}")
            console.print("[dim]Press Ctrl+C to stop[/dim]\n")

            try:
                with open(log_file, "r", encoding="utf-8") as f:
                    if lines is not None:
                        all_lines = f.readlines()
                        for line in all_lines[-lines:]:
                            console.print(line, end="")

                    f.seek(0, 2)
                    while True:
                        line = f.readline()
                        if line:
                            console.print(line, end="")
                        else:
                            time.sleep(0.5)
            except KeyboardInterrupt:
                console.print("\n[dim]Stopped following logs[/dim]")
        else:
            with open(log_file, "r", encoding="utf-8") as f:
                if lines is not None:
                    all_lines = f.readlines()
                    content = "".join(all_lines[-lines:])
                else:
                    content = f.read()

                syntax = Syntax(content, "log", theme="monokai", line_numbers=False)
                console.print(syntax)

    except Exception as e:
        console.print(f"[red]Failed to read logs:[/red] {e}")
        raise typer.Exit(code=1)
