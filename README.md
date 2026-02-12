# async-crud-mcp

A Python daemon MCP (Model Context Protocol) server built with [FastMCP](https://github.com/jlowin/fastmcp) that provides file-locking async CRUD operations designed for concurrent AI agent use.

## Overview

This server exposes Create, Read, Update, and Delete tools over MCP with built-in file-locking to safely handle concurrent access from multiple AI agents. It runs as a persistent daemon process, supporting both stdio and HTTP (Streamable HTTP) transports.

## Features

- Async file-locking CRUD operations
- Safe concurrent access for multiple AI agents
- FastMCP-based MCP server (Python 3.12+)
- Stdio and HTTP transport support
- Daemon process mode

## Getting Started

> **Prerequisites**: Python 3.12+, [uv](https://docs.astral.sh/uv/)

```bash
# Clone the repository
git clone https://github.com/RoscoeTheDog/async-crud-mcp.git
cd async-crud-mcp

# Install dependencies
uv sync

# Run the server (stdio)
uv run python -m async_crud_mcp

# Run the server (HTTP daemon)
uv run python -m async_crud_mcp --transport http --port 8000
```

## License

[MIT](LICENSE)
