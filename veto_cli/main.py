"""
Veto CLI — main entrypoint.

Commands:
    veto init          Auto-configure Veto MCP for installed AI clients
    veto test          Fire a test transaction to verify connection
    veto status        Show reputation + recent transactions
    veto list          List installed MCP clients with Veto
    veto uninstall     Remove Veto from an MCP client
    veto mcp           Run the MCP server directly (for manual configs)
"""

import argparse
import json
import os
import sys

from veto_cli import api, config_paths, mcp_config


# ── Pretty print helpers ──

class C:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    VIOLET = "\033[95m"
    CYAN = "\033[96m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    GRAY = "\033[90m"


def banner():
    """Modern CLI wordmark banner — shown on primary commands."""
    c = C.CYAN
    d = C.DIM
    r = C.RESET
    b = C.BOLD
    print()
    print(f"  {b}{c}██╗   ██╗███████╗████████╗ ██████╗{r}")
    print(f"  {b}{c}██║   ██║██╔════╝╚══██╔══╝██╔═══██╗{r}")
    print(f"  {b}{c}██║   ██║█████╗     ██║   ██║   ██║{r}")
    print(f"  {b}{c}╚██╗ ██╔╝██╔══╝     ██║   ██║   ██║{r}")
    print(f"  {b}{c} ╚████╔╝ ███████╗   ██║   ╚██████╔╝{r}")
    print(f"  {b}{c}  ╚═══╝  ╚══════╝   ╚═╝    ╚═════╝ {r}")
    print()
    print(f"  {d}authorization layer for AI agents{r}   {b}{c}veto-ai.com{r}")
    print()


def mini_banner():
    """Compact single-line banner — shown on secondary commands."""
    print()
    print(f"  {C.BOLD}{C.CYAN}veto{C.RESET} {C.DIM}·{C.RESET} {C.CYAN}authorization layer{C.RESET}")
    print()


def ok(msg):
    print(f"  {C.GREEN}✓{C.RESET} {msg}")


def warn(msg):
    print(f"  {C.YELLOW}!{C.RESET} {msg}")


def err(msg):
    print(f"  {C.RED}✗{C.RESET} {msg}")


def info(msg):
    print(f"  {C.DIM}·{C.RESET} {msg}")


def _prompt(question: str, default: str | None = None) -> str:
    suffix = f" {C.DIM}[{default}]{C.RESET}" if default else ""
    val = input(f"  {C.CYAN}?{C.RESET} {question}{suffix} ").strip()
    return val or (default or "")


# ── Storage for CLI state (API key, base URL) ──

STATE_PATH = os.path.expanduser("~/.veto/config.json")


def _save_state(state: dict):
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    with open(STATE_PATH, "w") as f:
        json.dump(state, f, indent=2)
    os.chmod(STATE_PATH, 0o600)


def _load_state() -> dict:
    if not os.path.exists(STATE_PATH):
        return {}
    try:
        with open(STATE_PATH) as f:
            return json.load(f)
    except Exception:
        return {}


# ── Commands ──

def cmd_init(args):
    banner()
    print(f"  {C.BOLD}Welcome to Veto.{C.RESET}")
    print(f"  {C.DIM}We'll auto-configure MCP for your AI agents.{C.RESET}")
    print()

    # Get API key
    state = _load_state()
    api_key = args.api_key or state.get("api_key")
    base_url = args.base_url or state.get("base_url", "https://veto-ai.com")

    if not api_key:
        print(f"  {C.DIM}Get your API key at {base_url}/dashboard/signup/{C.RESET}")
        print()
        api_key = _prompt("Paste your Veto API key:").strip()
        if not api_key or not api_key.startswith("veto_"):
            err("That doesn't look like a valid Veto API key.")
            sys.exit(1)

    # Verify key
    print()
    info("Verifying API key...")
    if not api.verify_key(base_url, api_key):
        err("API key is invalid or the Veto server is unreachable.")
        sys.exit(1)
    ok("API key verified.")

    # Save state
    _save_state({"api_key": api_key, "base_url": base_url})
    info(f"Config saved to {C.DIM}{STATE_PATH}{C.RESET}")

    # Detect installed clients
    print()
    installed = config_paths.detect_installed_clients()
    if not installed:
        warn("No MCP clients detected (Claude Desktop, Cursor, Zed, Continue).")
        warn("Install one of those and run `veto init` again,")
        warn("or use the manual config at https://veto-ai.com/dashboard/integration/")
        sys.exit(0)

    # Show menu
    print(f"  {C.BOLD}Detected MCP clients:{C.RESET}")
    for i, (name, path) in enumerate(installed.items(), 1):
        label = config_paths.CLIENT_LABELS.get(name, name)
        print(f"    {C.CYAN}{i}.{C.RESET} {label}  {C.DIM}{path}{C.RESET}")
    print(f"    {C.CYAN}{len(installed) + 1}.{C.RESET} All of the above")
    print()

    if args.yes:
        choice = str(len(installed) + 1)  # Install everywhere non-interactively
    else:
        choice = _prompt("Install Veto into which client?", default=str(len(installed) + 1))

    targets = []
    if choice == str(len(installed) + 1):
        targets = list(installed.items())
    else:
        try:
            idx = int(choice) - 1
            name = list(installed.keys())[idx]
            targets = [(name, installed[name])]
        except (ValueError, IndexError):
            err("Invalid choice.")
            sys.exit(1)

    # Install
    print()
    for name, path in targets:
        installer = mcp_config.INSTALLERS.get(name)
        if not installer:
            warn(f"No installer for {name}, skipping.")
            continue
        try:
            added = installer(path, api_key, base_url)
            label = config_paths.CLIENT_LABELS.get(name, name)
            if added:
                ok(f"Added Veto to {C.BOLD}{label}{C.RESET}")
            else:
                ok(f"Updated Veto config in {C.BOLD}{label}{C.RESET}")
        except Exception as e:
            err(f"Failed to configure {name}: {e}")

    # Final instructions
    print()
    print(f"  {C.BOLD}{C.GREEN}✓ Done.{C.RESET}")
    print()
    print(f"  {C.DIM}Restart your MCP client to activate Veto.{C.RESET}")
    print(f"  {C.DIM}Then tell your agent to use the {C.RESET}veto_authorize{C.DIM} tool before spending money.{C.RESET}")
    print()
    print(f"  {C.DIM}Test with:{C.RESET}  {C.BOLD}veto test{C.RESET}")
    print(f"  {C.DIM}Dashboard:{C.RESET}  {C.BOLD}{base_url}/dashboard/{C.RESET}")
    print()


def cmd_test(args):
    mini_banner()
    state = _load_state()
    api_key = args.api_key or state.get("api_key")
    base_url = args.base_url or state.get("base_url", "https://veto-ai.com")

    if not api_key:
        err("No API key configured. Run `veto init` first.")
        sys.exit(1)

    agent_id = args.agent_id or _prompt("Agent UUID to test with:")
    if not agent_id:
        err("Agent ID required.")
        sys.exit(1)

    print()
    info(f"Firing test transaction: $75 to Google Ads...")
    try:
        r = api.authorize(
            base_url, api_key, agent_id,
            amount=75.00,
            merchant="Google Ads",
            description="Test transaction from veto CLI",
            context="Test transaction from veto CLI to verify MCP integration",
        )
    except api.VetoAPIError as e:
        err(f"Request failed: {e}")
        sys.exit(1)

    status = r.get("status")
    risk = r.get("risk_score", 0)

    if status == "executed":
        card = r.get("result", {})
        print()
        ok(f"{C.BOLD}{C.GREEN}APPROVED{C.RESET} — Risk: {risk:.2f}")
        info(f"Virtual card: *{card.get('last4', '????')} ({card.get('brand', 'Visa')}) · ${card.get('funding_amount', '?')}")
        info(f"Stripe ID:    {card.get('card_id')}")
        print()
        info("Veto successfully approved this transaction and issued a real Stripe test card.")
    elif status == "denied":
        print()
        warn(f"{C.BOLD}BLOCKED{C.RESET} — {r.get('reason', 'unknown')}")
        info("(This is expected behavior if the policy was strict.)")
    elif status == "escalated":
        print()
        warn(f"{C.BOLD}ESCALATED{C.RESET} — Transaction requires human approval.")
        info(f"Review it at {base_url}/dashboard/")
    else:
        err(f"Unexpected response: {r}")
    print()


def cmd_status(args):
    mini_banner()
    state = _load_state()
    base_url = args.base_url or state.get("base_url", "https://veto-ai.com")

    agent_id = args.agent_id
    if not agent_id:
        err("Agent ID required. Usage: veto status <agent_id>")
        sys.exit(1)

    try:
        rep = api.get_reputation(base_url, agent_id)
    except api.VetoAPIError as e:
        err(f"Request failed: {e}")
        sys.exit(1)

    if rep.get("error"):
        err(rep["error"])
        sys.exit(1)

    score = rep.get("score", 0)
    tier = rep.get("tier_label", "Unknown")
    total = rep.get("total_transactions", 0)
    days = rep.get("days_active", 0)

    # Tier color
    tier_colors = {"Elite": C.GREEN, "Trusted": C.CYAN, "Standard": C.GRAY, "Risky": C.RED}
    color = tier_colors.get(tier, C.GRAY)

    print()
    print(f"  {C.BOLD}Reputation — {rep.get('agent_id', 'unknown')[:8]}...{C.RESET}")
    print()

    # Score bar
    bar_len = 40
    filled = int(bar_len * score / 1000)
    bar = f"{color}{'█' * filled}{C.DIM}{'░' * (bar_len - filled)}{C.RESET}"
    print(f"  {bar}  {C.BOLD}{score}{C.RESET}/1000")
    print()
    print(f"  {C.DIM}Tier:{C.RESET}          {color}{C.BOLD}{tier}{C.RESET}")
    print(f"  {C.DIM}Transactions:{C.RESET}  {total}")
    print(f"  {C.DIM}Days active:{C.RESET}   {days}")
    print()


def cmd_list(args):
    mini_banner()
    detected = config_paths.detect_installed_clients()
    if not detected:
        warn("No MCP clients detected.")
        return

    print(f"  {C.BOLD}MCP client status:{C.RESET}")
    print()
    for name, path in detected.items():
        label = config_paths.CLIENT_LABELS.get(name, name)
        installed = mcp_config.get_installed_block(name, path)
        if installed:
            print(f"    {C.GREEN}✓{C.RESET} {label:20s}  {C.DIM}{path}{C.RESET}")
        else:
            print(f"    {C.GRAY}·{C.RESET} {label:20s}  {C.DIM}not configured{C.RESET}")
    print()


def cmd_uninstall(args):
    mini_banner()
    detected = config_paths.detect_installed_clients()
    removed = False
    for name, path in detected.items():
        if mcp_config.uninstall(name, path):
            label = config_paths.CLIENT_LABELS.get(name, name)
            ok(f"Removed Veto from {label}")
            removed = True
    if not removed:
        info("Nothing to remove.")
    print()


def cmd_mcp(args):
    """Run the MCP server directly (for manual use)."""
    from veto_cli import mcp_server
    mcp_server.main()


# ── Entry point ──

def main():
    parser = argparse.ArgumentParser(
        prog="veto",
        description="Veto CLI — authorization for AI agents",
    )
    parser.add_argument("--api-key", help="Override saved API key")
    parser.add_argument("--base-url", help="Veto server URL (default: https://veto-ai.com)")

    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init", help="Auto-configure MCP for installed AI clients")
    p_init.add_argument("--yes", "-y", action="store_true", help="Install into all detected clients without prompting")
    p_init.set_defaults(func=cmd_init)

    p_test = sub.add_parser("test", help="Fire a test transaction")
    p_test.add_argument("agent_id", nargs="?", help="Agent UUID")
    p_test.set_defaults(func=cmd_test)

    p_status = sub.add_parser("status", help="Show agent reputation")
    p_status.add_argument("agent_id", help="Agent UUID")
    p_status.set_defaults(func=cmd_status)

    p_list = sub.add_parser("list", help="List MCP clients and Veto status")
    p_list.set_defaults(func=cmd_list)

    p_uninstall = sub.add_parser("uninstall", help="Remove Veto from all MCP clients")
    p_uninstall.set_defaults(func=cmd_uninstall)

    p_mcp = sub.add_parser("mcp", help="Run the MCP server (used by MCP clients)")
    p_mcp.set_defaults(func=cmd_mcp)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
