"""
Detect MCP client config file paths on the user's system.

Supports:
  - Claude Desktop (Anthropic)
  - Cursor
  - Zed
  - Continue (VS Code extension)
  - Generic/custom config
"""

import os
import platform
from pathlib import Path


def _home() -> Path:
    return Path.home()


def claude_desktop_config() -> Path:
    """Anthropic Claude Desktop MCP config path."""
    system = platform.system()
    if system == "Darwin":
        return _home() / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
    elif system == "Windows":
        return Path(os.environ.get("APPDATA", "")) / "Claude" / "claude_desktop_config.json"
    else:  # Linux
        return _home() / ".config" / "Claude" / "claude_desktop_config.json"


def cursor_config() -> Path:
    """Cursor MCP config path."""
    return _home() / ".cursor" / "mcp.json"


def zed_config() -> Path:
    """Zed MCP config path."""
    return _home() / ".config" / "zed" / "settings.json"


def continue_config() -> Path:
    """Continue (VS Code) MCP config path."""
    return _home() / ".continue" / "config.json"


def detect_installed_clients() -> dict:
    """
    Scan for which MCP clients are installed.
    Returns dict of {client_name: path_or_None}.

    A client is considered "installed" if its config directory exists,
    even if the config file itself doesn't (we'll create it).
    """
    candidates = {
        "claude_desktop": claude_desktop_config(),
        "cursor": cursor_config(),
        "zed": zed_config(),
        "continue": continue_config(),
    }

    installed = {}
    for name, path in candidates.items():
        if path.parent.exists():
            installed[name] = path
        elif path.exists():
            installed[name] = path

    return installed


CLIENT_LABELS = {
    "claude_desktop": "Claude Desktop",
    "cursor": "Cursor",
    "zed": "Zed",
    "continue": "Continue (VS Code)",
}
