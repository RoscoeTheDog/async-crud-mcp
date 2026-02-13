"""CLI package for async-crud-mcp."""

import typer

from async_crud_mcp.cli import (
    bootstrap_cmd,
    config_cmd,
    daemon_cmd,
    install_cmd,
    setup_cmd,
)

app = typer.Typer(
    name="async-crud-mcp",
    help="Async CRUD MCP daemon management CLI",
    no_args_is_help=True,
)

app.add_typer(bootstrap_cmd.app, name="bootstrap", help="Bootstrap daemon service")
app.add_typer(daemon_cmd.app, name="daemon", help="Daemon lifecycle management")
app.add_typer(config_cmd.app, name="config", help="Configuration management")

# Register setup as a top-level command
app.command(name="setup", help="Interactive setup wizard")(setup_cmd.wizard)

# Register quick-install as a top-level command
app.command(name="quick-install", help="Run full setup sequence")(install_cmd.quick_install)

# Register uninstall as a top-level command
app.command(name="uninstall", help="Stop and uninstall the daemon service")(install_cmd.uninstall)


@app.command()
def version():
    """Show version information."""
    from async_crud_mcp import __version__
    typer.echo(f"async-crud-mcp {__version__}")


if __name__ == "__main__":
    app()
