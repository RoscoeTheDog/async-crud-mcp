#!/usr/bin/env python3
"""Configure Claude Code CLI with MCP server entry.

This script manages the ~/.claude.json configuration file to add, update,
or remove MCP server entries for SSE-based daemon connections. Also
registers/deregisters the server in the port discovery manifest
(~/.claude/mcp-daemons.json) for automatic port remapping.

Usage:
    configure_claude_code.py --port 8720       # Add/update MCP server entry
    configure_claude_code.py --show            # Show current config
    configure_claude_code.py --remove          # Remove MCP server entry
    configure_claude_code.py --desktop --port  # Configure Claude Desktop instead
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

# Configuration - customize for your MCP server
APP_NAME = 'async-crud-mcp'
DEFAULT_PORT = 8720
# Platform config path for port discovery manifest (supports ~ and $VAR)
# Windows: $LOCALAPPDATA/async-crud-mcp/config/config.json
# macOS:   ~/Library/Preferences/async-crud-mcp/config.json
# Linux:   ~/.config/async-crud-mcp/config.json
if sys.platform == "win32":
    CONFIG_PATH = '$LOCALAPPDATA/async-crud-mcp/config/config.json'
elif sys.platform == "darwin":
    CONFIG_PATH = '~/Library/Preferences/async-crud-mcp/config.json'
else:
    CONFIG_PATH = '~/.config/async-crud-mcp/config.json'


def get_claude_cli_config_path() -> Path:
    """Get path to Claude Code CLI config file (~/.claude.json)."""
    return Path.home() / ".claude.json"


def get_claude_desktop_config_path() -> Path:
    """Get platform-specific path to Claude Desktop config."""
    if sys.platform == "win32":
        return Path.home() / "AppData" / "Roaming" / "Claude" / "claude_desktop_config.json"
    elif sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
    else:
        # Linux - XDG config
        xdg_config = Path.home() / ".config"
        return xdg_config / "Claude" / "claude_desktop_config.json"


def load_config(config_path: Path) -> dict[str, Any]:
    """Load existing config or return empty structure."""
    if config_path.exists():
        try:
            return json.loads(config_path.read_text())
        except json.JSONDecodeError:
            print(f"[WARN] Invalid JSON in {config_path}, starting fresh")
            return {}
    return {}


def save_config(config_path: Path, config: dict[str, Any]) -> None:
    """Save config with proper formatting."""
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps(config, indent=2) + "\n")


def add_mcp_server(
    config_path: Path,
    port: int,
    host: str = "127.0.0.1",
    server_name: str | None = None,
) -> dict[str, Any]:
    """Add or update MCP server entry in config.

    Args:
        config_path: Path to config file.
        port: Server port.
        host: Server host (default: 127.0.0.1).
        server_name: Server name in config (default: APP_NAME).

    Returns:
        Updated config dict.
    """
    config = load_config(config_path)
    server_name = server_name or APP_NAME

    # Ensure mcpServers section exists
    if "mcpServers" not in config:
        config["mcpServers"] = {}

    # Add/update server entry for SSE transport
    config["mcpServers"][server_name] = {
        "type": "sse",
        "url": f"http://{host}:{port}/sse",
    }

    save_config(config_path, config)
    return config


def remove_mcp_server(
    config_path: Path,
    server_name: str | None = None,
) -> dict[str, Any]:
    """Remove MCP server entry from config.

    Args:
        config_path: Path to config file.
        server_name: Server name to remove (default: APP_NAME).

    Returns:
        Updated config dict.
    """
    config = load_config(config_path)
    server_name = server_name or APP_NAME

    if "mcpServers" in config and server_name in config["mcpServers"]:
        del config["mcpServers"][server_name]
        # Clean up empty mcpServers section
        if not config["mcpServers"]:
            del config["mcpServers"]
        save_config(config_path, config)
        print(f"[OK] Removed {server_name} from {config_path}")
    else:
        print(f"[INFO] {server_name} not found in {config_path}")

    return config


def get_manifest_path() -> Path:
    """Get path to MCP daemons manifest (~/.claude/mcp-daemons.json)."""
    return Path.home() / ".claude" / "mcp-daemons.json"


def register_in_manifest(
    name: str,
    config_path_pattern: str,
    default_port: int,
    host: str = "127.0.0.1",
    url_path: str = "/sse",
    manifest_path: Path | None = None,
) -> None:
    """Register daemon MCP server in the port discovery manifest.

    Creates or updates the manifest file used by the SessionStart hook
    to auto-discover ports on session start.

    Args:
        name: Server name (must match mcpServers key in ~/.claude.json).
        config_path_pattern: Path to daemon config.json (supports ~ and $VAR).
        default_port: Fallback port if config is unreadable.
        host: Host address (default: 127.0.0.1).
        url_path: SSE endpoint path (default: /sse).
        manifest_path: Override manifest location (default: ~/.claude/mcp-daemons.json).
    """
    if manifest_path is None:
        manifest_path = get_manifest_path()

    # Load or create manifest
    manifest: dict[str, Any] = {"$schema": "mcp-daemons-manifest-v1", "servers": []}
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass

    # Build entry
    entry = {
        "name": name,
        "configPath": config_path_pattern,
        "defaultPort": default_port,
        "host": host,
        "urlPath": url_path,
        "type": "sse",
    }

    # Replace existing entry with same name, or append
    servers = manifest.get("servers", [])
    servers = [s for s in servers if s.get("name") != name]
    servers.append(entry)
    manifest["servers"] = servers

    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"[OK] Registered {name} in port discovery manifest: {manifest_path}")


def deregister_from_manifest(
    name: str,
    manifest_path: Path | None = None,
) -> None:
    """Remove daemon MCP server from the port discovery manifest.

    Args:
        name: Server name to remove.
        manifest_path: Override manifest location (default: ~/.claude/mcp-daemons.json).
    """
    if manifest_path is None:
        manifest_path = get_manifest_path()

    if not manifest_path.exists():
        return

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return

    servers = manifest.get("servers", [])
    original_count = len(servers)
    servers = [s for s in servers if s.get("name") != name]
    manifest["servers"] = servers

    if len(servers) < original_count:
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        print(f"[OK] Deregistered {name} from port discovery manifest")
    else:
        print(f"[INFO] {name} not found in port discovery manifest")


def show_config(config_path: Path) -> None:
    """Display current config file contents."""
    if not config_path.exists():
        print(f"[INFO] Config file does not exist: {config_path}")
        return

    config = load_config(config_path)
    print(f"Config: {config_path}")
    print("-" * 40)

    if "mcpServers" in config:
        print("MCP Servers:")
        for name, entry in config["mcpServers"].items():
            server_type = entry.get("type", "unknown")
            if server_type == "sse":
                url = entry.get("url", "N/A")
                print(f"  {name}: {server_type} -> {url}")
            else:
                cmd = entry.get("command", "N/A")
                print(f"  {name}: {server_type} -> {cmd}")
    else:
        print("No MCP servers configured")

    print("-" * 40)


def main() -> int:
    """CLI entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description=f"Configure Claude Code CLI for {APP_NAME} MCP server"
    )
    parser.add_argument(
        "--port", "-p",
        type=int,
        default=DEFAULT_PORT,
        help=f"Server port (default: {DEFAULT_PORT})",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Server host (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--name",
        default=APP_NAME,
        help=f"Server name in config (default: {APP_NAME})",
    )
    parser.add_argument(
        "--show", "-s",
        action="store_true",
        help="Show current configuration",
    )
    parser.add_argument(
        "--remove", "-r",
        action="store_true",
        help="Remove MCP server entry",
    )
    parser.add_argument(
        "--desktop", "-d",
        action="store_true",
        help="Configure Claude Desktop instead of CLI",
    )

    args = parser.parse_args()

    # Select config file
    if args.desktop:
        config_path = get_claude_desktop_config_path()
        target_name = "Claude Desktop"
    else:
        config_path = get_claude_cli_config_path()
        target_name = "Claude Code CLI"

    # Execute action
    if args.show:
        show_config(config_path)
        return 0

    if args.remove:
        remove_mcp_server(config_path, args.name)
        # Also deregister from port discovery manifest
        if not args.desktop:
            deregister_from_manifest(args.name)
        return 0

    # Default action: add/update
    try:
        add_mcp_server(
            config_path,
            port=args.port,
            host=args.host,
            server_name=args.name,
        )
        print(f"[OK] {target_name} configured: {config_path}")
        print(f"     Server: {args.name}")
        print(f"     URL: http://{args.host}:{args.port}/sse")

        # Register in port discovery manifest (CLI only, not Desktop)
        if not args.desktop and CONFIG_PATH:
            register_in_manifest(
                name=args.name,
                config_path_pattern=CONFIG_PATH,
                default_port=DEFAULT_PORT,
                host=args.host,
            )

        return 0
    except Exception as e:
        print(f"[ERROR] Failed to configure: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
