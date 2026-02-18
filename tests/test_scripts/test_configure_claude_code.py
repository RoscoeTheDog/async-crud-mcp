"""Tests for scripts/configure_claude_code.py."""

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# Import from the scripts directory
scripts_dir = Path(__file__).parent.parent.parent / "scripts"
sys.path.insert(0, str(scripts_dir))

import configure_claude_code


class TestAddMcpServer:
    """Test add_mcp_server()."""

    def test_add_to_empty_config(self, tmp_path):
        """Test adding server to non-existent config file."""
        config_path = tmp_path / ".claude.json"

        result = configure_claude_code.add_mcp_server(config_path, port=8720)

        assert config_path.exists()
        assert "mcpServers" in result
        assert "async-crud-mcp" in result["mcpServers"]
        entry = result["mcpServers"]["async-crud-mcp"]
        assert entry["type"] == "sse"
        assert entry["url"] == "http://127.0.0.1:8720/sse"

    def test_add_preserves_existing_servers(self, tmp_path):
        """Test adding server preserves other mcpServers entries."""
        config_path = tmp_path / ".claude.json"
        existing = {
            "mcpServers": {
                "other-server": {"type": "stdio", "command": "other"}
            }
        }
        config_path.write_text(json.dumps(existing))

        result = configure_claude_code.add_mcp_server(config_path, port=8720)

        assert "other-server" in result["mcpServers"]
        assert "async-crud-mcp" in result["mcpServers"]

    def test_add_with_custom_host_and_name(self, tmp_path):
        """Test adding with custom host and server name."""
        config_path = tmp_path / ".claude.json"

        result = configure_claude_code.add_mcp_server(
            config_path, port=9000, host="0.0.0.0", server_name="my-server"
        )

        assert "my-server" in result["mcpServers"]
        assert result["mcpServers"]["my-server"]["url"] == "http://0.0.0.0:9000/sse"

    def test_add_updates_existing_entry(self, tmp_path):
        """Test that re-adding overwrites the existing entry."""
        config_path = tmp_path / ".claude.json"

        configure_claude_code.add_mcp_server(config_path, port=8720)
        result = configure_claude_code.add_mcp_server(config_path, port=9999)

        assert result["mcpServers"]["async-crud-mcp"]["url"] == "http://127.0.0.1:9999/sse"

    def test_add_preserves_non_mcp_config(self, tmp_path):
        """Test that non-mcpServers keys are preserved."""
        config_path = tmp_path / ".claude.json"
        existing = {"theme": "dark", "version": 2}
        config_path.write_text(json.dumps(existing))

        result = configure_claude_code.add_mcp_server(config_path, port=8720)

        assert result["theme"] == "dark"
        assert result["version"] == 2


class TestRemoveMcpServer:
    """Test remove_mcp_server()."""

    def test_remove_existing_entry(self, tmp_path):
        """Test removing an existing server entry."""
        config_path = tmp_path / ".claude.json"
        config = {
            "mcpServers": {
                "async-crud-mcp": {"type": "sse", "url": "http://127.0.0.1:8720/sse"},
                "other": {"type": "stdio", "command": "other"},
            }
        }
        config_path.write_text(json.dumps(config))

        result = configure_claude_code.remove_mcp_server(config_path)

        assert "async-crud-mcp" not in result.get("mcpServers", {})
        assert "other" in result["mcpServers"]

    def test_remove_last_entry_cleans_section(self, tmp_path):
        """Test removing the last server cleans up empty mcpServers."""
        config_path = tmp_path / ".claude.json"
        config = {
            "mcpServers": {
                "async-crud-mcp": {"type": "sse", "url": "http://127.0.0.1:8720/sse"}
            }
        }
        config_path.write_text(json.dumps(config))

        result = configure_claude_code.remove_mcp_server(config_path)

        assert "mcpServers" not in result

    def test_remove_nonexistent_entry(self, tmp_path):
        """Test removing a server that doesn't exist is a no-op."""
        config_path = tmp_path / ".claude.json"
        config = {"mcpServers": {"other": {"type": "stdio"}}}
        config_path.write_text(json.dumps(config))

        result = configure_claude_code.remove_mcp_server(config_path)

        assert "other" in result["mcpServers"]

    def test_remove_from_nonexistent_file(self, tmp_path):
        """Test removing from non-existent config file."""
        config_path = tmp_path / ".claude.json"

        result = configure_claude_code.remove_mcp_server(config_path)

        assert result == {}


