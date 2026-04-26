"""
Inject/remove Veto MCP server config in a client's config file.

Each MCP client uses roughly the same JSON shape:
    {
      "mcpServers": {
        "veto": { "command": "...", "args": [...] }
      }
    }

Cursor uses "mcpServers" too. Claude Desktop uses "mcpServers". Zed uses
"context_servers" with a slightly different shape. We handle each.
"""

import json
from pathlib import Path


MCP_SERVER_NAME = "veto"


def _veto_server_block(api_key: str, veto_base_url: str = "https://veto-ai.com") -> dict:
    """
    Build the MCP server config block that invokes the Veto MCP server.

    Users don't need the server file locally — they run it via pipx/uvx
    from PyPI when it's published. For now, we use a Python invocation.
    """
    return {
        "command": "python3",
        "args": [
            "-m", "veto_cli.mcp_server",
            "--api-key", api_key,
            "--base-url", veto_base_url,
        ],
        "env": {
            "VETO_API_KEY": api_key,
            "VETO_BASE_URL": veto_base_url,
        },
    }


def _load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _save_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def install_claude_desktop(path: Path, api_key: str, base_url: str = "https://veto-ai.com") -> bool:
    """Inject Veto into Claude Desktop config. Returns True if added, False if already present."""
    data = _load_json(path)
    servers = data.setdefault("mcpServers", {})
    already = MCP_SERVER_NAME in servers
    servers[MCP_SERVER_NAME] = _veto_server_block(api_key, base_url)
    _save_json(path, data)
    return not already


def install_cursor(path: Path, api_key: str, base_url: str = "https://veto-ai.com") -> bool:
    """Inject Veto into Cursor MCP config."""
    data = _load_json(path)
    servers = data.setdefault("mcpServers", {})
    already = MCP_SERVER_NAME in servers
    servers[MCP_SERVER_NAME] = _veto_server_block(api_key, base_url)
    _save_json(path, data)
    return not already


def install_zed(path: Path, api_key: str, base_url: str = "https://veto-ai.com") -> bool:
    """
    Inject Veto into Zed settings.json.
    Zed uses 'context_servers' with a different shape.
    """
    data = _load_json(path)
    servers = data.setdefault("context_servers", {})
    already = MCP_SERVER_NAME in servers
    servers[MCP_SERVER_NAME] = _veto_server_block(api_key, base_url)
    _save_json(path, data)
    return not already


def install_continue(path: Path, api_key: str, base_url: str = "https://veto-ai.com") -> bool:
    """Inject Veto into Continue config."""
    data = _load_json(path)
    servers = data.setdefault("mcpServers", {})
    already = MCP_SERVER_NAME in servers
    servers[MCP_SERVER_NAME] = _veto_server_block(api_key, base_url)
    _save_json(path, data)
    return not already


INSTALLERS = {
    "claude_desktop": install_claude_desktop,
    "cursor": install_cursor,
    "zed": install_zed,
    "continue": install_continue,
}


def uninstall(client: str, path: Path) -> bool:
    """Remove Veto from a client config. Returns True if removed."""
    data = _load_json(path)

    if client == "zed":
        key = "context_servers"
    else:
        key = "mcpServers"

    servers = data.get(key, {})
    if MCP_SERVER_NAME not in servers:
        return False

    del servers[MCP_SERVER_NAME]
    _save_json(path, data)
    return True


def get_installed_block(client: str, path: Path) -> dict | None:
    """Return the Veto MCP block from a client config, if present."""
    data = _load_json(path)
    key = "context_servers" if client == "zed" else "mcpServers"
    return data.get(key, {}).get(MCP_SERVER_NAME)
