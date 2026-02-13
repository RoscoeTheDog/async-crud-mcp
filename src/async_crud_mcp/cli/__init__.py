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
app.add_typer(install_cmd.app, name="install", help="Quick installation commands")
app.add_typer(setup_cmd.app, name="setup", help="Interactive setup wizard")


if __name__ == "__main__":
    app()