class TestRegisterInManifest:
    """Test register_in_manifest()."""

    def test_register_creates_manifest(self, tmp_path):
        """Test registration creates manifest file if missing."""
        manifest_path = tmp_path / ".claude" / "mcp-daemons.json"

        configure_claude_code.register_in_manifest(
            name="async-crud-mcp",
            config_path_pattern="$LOCALAPPDATA/async-crud-mcp/config/config.json",
            default_port=8720,
            manifest_path=manifest_path,
        )

        assert manifest_path.exists()
        manifest = json.loads(manifest_path.read_text())
        assert manifest["$schema"] == "mcp-daemons-manifest-v1"
        assert len(manifest["servers"]) == 1
        entry = manifest["servers"][0]
        assert entry["name"] == "async-crud-mcp"
        assert entry["defaultPort"] == 8720
        assert entry["type"] == "sse"

    def test_register_appends_to_existing(self, tmp_path):
        """Test registration appends to existing manifest."""
        manifest_path = tmp_path / "mcp-daemons.json"
        existing = {
            "$schema": "mcp-daemons-manifest-v1",
            "servers": [
                {"name": "other-server", "defaultPort": 9000, "type": "sse"}
            ],
        }
        manifest_path.write_text(json.dumps(existing))

        configure_claude_code.register_in_manifest(
            name="async-crud-mcp",
            config_path_pattern="test",
            default_port=8720,
            manifest_path=manifest_path,
        )

        manifest = json.loads(manifest_path.read_text())
        assert len(manifest["servers"]) == 2
        names = [s["name"] for s in manifest["servers"]]
        assert "other-server" in names
        assert "async-crud-mcp" in names

    def test_register_replaces_same_name(self, tmp_path):
        """Test re-registration replaces entry with same name."""
        manifest_path = tmp_path / "mcp-daemons.json"
        existing = {
            "$schema": "mcp-daemons-manifest-v1",
            "servers": [
                {"name": "async-crud-mcp", "defaultPort": 1111, "type": "sse"}
            ],
        }
        manifest_path.write_text(json.dumps(existing))

        configure_claude_code.register_in_manifest(
            name="async-crud-mcp",
            config_path_pattern="test",
            default_port=8720,
            manifest_path=manifest_path,
        )

        manifest = json.loads(manifest_path.read_text())
        assert len(manifest["servers"]) == 1
        assert manifest["servers"][0]["defaultPort"] == 8720


class TestDeregisterFromManifest:
    """Test deregister_from_manifest()."""

    def test_deregister_removes_entry(self, tmp_path):
        """Test deregistration removes the named entry."""
        manifest_path = tmp_path / "mcp-daemons.json"
        manifest = {
            "$schema": "mcp-daemons-manifest-v1",
            "servers": [
                {"name": "async-crud-mcp", "defaultPort": 8720},
                {"name": "other", "defaultPort": 9000},
            ],
        }
        manifest_path.write_text(json.dumps(manifest))

        configure_claude_code.deregister_from_manifest(
            name="async-crud-mcp", manifest_path=manifest_path
        )

        result = json.loads(manifest_path.read_text())
        assert len(result["servers"]) == 1
        assert result["servers"][0]["name"] == "other"

    def test_deregister_nonexistent_entry(self, tmp_path):
        """Test deregistering a name that doesn't exist."""
        manifest_path = tmp_path / "mcp-daemons.json"
        manifest = {
            "$schema": "mcp-daemons-manifest-v1",
            "servers": [{"name": "other", "defaultPort": 9000}],
        }
        manifest_path.write_text(json.dumps(manifest))

        configure_claude_code.deregister_from_manifest(
            name="async-crud-mcp", manifest_path=manifest_path
        )

        result = json.loads(manifest_path.read_text())
        assert len(result["servers"]) == 1

    def test_deregister_missing_manifest(self, tmp_path):
        """Test deregistering when manifest doesn't exist is a no-op."""
        manifest_path = tmp_path / "mcp-daemons.json"

        # Should not raise
        configure_claude_code.deregister_from_manifest(
            name="async-crud-mcp", manifest_path=manifest_path
        )

        assert not manifest_path.exists()


