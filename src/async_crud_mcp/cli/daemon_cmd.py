"""Daemon subcommand group for lifecycle management."""

import asyncio
import subprocess
import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax

from async_crud_mcp.daemon.bootstrap_daemon import BootstrapDaemon
from async_crud_mcp.daemon.health import check_health
from async_crud_mcp.daemon.paths import get_logs_dir

app = typer.Typer(help="Daemon lifecycle management")
console = Console()


@app.command()
def start(background: bool = typer.Option(False, "--background", "-b", help="Run in background")):
    """Start the daemon."""
    try:
        daemon = BootstrapDaemon()

        if background:
            python_exe = sys.executable
            script_args = [python_exe, "-m", "async_crud_mcp.daemon.bootstrap_daemon"]

            if sys.platform == "win32":
                subprocess.Popen(
                    script_args,
                    creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            else:
                subprocess.Popen(
                    script_args,
                    start_new_session=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )

            console.print("[green]Daemon started in background[/green]")
        else:
            console.print("[cyan]Starting daemon in foreground...[/cyan]")
            asyncio.run(daemon.run())

    except KeyboardInterrupt:
        console.print("\n[yellow]Daemon interrupted[/yellow]")
    except Exception as e:
        console.print(f"[red]Failed to start daemon:[/red] {e}")
        raise typer.Exit(code=1)


@app.command()
def stop():
    """Stop the daemon."""
    console.print("[yellow]Stop command not yet implemented[/yellow]")
    console.print("[dim]Use your platform's service manager or kill the process[/dim]")


@app.command()
def restart():
    """Restart the daemon."""
    console.print("[cyan]Restarting daemon...[/cyan]")
    try:
        stop()
        start()
    except Exception as e:
        console.print(f"[red]Restart failed:[/red] {e}")
        raise typer.Exit(code=1)


@app.command()
def status():
    """Check daemon health status."""
    try:
        health = check_health()
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
def logs(follow: bool = typer.Option(False, "--follow", "-f", help="Follow log output")):
    """View daemon logs."""
    try:
        log_file = get_logs_dir() / "daemon.log"

        if not log_file.exists():
            console.print(f"[yellow]Log file not found:[/yellow] {log_file}")
            return

        if follow:
            console.print(f"[cyan]Following logs from:[/cyan] {log_file}")
            console.print("[dim]Press Ctrl+C to stop[/dim]\n")

            try:
                with open(log_file, "r", encoding="utf-8") as f:
                    f.seek(0, 2)
                    while True:
                        line = f.readline()
                        if line:
                            console.print(line, end="")
                        else:
                            import time
                            time.sleep(0.5)
            except KeyboardInterrupt:
                console.print("\n[dim]Stopped following logs[/dim]")
        else:
            with open(log_file, "r", encoding="utf-8") as f:
                content = f.read()
                syntax = Syntax(content, "log", theme="monokai", line_numbers=False)
                console.print(syntax)

    except Exception as e:
        console.print(f"[red]Failed to read logs:[/red] {e}")
        raise typer.Exit(code=1)