class TestShowConfig:
    """Test show_config()."""

    def test_show_existing_config(self, tmp_path, capsys):
        """Test showing config with MCP servers."""
        config_path = tmp_path / ".claude.json"
        config = {
            "mcpServers": {
                "async-crud-mcp": {"type": "sse", "url": "http://127.0.0.1:8720/sse"}
            }
        }
        config_path.write_text(json.dumps(config))

        configure_claude_code.show_config(config_path)

        captured = capsys.readouterr()
        assert "async-crud-mcp" in captured.out
        assert "sse" in captured.out
        assert "8720" in captured.out

    def test_show_nonexistent_config(self, tmp_path, capsys):
        """Test showing non-existent config file."""
        config_path = tmp_path / ".claude.json"

        configure_claude_code.show_config(config_path)

        captured = capsys.readouterr()
        assert "does not exist" in captured.out


class TestMain:
    """Test main() CLI entry point."""

    def test_main_show(self, tmp_path, monkeypatch):
        """Test --show flag."""
        config_path = tmp_path / ".claude.json"
        monkeypatch.setattr(
            configure_claude_code,
            "get_claude_cli_config_path",
            lambda: config_path,
        )
        monkeypatch.setattr("sys.argv", ["configure_claude_code.py", "--show"])

        result = configure_claude_code.main()

        assert result == 0

    def test_main_add_default(self, tmp_path, monkeypatch):
        """Test default add action."""
        config_path = tmp_path / ".claude.json"
        manifest_path = tmp_path / ".claude" / "mcp-daemons.json"

        monkeypatch.setattr(
            configure_claude_code,
            "get_claude_cli_config_path",
            lambda: config_path,
        )
        monkeypatch.setattr(
            configure_claude_code,
            "get_manifest_path",
            lambda: manifest_path,
        )
        monkeypatch.setattr("sys.argv", ["configure_claude_code.py"])

        result = configure_claude_code.main()

        assert result == 0
        assert config_path.exists()
        config = json.loads(config_path.read_text())
        assert "async-crud-mcp" in config["mcpServers"]

    def test_main_remove(self, tmp_path, monkeypatch):
        """Test --remove flag."""
        config_path = tmp_path / ".claude.json"
        config = {
            "mcpServers": {
                "async-crud-mcp": {"type": "sse", "url": "http://127.0.0.1:8720/sse"}
            }
        }
        config_path.write_text(json.dumps(config))

        monkeypatch.setattr(
            configure_claude_code,
            "get_claude_cli_config_path",
            lambda: config_path,
        )
        monkeypatch.setattr("sys.argv", ["configure_claude_code.py", "--remove"])

        result = configure_claude_code.main()

        assert result == 0
        updated = json.loads(config_path.read_text())
        assert "mcpServers" not in updated

    def test_main_desktop_flag(self, tmp_path, monkeypatch):
        """Test --desktop flag targets Claude Desktop config."""
        desktop_path = tmp_path / "claude_desktop_config.json"

        monkeypatch.setattr(
            configure_claude_code,
            "get_claude_desktop_config_path",
            lambda: desktop_path,
        )
        monkeypatch.setattr(
            "sys.argv", ["configure_claude_code.py", "--desktop"]
        )

        result = configure_claude_code.main()

        assert result == 0
        assert desktop_path.exists()
        config = json.loads(desktop_path.read_text())
        assert "async-crud-mcp" in config["mcpServers"]


class TestLoadConfig:
    """Test load_config() edge cases."""

    def test_load_invalid_json(self, tmp_path):
        """Test loading invalid JSON returns empty dict."""
        config_path = tmp_path / "bad.json"
        config_path.write_text("not valid json {{{")

        result = configure_claude_code.load_config(config_path)

        assert result == {}

    def test_load_nonexistent(self, tmp_path):
        """Test loading non-existent file returns empty dict."""
        config_path = tmp_path / "missing.json"

        result = configure_claude_code.load_config(config_path)

        assert result == {}
