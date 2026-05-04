"""
Veto CLI — main entrypoint.

Commands:
    veto register      CLI-native signup — get an API key + default agent in one command
    veto authorize     Ask Veto whether an agent action is allowed (headline command)
    veto verify        Verify a Veto signed decision receipt (offline, via JWKS)
    veto policy        Author / inspect / dry-run security policies (YAML)
    veto init          Auto-configure Veto MCP for installed AI clients (post-register)
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
from pathlib import Path

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
    """Full Veto wordmark banner — same as the install.sh banner.
    Auto-converted from frontend/public/veto-logo.png via chafa
    (block symbols, 64x14). Renders cleanly in any monospace font
    that supports unicode block characters."""
    c = C.CYAN
    d = C.DIM
    r = C.RESET
    b = C.BOLD
    logo = '''       ▃▄▆▇▇██▇▇▆▄▃
    ▂▆██████████████▆▂
  ▗▟██████████████████▙▖
 ▗██████████████████████▖
 ████████████████████████▖                ▗▅▆▋
▐██████████▉▔▔▔▝██████▛▔▔       ▂▂▁       ▐██▊         ▁▂▂▁
▟███████████▍   ▐█████   ▗▎  ▄▇█████▆▃  ▐███████▋   ▁▅▇█████▆▃
▐████████████    ████▌   █▎ ▟█▛▔   ▝██▙  ▔▐██▊▔▔   ▗██▛▔  ▔▝██▇▖
▐████████████▙   ▝██▉   ▟█ ▐██▃▃▃▃▃▃▐██▎  ▐██▊    ▕██▉      ▝██▊
 ▜████████████▍   ▜█▘  ▗█▍ ▐██▀▀▀▀▀▀▀▀▀▘  ▐██▊    ▕██▊      ▕███
 ▝▜████████████   ▝▛   █▛  ▐██▍           ▐██▊     ███      ▗██▋
   ▀███████████▙      ▟▀    ▀██▅▃▁▁▂▂▄    ▕███▃▂▃  ▝██▇▃▂▂▂▄██▛
    ▔▀██████████▖     ▔      ▔▀▜█████▀▘    ▝▜████    ▀▀████▛▀▔
       ▔▀▀▀█████▛                                               '''
    print()
    for line in logo.split("\n"):
        print(f"  {b}{c}{line}{r}")
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


# Allowed action types — must match Transaction.ActionType in the backend.
# CLI doesn't enforce these (backend is authoritative); listed in --help for transparency.
_ALLOWED_ACTIONS = ("payment", "crypto_transfer", "tool_execution")

# Policy presets — must match keys in policies/presets.py POLICY_PRESETS on the backend.
# CLI doesn't enforce these (backend is authoritative); listed in --help for transparency.
_ALLOWED_PRESETS = ("personal", "inference", "x402-micropay", "ad-spend", "dev")

_STDIN_FIELDS = {"agent_id", "agent", "amount", "merchant", "action", "description", "context"}


def cmd_register(args):
    """
    CLI-native signup — POST /api/v1/register/, save API key + default agent UUID locally.

    No web form, no email verification (yet). Just an email and a preset →
    a working account in one command.
    """
    base_url = args.base_url or "https://veto-ai.com"

    # Warn if user already has an API key saved — we'd overwrite ~/.veto/config.json.
    state = _load_state()
    if state.get("api_key") and not args.yes:
        warn(f"You already have an API key saved at {STATE_PATH}.")
        warn(f"Existing key: {state['api_key'][:24]}...")
        confirm = _prompt("Overwrite with new account? (y/N)", default="N")
        if confirm.strip().lower() not in ("y", "yes"):
            info("Cancelled. Your existing config is unchanged.")
            sys.exit(0)

    banner()
    info(f"Registering {args.email} with preset '{args.preset or 'personal'}'...")
    print()

    try:
        r = api.register(
            base_url,
            email=args.email,
            preset=args.preset,
            mission=args.mission,
            agent_name=args.agent_name,
            org_name=args.org_name,
        )
    except api.VetoAPIError as e:
        # Errors to stderr so success-path stdout stays clean for piping.
        _eprint(f"  {C.RED}✗{C.RESET} Registration failed: {e}")
        if e.status_code == 409:
            _eprint(f"  {C.DIM}·{C.RESET} Use a different email, or run `veto init --api-key <existing>` if you already have a key.")
        sys.exit(3)

    # Save state — API key + default agent so subsequent `veto authorize` doesn't need flags.
    _save_state({
        "api_key": r["api_key"],
        "base_url": base_url,
        "default_agent": r["agent_id"],
    })

    # Pretty print the account summary.
    p = r["policy"]
    print(f"  {C.BOLD}{C.GREEN}✓ Welcome to Veto.{C.RESET}")
    print()
    print(f"  {C.DIM}Email:{C.RESET}      {args.email}")
    print(f"  {C.DIM}Org:{C.RESET}        {r.get('org_name', '')}")
    print(f"  {C.DIM}Agent:{C.RESET}      {r['agent_name']}  {C.DIM}({r['agent_id']}){C.RESET}")
    print(f"  {C.DIM}Mission:{C.RESET}    {r['mission']}")
    print(f"  {C.DIM}Policy:{C.RESET}     {p['name']} preset")
    print(f"             {C.DIM}max ${p['max_per_tx']}/tx · ${p['daily_limit']}/day · ${p['monthly_limit']}/mo{C.RESET}")
    if p.get("auto_approve_below"):
        print(f"             {C.DIM}auto-approve below ${p['auto_approve_below']}{C.RESET}")
    if p.get("require_human_approval_above"):
        print(f"             {C.DIM}escalate above ${p['require_human_approval_above']}{C.RESET}")
    if p.get("merchant_blocklist"):
        print(f"             {C.DIM}blocks: {', '.join(p['merchant_blocklist'])}{C.RESET}")
    if p.get("merchant_allowlist"):
        print(f"             {C.DIM}allows: {', '.join(p['merchant_allowlist'])}{C.RESET}")
    if p.get("chain_allowlist"):
        print(f"             {C.DIM}chains: {', '.join(p['chain_allowlist'])}{C.RESET}")
    print(f"  {C.DIM}API key:{C.RESET}    saved to {STATE_PATH}")
    print()
    # Build example commands that actually behave as advertised under the
    # preset just registered:
    #   - approve example uses the first merchant from the policy allowlist
    #     (or api.openai.com as a sensible default when no allowlist exists)
    #   - deny example uses 2x the per-tx cap so it exceeds JUST that cap,
    #     keeping the reason_codes output tight (avoids also tripping the
    #     daily/monthly caps).
    _allowlist = p.get("merchant_allowlist") or []
    _ok_merchant = _allowlist[0] if _allowlist else "api.openai.com"
    try:
        _max_per_tx = float(p.get("max_per_tx") or 5)
    except (TypeError, ValueError):
        _max_per_tx = 5.0
    _deny_amount = round(_max_per_tx * 2, 2)
    _deny_amount_str = f"{int(_deny_amount)}" if _deny_amount.is_integer() else f"{_deny_amount}"

    print(f"  {C.BOLD}Try it:{C.RESET}")
    print(f"    {C.CYAN}veto authorize --amount {_deny_amount_str} --merchant amazon.com --action payment{C.RESET}")
    print(f"    {C.DIM}→ should be DENIED (over per-tx cap){C.RESET}")
    print()
    print(f"    {C.CYAN}veto authorize --amount 0.05 --merchant {_ok_merchant} --action payment{C.RESET}")
    print(f"    {C.DIM}→ should be APPROVED{C.RESET}")
    print()


def _eprint(msg: str = "") -> None:
    """Print to stderr — used by cmd_authorize so stdout stays machine-readable."""
    print(msg, file=sys.stderr)


def _eerr(msg: str) -> None:
    """Stderr-equivalent of err() — keeps stdout clean for `veto policy show > file`."""
    print(f"  {C.RED}✗{C.RESET} {msg}", file=sys.stderr)


def _einfo(msg: str) -> None:
    """Stderr-equivalent of info() — used for context lines that follow _eerr()."""
    print(f"  {C.DIM}·{C.RESET} {msg}", file=sys.stderr)


def cmd_authorize(args):
    """
    Ask Veto whether an agent action is allowed.

    Two input modes:
      1. Flags:    veto authorize --agent <uuid> --amount 0.05 --merchant ... --action payment
      2. Stdin:    echo '{"agent_id":"...","amount":0.05,...}' | veto authorize -

    Output:
      - Default: human-readable with color
      - --json:  JSON object passed through from the API response
      - --quiet: silent, exit code only

    Exit codes:
      0 = approved   1 = denied   2 = escalated   3 = error
    """
    state = _load_state()
    api_key = args.api_key or state.get("api_key")
    base_url = args.base_url or state.get("base_url", "https://veto-ai.com")

    # Resolve input (stdin vs flags)
    use_stdin = args.stdin == "-"
    if use_stdin:
        try:
            payload = json.load(sys.stdin)
            if not isinstance(payload, dict):
                raise ValueError("stdin must be a JSON object")
        except (json.JSONDecodeError, ValueError) as e:
            if args.json:
                print(json.dumps({"status": "error", "error": f"invalid stdin JSON: {e}"}))
            elif not args.quiet:
                _eprint(f"  {C.RED}✗{C.RESET} Invalid JSON on stdin: {e}")
            sys.exit(3)
        # Fall back to default_agent from config when stdin doesn't specify one.
        agent_id = payload.get("agent_id") or payload.get("agent") or state.get("default_agent")
        amount = payload.get("amount")
        merchant = payload.get("merchant", "")
        action = payload.get("action")
        description = payload.get("description", "")
        context = payload.get("context", "")
        extra = {k: v for k, v in payload.items() if k not in _STDIN_FIELDS}
    else:
        # `veto register` saves the default agent UUID to ~/.veto/config.json so users
        # don't have to retype --agent every time. --agent flag still wins if supplied.
        agent_id = args.agent or state.get("default_agent")
        amount = args.amount
        merchant = args.merchant or ""
        action = args.action
        description = args.description or ""
        context = args.context or ""
        extra = None

    # Validate
    missing = []
    if not api_key:
        missing.append("API key (run `veto init` or pass --api-key)")
    if not agent_id:
        missing.append("--agent / agent_id")
    if amount is None:
        missing.append("--amount")
    if not action:
        missing.append("--action")
    if missing:
        if args.json:
            print(json.dumps({"status": "error", "error": f"missing: {', '.join(missing)}"}))
        elif not args.quiet:
            _eprint(f"  {C.RED}✗{C.RESET} Missing required input: {', '.join(missing)}")
            _eprint(f"  {C.DIM}Run `veto authorize --help` for usage.{C.RESET}")
        sys.exit(3)

    # Call API
    try:
        r = api.authorize(
            base_url, api_key, agent_id,
            amount=amount,
            merchant=merchant,
            description=description,
            context=context,
            action=action,
            decision_only=True,
            extra=extra,
        )
    except api.VetoAPIError as e:
        if args.json:
            payload = {"status": "error", "error": str(e)}
            if e.status_code:
                payload["status_code"] = e.status_code
            print(json.dumps(payload))
        elif not args.quiet:
            _eprint(f"  {C.RED}✗{C.RESET} Request failed: {e}")
        sys.exit(3)

    status = r.get("status")

    # Human-readable output
    if args.json:
        print(json.dumps(r))
    elif not args.quiet:
        risk = r.get("risk_score") or 0
        tx_id = r.get("transaction_id", "")
        receipt = r.get("receipt", "")
        reason = r.get("reason", "")
        reason_codes = r.get("reason_codes", []) or []

        # Pull richer fields out of the signed receipt so we can show the
        # engine's actual work. parse_receipt_unsafe is for *display only* —
        # use `veto verify` for cryptographic validation.
        policy_name = ""
        policy_version = ""
        policy_hash = ""
        engine_version = ""
        decision_layer = ""
        input_fp = ""
        if receipt:
            try:
                from veto_cli import receipts as _rcpt
                _hdr, _payload, _sig, _input = _rcpt.parse_receipt_unsafe(receipt)
                _policy = _payload.get("policy") or {}
                policy_name = _policy.get("name", "")
                policy_version = _policy.get("version_number", "")
                policy_hash = _policy.get("hash", "")
                engine_version = _payload.get("engine_version", "")
                decision_layer = _payload.get("decision_layer", "")
                input_fp = _payload.get("input_fingerprint", "")
                # If reason_codes weren't returned at top level, pull from receipt.
                if not reason_codes:
                    reason_codes = _payload.get("reason_codes", []) or []
            except Exception:
                pass  # fall through to minimal output

        def _fmt_hash(h: str, width: int = 16) -> str:
            return f"{h[:width]}…" if len(h) > width else h

        def _fmt_codes(codes):
            return ", ".join(f"{C.BOLD}{c}{C.RESET}" for c in codes) if codes else f"{C.DIM}—{C.RESET}"

        print()

        # ── Decision banner
        if status in ("approved", "executed"):
            badge = f"{C.BOLD}{C.GREEN}✓ APPROVED{C.RESET}"
        elif status == "denied":
            badge = f"{C.BOLD}{C.RED}✗ DENIED{C.RESET}"
        elif status == "escalated":
            badge = f"{C.BOLD}{C.YELLOW}⏸ ESCALATED{C.RESET}"
        else:
            err(f"Unexpected response status: {status}")
            info(f"raw: {r}")
            print()
            # fall through to exit code logic below

        if status in ("approved", "executed", "denied", "escalated"):
            engine_suffix = f"  {C.DIM}·  engine v{engine_version}{C.RESET}" if engine_version else ""
            print(f"  {badge}  {C.DIM}·  risk {risk:.2f}{C.RESET}{engine_suffix}")
            print()

            # ── Why (denied + escalated only — explains the call)
            if status == "denied" and reason:
                print(f"    {C.BOLD}why{C.RESET}")
                # `reason` is sometimes a single sentence, sometimes multi-clause.
                for line in str(reason).split(". "):
                    line = line.strip().rstrip(".")
                    if line:
                        print(f"      • {line}")
                print()
            elif status == "escalated":
                print(f"    {C.BOLD}why{C.RESET}")
                print(f"      • {reason or 'Human approval required.'}")
                print(f"      • review at {C.CYAN}{base_url}/dashboard/{C.RESET}")
                print()

            # ── Engine signals (the reason_codes vocabulary — same shape across
            #    decisions, so viewers can see signals fired even on approve).
            if reason_codes:
                hint = ""
                if status in ("approved", "executed"):
                    hint = f"  {C.DIM}(signals weighed, did not deny){C.RESET}"
                print(f"    {C.BOLD}reason_codes{C.RESET}    {_fmt_codes(reason_codes)}{hint}")

            # ── Policy fingerprint — proves which exact policy version governed
            #    this decision (cited in the signed receipt, anyone can verify).
            if policy_name:
                ver_suffix = f" v{policy_version}" if policy_version else ""
                print(f"    {C.BOLD}policy{C.RESET}          {policy_name}{ver_suffix}  {C.DIM}({_fmt_hash(policy_hash)}){C.RESET}")

            if tx_id:
                print(f"    {C.BOLD}transaction{C.RESET}     {C.DIM}{tx_id}{C.RESET}")

            # ── Receipt summary — the cryptographic part. Shown so viewers
            #    see Veto isn't just logging — every decision is signed.
            if receipt:
                print()
                print(f"    {C.DIM}┌ Decision receipt — Ed25519, JWKS-verifiable{C.RESET}")
                if decision_layer:
                    print(f"    {C.DIM}│{C.RESET} decision_layer: {decision_layer}")
                if input_fp:
                    print(f"    {C.DIM}│{C.RESET} input_fingerprint: {C.DIM}{_fmt_hash(input_fp, 24)}{C.RESET}")
                print(f"    {C.DIM}└ verify offline:{C.RESET} {C.CYAN}veto authorize ... --json | jq -r .receipt | veto verify -{C.RESET}")

            print()

    # Exit codes
    if status in ("approved", "executed"):
        sys.exit(0)
    if status == "denied":
        sys.exit(1)
    if status == "escalated":
        sys.exit(2)
    sys.exit(3)


# ── Verify command — offline JWS receipt validation via JWKS ──

def cmd_verify(args):
    """
    `veto verify <receipt>` — fetch JWKS, validate Ed25519 signature, print payload.

    Receipt can be passed as a positional arg or via stdin (use '-').

    Exit codes:
        0 = valid signature, payload printed
        1 = invalid signature (key found but didn't verify)
        2 = malformed receipt OR JWKS fetch failed
        3 = input error (bad stdin, etc.)
    """
    from veto_cli import receipts as rcpt

    state = _load_state()
    base_url = args.base_url or state.get("base_url", "https://veto-ai.com")

    raw = args.receipt
    if raw == "-":
        raw = sys.stdin.read().strip()
    if not raw:
        if args.json:
            print(json.dumps({"valid": False, "error": "missing receipt input"}))
        else:
            _eerr("Receipt input is empty.")
        sys.exit(3)

    try:
        payload = rcpt.verify_receipt(raw, base_url, no_cache=args.no_cache)
    except rcpt.MalformedReceipt as e:
        if args.json:
            print(json.dumps({"valid": False, "error": f"malformed: {e}"}))
        elif not args.quiet:
            _eerr(f"Malformed receipt: {e}")
        sys.exit(2)
    except rcpt.KeyFetchError as e:
        if args.json:
            print(json.dumps({"valid": False, "error": f"jwks: {e}"}))
        elif not args.quiet:
            _eerr(f"JWKS fetch failed: {e}")
            _einfo(f"Tried: {base_url}/.well-known/jwks.json")
        sys.exit(2)
    except rcpt.InvalidReceipt as e:
        # Try to surface the (untrusted) payload claims so the user sees what was
        # being claimed by the bad receipt — useful for debugging.
        try:
            _, untrusted_payload, _, _ = rcpt.parse_receipt_unsafe(raw)
        except Exception:
            untrusted_payload = {}
        if args.json:
            print(json.dumps({
                "valid": False,
                "error": str(e),
                "untrusted_payload": untrusted_payload,
            }))
        elif not args.quiet:
            _eerr(f"{C.BOLD}INVALID RECEIPT{C.RESET} — {e}")
        sys.exit(1)

    # Valid — render the verified payload
    if args.json:
        print(json.dumps({"valid": True, "payload": payload}))
    elif not args.quiet:
        decision = payload.get("decision", "?")
        decision_color = {
            "approve": C.GREEN,
            "deny": C.RED,
            "escalate": C.YELLOW,
        }.get(decision, C.DIM)
        print()
        ok(f"{C.BOLD}{C.GREEN}VERIFIED{C.RESET} {C.DIM}— Ed25519 / {payload.get('engine_version', '?')}{C.RESET}")
        print()
        print(f"  {C.DIM}decision:{C.RESET}        {decision_color}{C.BOLD}{decision.upper()}{C.RESET}")
        # decision_layer disambiguates Veto's operator_policy receipts from
        # user-authorization credentials (AP2 / Verifiable Intent) when both
        # are present on a transaction. Surface it so downstream verifiers
        # know which layer this attestation belongs to.
        if payload.get("decision_layer"):
            print(f"  {C.DIM}decision_layer:{C.RESET}  {payload['decision_layer']}")
        if payload.get("mandate_ref"):
            print(f"  {C.DIM}mandate_ref:{C.RESET}     {payload['mandate_ref']}")
        print(f"  {C.DIM}risk_score:{C.RESET}      {payload.get('risk_score', '?')}")
        if payload.get("reason_codes"):
            print(f"  {C.DIM}reason_codes:{C.RESET}    {', '.join(payload['reason_codes'])}")
        if payload.get("policy"):
            p = payload["policy"]
            print(f"  {C.DIM}policy:{C.RESET}          {p.get('name', '')} v{p.get('version_number', '?')}")
            print(f"  {C.DIM}policy_id:{C.RESET}       {C.DIM}{p.get('id', '')}{C.RESET}")
            if p.get("hash"):
                print(f"  {C.DIM}policy_hash:{C.RESET}     {C.DIM}{p['hash'][:32]}…{C.RESET}")
        print(f"  {C.DIM}transaction_id:{C.RESET}  {C.DIM}{payload.get('sub', '')}{C.RESET}")
        print(f"  {C.DIM}agent_id:{C.RESET}        {C.DIM}{payload.get('agent_id', '')}{C.RESET}")
        print(f"  {C.DIM}fingerprint:{C.RESET}     {C.DIM}{payload.get('input_fingerprint', '')[:32]}…{C.RESET}")
        if payload.get("iat"):
            from datetime import datetime, timezone
            iat = datetime.fromtimestamp(payload["iat"], tz=timezone.utc)
            print(f"  {C.DIM}signed_at:{C.RESET}       {iat.isoformat()}")
        print()
    sys.exit(0)


# ── Policy commands ──

def _require_yaml():
    """Import PyYAML lazily so tests / unrelated commands don't hard-fail without it."""
    try:
        import yaml  # type: ignore
        return yaml
    except ImportError:
        _eerr("PyYAML is required for `veto policy` commands. Install with: pip install pyyaml")
        sys.exit(3)


def _strip_meta(d: dict) -> dict:
    """Drop the read-only _meta block before sending a policy back to the server."""
    return {k: v for k, v in d.items() if k != "_meta"}


def _print_yaml(data: dict):
    """Emit YAML to stdout. Block style, sorted keys preserved as inserted."""
    yaml = _require_yaml()
    sys.stdout.write(
        yaml.dump(data, default_flow_style=False, sort_keys=False, allow_unicode=True)
    )


def cmd_policy_export(args):
    """`veto policy export <preset>` — fetch a preset and print as YAML."""
    base_url = args.base_url or _load_state().get("base_url", "https://veto-ai.com")
    try:
        data = api.policy_export_preset(base_url, args.preset)
    except api.VetoAPIError as e:
        _eerr(f"Could not fetch preset: {e}")
        if e.status_code == 404:
            _einfo("Run `veto policy export --list` to see available presets.")
        sys.exit(3)
    _print_yaml(data)


def cmd_policy_push(args):
    """`veto policy push <file>` — read YAML, send to backend, print version info."""
    state = _load_state()
    api_key = args.api_key or state.get("api_key")
    base_url = args.base_url or state.get("base_url", "https://veto-ai.com")
    if not api_key:
        _eerr("No API key. Run `veto register` or `veto init` first.")
        sys.exit(3)

    if not os.path.isfile(args.file):
        _eerr(f"File not found: {args.file}")
        sys.exit(3)

    yaml = _require_yaml()
    try:
        with open(args.file) as f:
            payload = yaml.safe_load(f)
    except yaml.YAMLError as e:
        _eerr(f"YAML parse error in {args.file}: {e}")
        sys.exit(3)

    if not isinstance(payload, dict):
        _eerr(f"Policy file must contain a YAML object (got {type(payload).__name__}).")
        sys.exit(3)

    payload = _strip_meta(payload)

    try:
        r = api.policy_push(base_url, api_key, payload)
    except api.VetoAPIError as e:
        _eerr(f"Push failed: {e}")
        if e.body and e.body.get("field"):
            _einfo(f"field: {e.body['field']}")
        sys.exit(3)

    print()
    ok(f"{C.BOLD}Policy v{r['version_number']} pushed{C.RESET} {C.DIM}— now active{C.RESET}")
    info(f"name:       {r['name']}")
    info(f"scope:      {r['scope']}")
    if r.get("agent_id"):
        info(f"agent_id:   {r['agent_id']}")
    info(f"policy_id:  {C.DIM}{r['policy_id']}{C.RESET}")
    print()
    info(f"Roll back with:  {C.CYAN}veto policy activate <prior-policy_id>{C.RESET}")
    print()


def cmd_policy_show(args):
    """`veto policy show` — fetch the active policy and print as YAML."""
    state = _load_state()
    api_key = args.api_key or state.get("api_key")
    base_url = args.base_url or state.get("base_url", "https://veto-ai.com")
    if not api_key:
        _eerr("No API key. Run `veto register` or `veto init` first.")
        sys.exit(3)

    try:
        data = api.policy_show_active(base_url, api_key)
    except api.VetoAPIError as e:
        _eerr(f"Could not fetch active policy: {e}")
        sys.exit(3)

    _print_yaml(data)


def cmd_policy_list(args):
    """`veto policy list` — show all versions for this client, newest first."""
    state = _load_state()
    api_key = args.api_key or state.get("api_key")
    base_url = args.base_url or state.get("base_url", "https://veto-ai.com")
    if not api_key:
        _eerr("No API key. Run `veto register` or `veto init` first.")
        sys.exit(3)

    try:
        r = api.policy_list(base_url, api_key)
    except api.VetoAPIError as e:
        _eerr(f"List failed: {e}")
        sys.exit(3)

    policies = r.get("policies", [])
    if not policies:
        info("No policies yet. Push one with `veto policy push <file>`.")
        return

    # Pad name column to the longest name in the result so columns stay aligned
    # even when names differ in length.
    name_width = max((len(p.get("name", "")) for p in policies), default=20)
    name_width = max(name_width, 20)  # don't shrink below 20 — looks weird

    print()
    print(f"  {C.BOLD}Policy versions:{C.RESET}")
    print()
    for p in policies:
        marker = f"{C.GREEN}●{C.RESET}" if p["is_active"] else f"{C.DIM}·{C.RESET}"
        active_label = (
            f"{C.GREEN}active  {C.RESET}" if p["is_active"]
            else f"{C.DIM}inactive{C.RESET}"
        )
        # Relative timestamp ("5 min ago", "2 days ago") — chronology legible
        # even when active row isn't first (after a rollback).
        rel = _relative_time(p.get("created_at"))
        name = p.get("name", "")
        print(
            f"  {marker} v{p['version_number']:<3}  "
            f"{name:<{name_width}}  "
            f"{active_label}  "
            f"{C.DIM}{rel:>14}  {p['policy_id']}{C.RESET}"
        )
    print()


def _relative_time(iso_ts: str | None) -> str:
    """'2026-04-29T10:09:57Z' → '23 min ago' (or '' if unparseable)."""
    if not iso_ts:
        return ""
    try:
        from datetime import datetime, timezone
        # Accept '...Z' or '...+00:00'
        s = iso_ts.replace("Z", "+00:00")
        ts = datetime.fromisoformat(s)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        delta = datetime.now(timezone.utc) - ts
        secs = int(delta.total_seconds())
        if secs < 60:
            return f"{secs} sec ago"
        if secs < 3600:
            return f"{secs // 60} min ago"
        if secs < 86400:
            return f"{secs // 3600} hr ago"
        return f"{secs // 86400} day{'s' if secs // 86400 != 1 else ''} ago"
    except Exception:
        return ""


def cmd_policy_check(args):
    """`veto policy check '<json>'` — dry-run an action against the active policy."""
    state = _load_state()
    api_key = args.api_key or state.get("api_key")
    base_url = args.base_url or state.get("base_url", "https://veto-ai.com")
    if not api_key:
        _eerr("No API key. Run `veto register` or `veto init` first.")
        sys.exit(3)

    # action JSON via positional arg or stdin
    raw = args.action_json
    if raw == "-":
        raw = sys.stdin.read()
    try:
        payload = json.loads(raw) if raw else {}
    except json.JSONDecodeError as e:
        _eerr(f"Invalid JSON: {e}")
        sys.exit(3)

    agent_id = payload.get("agent_id") or payload.get("agent") or state.get("default_agent")
    action = payload.get("action") or "payment"
    if not agent_id:
        _eerr("agent_id required (set --agent or include 'agent_id' in JSON, or run `veto register` first).")
        sys.exit(3)

    extra = {k: v for k, v in payload.items() if k not in {
        "agent_id", "agent", "amount", "merchant", "action", "description", "context"
    }}

    try:
        r = api.policy_check(
            base_url, api_key, agent_id,
            action=action,
            amount=payload.get("amount"),
            merchant=payload.get("merchant", ""),
            description=payload.get("description", ""),
            context=payload.get("context", ""),
            extra=extra,
        )
    except api.VetoAPIError as e:
        _eerr(f"Check failed: {e}")
        sys.exit(3)

    if args.json:
        print(json.dumps(r))
        return

    decision = r.get("decision", "?")
    risk = r.get("risk_score", 0) or 0
    reason = r.get("denial_reason", "")
    pol = r.get("policy") or {}

    print()
    if decision == "approve":
        ok(f"{C.BOLD}{C.GREEN}WOULD APPROVE{C.RESET} {C.DIM}— risk {risk:.2f}, dry-run{C.RESET}")
    elif decision == "deny":
        err(f"{C.BOLD}WOULD DENY{C.RESET} {C.DIM}— risk {risk:.2f}, dry-run{C.RESET}")
        if reason:
            info(f"reason: {reason}")
    elif decision == "escalate":
        warn(f"{C.BOLD}WOULD ESCALATE{C.RESET} {C.DIM}— risk {risk:.2f}, dry-run{C.RESET}")
        if reason:
            info(reason)
    else:
        info(f"decision: {decision}")

    # Surface canonical reason_codes when the server provided them. Same shape
    # as `veto authorize --json` so dry-run and real-decision outputs match.
    reason_codes = r.get("reason_codes") or []
    if reason_codes:
        info(f"reason_codes: {C.BOLD}{', '.join(reason_codes)}{C.RESET}")

    if pol:
        info(f"policy:  {pol.get('name', '')} v{pol.get('version_number', '?')}")
    signals = [s for s in r.get("signals", []) if s.get("score", 0) > 0]
    if signals and args.verbose:
        print()
        print(f"  {C.DIM}signals:{C.RESET}")
        for s in signals[:10]:
            print(f"    {C.DIM}· {s['name']:25s} {s['score']:.2f}  {s.get('reason', '')[:80]}{C.RESET}")
    print()


def cmd_policy_activate(args):
    """`veto policy activate <policy_id>` — roll back to / activate a specific version."""
    state = _load_state()
    api_key = args.api_key or state.get("api_key")
    base_url = args.base_url or state.get("base_url", "https://veto-ai.com")
    if not api_key:
        _eerr("No API key. Run `veto register` or `veto init` first.")
        sys.exit(3)

    try:
        r = api.policy_activate(base_url, api_key, args.policy_id)
    except api.VetoAPIError as e:
        _eerr(f"Activate failed: {e}")
        sys.exit(3)

    print()
    ok(f"{C.BOLD}Activated v{r['version_number']}{C.RESET} {C.DIM}— {r['name']}{C.RESET}")
    info(f"policy_id: {C.DIM}{r['policy_id']}{C.RESET}")
    print()


# ── Agent scaffolding command (`veto agent init`) ──
#
# Generates a runnable agent project on the user's disk. The agent is
# pre-wired with Veto policy enforcement: every payment call passes
# through `veto.authorize()` before settling.
#
# Architectural commitments (see ARCHITECTURE.md in the repo root):
#   - Agent runs on user's machine. Veto NEVER hosts it.
#   - Wallet is provisioned via Coinbase CDP. Veto orchestrates the API
#     call but never holds keys.
#   - For v0.6 hard-stop, the wallet is an ERC-4337 smart account that
#     refuses to settle without a Veto-signed mandate JWT.

_AGENT_TYPES = {
    "local": "Local viem wallet — you own the private key. No third-party wallet vendor. Default.",
    "cdp":   "Coinbase CDP AgentKit + CDP smart-account wallet. Heavier setup; multi-chain via CDP.",
}
_DEFAULT_AGENT_TYPE = "local"


# ── Interactive onboarding for `veto agent init` / `veto agent configure` ──
#
# We collect the keys the scaffolded agent needs to run end-to-end:
#   - Veto API key + agent ID (reused from ~/.veto/config.json if registered,
#                               otherwise the user gets pointed at `veto register`)
#   - Anthropic API key (the agent's brain)
#   - Coinbase CDP keys (optional — settler is stubbed in v0.6, so the agent
#                        runs without them; needed for real on-chain settlement)

def _hidden_prompt(question: str) -> str:
    """Like _prompt but doesn't echo the input — for API keys, secrets."""
    import getpass
    try:
        return getpass.getpass(question)
    except (EOFError, KeyboardInterrupt):
        print()
        return ""


def _generate_private_key() -> str:
    """Generate a fresh secp256k1 private key for a viem wallet.

    Returns a 0x-prefixed 32-byte hex string. The user owns this key — Veto
    never sees it. Stored in the scaffolded project's .env.
    """
    import secrets as _secrets_lib
    return "0x" + _secrets_lib.token_hex(32)


def _address_from_private_key(pk_hex: str) -> str:
    """Derive the Ethereum-style 0x... address for a private key.

    Uses eth_keys if available; falls back to a placeholder if not. We don't
    add eth_keys as a CLI dependency (keeps install lean), so the placeholder
    is fine — the scaffolded TS code will derive + log the real address on
    first run anyway.
    """
    try:
        from eth_keys import keys  # optional, often present transitively
        pk_bytes = bytes.fromhex(pk_hex.removeprefix("0x"))
        return keys.PrivateKey(pk_bytes).public_key.to_checksum_address()
    except Exception:
        return "(derived at first run — see your agent's first log line)"


def _collect_agent_secrets(prompt: bool, agent_type: str = "local") -> dict:
    """Collect the secrets the scaffolded agent needs.

    Returns a dict of substitutions for `.env` (and other places). Missing
    values come back as empty strings — the user can fill them in later by
    editing `.env` directly or re-running `veto agent configure`.
    """
    secrets = {
        "VETO_API_KEY": "",
        "VETO_AGENT_ID": "",
        "VETO_BASE_URL": "https://veto-ai.com",
        "LLM_PROVIDER": "anthropic",  # default; overridden by user choice below
        "ANTHROPIC_API_KEY": "",
        "OPENAI_API_KEY": "",
        "XAI_API_KEY": "",
        # Local-wallet (viem) secrets
        "WALLET_PRIVATE_KEY": "",
        "RPC_URL": "https://mainnet.base.org",
        "NETWORK": "base-mainnet",
        "CHAIN_ID": "8453",
        # CDP secrets (only used when --type cdp)
        "CDP_API_KEY_ID": "",
        "CDP_API_KEY_SECRET": "",
        "CDP_WALLET_SECRET": "",
        "CDP_WALLET_ADDRESS": "",
        "CDP_WALLET_ID": "",
    }

    # ── Veto: reuse existing local config if present ─────────────────
    state = _load_state()
    if state.get("api_key"):
        secrets["VETO_API_KEY"] = state["api_key"]
    if state.get("agent_id"):
        secrets["VETO_AGENT_ID"] = state["agent_id"]
    if state.get("base_url"):
        secrets["VETO_BASE_URL"] = state["base_url"]

    if not prompt:
        # Even in --no-prompt mode, auto-generate a local wallet so the
        # scaffold is runnable as soon as the user fills in the LLM/Veto keys.
        # CDP needs vendor-issued keys so we can't auto-fill those.
        if agent_type == "local" and not secrets["WALLET_PRIVATE_KEY"]:
            secrets["WALLET_PRIVATE_KEY"] = _generate_private_key()
        return secrets

    print()
    print(f"  {C.BOLD}Set up your agent{C.RESET} {C.DIM}— takes about a minute{C.RESET}")
    print(f"  {C.DIM}Press Enter at any prompt to skip; you can fill it into .env later.{C.RESET}")
    print()

    # ── Step 1: Veto ─────────────────────────────────────────────────
    print(f"  {C.BOLD}1. Veto API key{C.RESET}")
    if secrets["VETO_API_KEY"]:
        masked = secrets["VETO_API_KEY"][:8] + "…" + secrets["VETO_API_KEY"][-4:] if len(secrets["VETO_API_KEY"]) > 16 else "***"
        print(f"     {C.GREEN}✓{C.RESET} reusing your existing key from {C.DIM}{STATE_PATH}{C.RESET}")
        print(f"     {C.DIM}key:      {masked}{C.RESET}")
        print(f"     {C.DIM}agent_id: {secrets['VETO_AGENT_ID'] or '(none — run `veto register`)'}{C.RESET}")
    else:
        print(f"     {C.DIM}You don't have a Veto key yet.{C.RESET}")
        print(f"     {C.DIM}Run `veto register --preset inference --email you@example.com` first,{C.RESET}")
        print(f"     {C.DIM}then re-run this command (or edit .env after scaffolding).{C.RESET}")
        skip = _prompt("Continue without a Veto key? [y/N]:", default="N").strip().lower()
        if skip != "y":
            print(f"     {C.DIM}Skipping for now. Run `veto register` then `veto agent configure` to fill in.{C.RESET}")
    print()

    # ── Step 2: LLM brain — pick a provider ─────────────────────────
    print(f"  {C.BOLD}2. LLM brain — pick a provider{C.RESET}")
    print(f"     {C.CYAN}1){C.RESET} Anthropic Claude  {C.DIM}(default — works best with the included tool definitions){C.RESET}")
    print(f"     {C.CYAN}2){C.RESET} OpenAI GPT")
    print(f"     {C.CYAN}3){C.RESET} xAI Grok")
    print(f"     {C.CYAN}4){C.RESET} Skip — fill in later")
    while True:
        choice = _prompt("     Choose [1-4]:", default="1").strip()
        if choice in ("1", "2", "3", "4"):
            break
        warn("Pick 1, 2, 3, or 4.")

    if choice == "1":
        secrets["LLM_PROVIDER"] = "anthropic"
        print(f"     {C.DIM}Get a key at https://console.anthropic.com/settings/keys{C.RESET}")
        key = _hidden_prompt("     Paste sk-ant-... (or Enter to skip): ").strip()
        if key:
            if not key.startswith("sk-ant-"):
                warn("That doesn't look like an Anthropic key (expected sk-ant-…). Saving anyway.")
            secrets["ANTHROPIC_API_KEY"] = key
            print(f"     {C.GREEN}✓{C.RESET} Anthropic Claude configured")
        else:
            print(f"     {C.DIM}skipped — paste your Anthropic key into .env later{C.RESET}")
    elif choice == "2":
        secrets["LLM_PROVIDER"] = "openai"
        print(f"     {C.DIM}Get a key at https://platform.openai.com/api-keys{C.RESET}")
        key = _hidden_prompt("     Paste sk-... (or Enter to skip): ").strip()
        if key:
            if not key.startswith("sk-"):
                warn("That doesn't look like an OpenAI key (expected sk-…). Saving anyway.")
            secrets["OPENAI_API_KEY"] = key
            print(f"     {C.GREEN}✓{C.RESET} OpenAI GPT configured")
        else:
            print(f"     {C.DIM}skipped — paste your OpenAI key into .env later{C.RESET}")
    elif choice == "3":
        secrets["LLM_PROVIDER"] = "grok"
        print(f"     {C.DIM}Get a key at https://console.x.ai/{C.RESET}")
        key = _hidden_prompt("     Paste xai-... (or Enter to skip): ").strip()
        if key:
            if not key.startswith("xai-"):
                warn("That doesn't look like a Grok key (expected xai-…). Saving anyway.")
            secrets["XAI_API_KEY"] = key
            print(f"     {C.GREEN}✓{C.RESET} xAI Grok configured")
        else:
            print(f"     {C.DIM}skipped — paste your Grok key into .env later{C.RESET}")
    else:  # 4
        # Default provider stays as anthropic so the env file has a sensible
        # default; user picks one and pastes the key into .env later.
        print(f"     {C.DIM}skipped — pick a provider + paste a key into .env later{C.RESET}")
    print()

    # ── Step 3: Network ─────────────────────────────────────────────
    print(f"  {C.BOLD}3. Network{C.RESET}")
    print(f"     {C.CYAN}1){C.RESET} base-sepolia  {C.DIM}(testnet, free, recommended for first try){C.RESET}")
    print(f"     {C.CYAN}2){C.RESET} base-mainnet  {C.DIM}(real money — hard-stop disabled until v2 audit){C.RESET}")
    while True:
        net_choice = _prompt("     Choose [1-2]:", default="1").strip()
        if net_choice in ("1", "2"):
            break
        warn("Pick 1 or 2.")
    if net_choice == "1":
        secrets["NETWORK"] = "base-sepolia"
        secrets["CHAIN_ID"] = "84532"
        secrets["RPC_URL"] = "https://sepolia.base.org"
    else:
        secrets["NETWORK"] = "base-mainnet"
        secrets["CHAIN_ID"] = "8453"
        secrets["RPC_URL"] = "https://mainnet.base.org"
    print(f"     {C.GREEN}✓{C.RESET} {secrets['NETWORK']} (chain {secrets['CHAIN_ID']})")
    print()

    # ── Step 4: Wallet (branches on agent_type) ─────────────────────
    if agent_type == "local":
        # Local viem wallet — generate a private key automatically. User owns
        # it. No third-party vendor. Zero signup friction.
        print(f"  {C.BOLD}4. Wallet{C.RESET} {C.DIM}— local viem wallet, you own the key{C.RESET}")
        if not secrets["WALLET_PRIVATE_KEY"]:
            secrets["WALLET_PRIVATE_KEY"] = _generate_private_key()
            addr = _address_from_private_key(secrets["WALLET_PRIVATE_KEY"])
            print(f"     {C.GREEN}✓{C.RESET} Generated a fresh wallet:")
            print(f"     {C.DIM}address:{C.RESET}     {C.BOLD}{addr}{C.RESET}")
            print(f"     {C.DIM}private_key:{C.RESET} {C.DIM}saved to .env (treat that file like a password){C.RESET}")
        else:
            print(f"     {C.GREEN}✓{C.RESET} {C.DIM}existing WALLET_PRIVATE_KEY in env — reusing{C.RESET}")
    elif agent_type == "cdp":
        # Coinbase CDP — opt-in for users who want CDP's managed AA stack.
        print(f"  {C.BOLD}4. Coinbase CDP keys{C.RESET} {C.DIM}— managed wallet via CDP{C.RESET}")
        print(f"     {C.DIM}Get them at https://portal.cdp.coinbase.com → your project → API keys.{C.RESET}")
        print(f"     {C.DIM}You'll see {C.RESET}{C.BOLD}API Key ID{C.RESET}{C.DIM} (a UUID) and {C.RESET}{C.BOLD}API Key Secret{C.RESET}{C.DIM} (a long string).{C.RESET}")
        cdp_id = _prompt("     CDP API Key ID (UUID, e.g. 1d6bfd3c-… — or Enter to skip):", default="").strip()
        if cdp_id:
            secrets["CDP_API_KEY_ID"] = cdp_id
            cdp_secret = _hidden_prompt("     CDP API Key Secret (paste, hidden): ").strip()
            if cdp_secret:
                secrets["CDP_API_KEY_SECRET"] = cdp_secret
                print(f"     {C.DIM}The Wallet Secret authorizes signing transactions. Required{C.RESET}")
                print(f"     {C.DIM}for the agent to actually send. Without it, agent is read-only.{C.RESET}")
                cdp_wallet_secret = _hidden_prompt("     CDP Wallet Secret (Enter to skip — agent read-only): ").strip()
                if cdp_wallet_secret:
                    secrets["CDP_WALLET_SECRET"] = cdp_wallet_secret
                    print(f"     {C.GREEN}✓{C.RESET} CDP fully configured — agent can read AND send")
                else:
                    warn("Wallet Secret skipped — agent will be read-only.")
            else:
                warn("API Key Secret was empty — only the ID was saved.")
        else:
            print(f"     {C.DIM}skipped — fill into .env later with `veto agent configure`{C.RESET}")
    print()

    return secrets


def _write_env_file(target_dir: Path, secrets: dict, mode: str = "chat") -> Path:
    """Write a .env file with the collected secrets pre-filled.

    If a .env already exists, merge: keep its values for keys not in `secrets`,
    overwrite for keys we have non-empty values for. Preserves comments + order
    using a simple line-by-line rewrite of the .env.example template.
    """
    example = target_dir / ".env.example"
    target = target_dir / ".env"

    if not example.exists():
        # Fall back to a minimal env if the template didn't ship one.
        target.write_text(
            "\n".join(f"{k}={v}" for k, v in secrets.items()) + f"\nMODE={mode}\n",
            encoding="utf-8",
        )
        return target

    template_lines = example.read_text(encoding="utf-8").splitlines()
    out_lines: list[str] = []
    seen = set()
    for line in template_lines:
        if "=" not in line or line.lstrip().startswith("#"):
            out_lines.append(line)
            continue
        key, _, _existing = line.partition("=")
        key = key.strip()
        if key in secrets and secrets[key]:
            out_lines.append(f"{key}={secrets[key]}")
            seen.add(key)
        elif key == "MODE":
            out_lines.append(f"MODE={mode}")
            seen.add(key)
        else:
            out_lines.append(line)  # keep placeholder
            seen.add(key)

    # Append any secrets that weren't in the template
    extras = {k: v for k, v in secrets.items() if k not in seen and v}
    if extras:
        out_lines.append("")
        out_lines.append("# ── Added by `veto agent init` ──")
        for k, v in extras.items():
            out_lines.append(f"{k}={v}")

    target.write_text("\n".join(out_lines) + "\n", encoding="utf-8")
    return target


def _template_dir(agent_type: str) -> Path:
    """Return the path to the template directory for `agent_type`.

    Works both when veto-cli is installed via pip (templates packaged inside
    the wheel) and when running from a source checkout (templates next to
    the cli/ source). Falls back to a path relative to this file.
    """
    # Try importlib.resources first — preferred for installed packages.
    try:
        from importlib.resources import files
        try:
            res = files("veto_cli").joinpath("templates", agent_type)
            if res.is_dir():
                return Path(str(res))
        except Exception:
            pass
    except ImportError:
        pass

    # Source-checkout fallback: ../templates/{type} relative to this file.
    src_path = Path(__file__).resolve().parent.parent / "templates" / agent_type
    if src_path.is_dir():
        return src_path

    raise FileNotFoundError(
        f"Template not found for agent type '{agent_type}'. "
        "If you installed via pip, please reinstall the latest veto-cli."
    )


def _scaffold_project(template_dir: Path, target_dir: Path, vars: dict) -> list[Path]:
    """Copy `template_dir` to `target_dir` with `{{VAR}}` substitution.

    Returns the list of files written. Substitution is naive (string replace)
    on a small allow-list of file extensions to avoid corrupting binaries.
    """
    SUBSTITUTABLE_EXTS = {".json", ".md", ".ts", ".tsx", ".js", ".env", ".example", ".yaml", ".yml", ".toml", ".gitignore", ""}

    target_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    for src in template_dir.rglob("*"):
        if not src.is_file():
            continue
        rel = src.relative_to(template_dir)
        dst = target_dir / rel
        dst.parent.mkdir(parents=True, exist_ok=True)

        ext = src.suffix.lower()
        if ext in SUBSTITUTABLE_EXTS or src.name in {".gitignore", ".env.example"}:
            text = src.read_text(encoding="utf-8")
            for k, v in vars.items():
                text = text.replace("{{" + k + "}}", v)
            dst.write_text(text, encoding="utf-8")
        else:
            dst.write_bytes(src.read_bytes())
        written.append(dst)

    return written


def _slug(name: str) -> str:
    """Lower-case + dashes; safe for npm package names."""
    out = "".join(c if c.isalnum() else "-" for c in name.lower())
    while "--" in out:
        out = out.replace("--", "-")
    return out.strip("-") or "veto-agent"


def cmd_agent_init(args):
    """Scaffold a runnable Veto-governed agent project on disk, with
    an interactive onboarding flow that pre-fills the .env.

    Steps:
      1. Copy template files (with `{{AGENT_NAME}}` substitution)
      2. Interactive prompts for Veto / Anthropic / CDP keys (skip with --no-prompt)
      3. Write a pre-filled .env so the user can `npm install && npm run dev`
         without manually editing anything else

    Wallet auto-provisioning + smart-account hard-stop land later in v0.6.
    """
    agent_type = args.type
    target_dir = Path(args.dir or "./veto-agent").resolve()
    agent_name = args.name or "veto-agent"
    safe_name = _slug(agent_name)
    interactive = not args.no_prompt

    print()
    print(f"  {C.BOLD}{C.CYAN}veto agent init{C.RESET}")
    print(f"  {C.DIM}{'─' * 56}{C.RESET}")
    print(f"  {C.DIM}type:{C.RESET}    {agent_type}  {C.DIM}({_AGENT_TYPES[agent_type]}){C.RESET}")
    print(f"  {C.DIM}dir:{C.RESET}     {target_dir}")
    print(f"  {C.DIM}name:{C.RESET}    {safe_name}")
    print()

    # Refuse to overwrite a populated directory unless explicitly empty.
    if target_dir.exists() and any(target_dir.iterdir()):
        err(f"Target directory already exists and is non-empty: {target_dir}")
        info("Pick a different --dir, or remove the existing directory first.")
        sys.exit(1)

    try:
        template = _template_dir(agent_type)
    except FileNotFoundError as e:
        err(str(e))
        sys.exit(1)

    info(f"Copying template from {C.DIM}{template}{C.RESET}")
    written = _scaffold_project(
        template_dir=template,
        target_dir=target_dir,
        vars={"AGENT_NAME": safe_name},
    )
    ok(f"Scaffolded {len(written)} files in {C.BOLD}{target_dir}{C.RESET}")

    # ── Onboarding: collect secrets + write .env ──
    secrets = _collect_agent_secrets(prompt=interactive, agent_type=agent_type)
    env_file = _write_env_file(target_dir, secrets, mode="chat")
    ok(f"Wrote {env_file.name} with {sum(1 for v in secrets.values() if v)} secrets pre-filled")

    # ── Run instructions ──
    # Required varies per type: local needs a private key; cdp needs CDP creds.
    base_required = ["VETO_API_KEY", "VETO_AGENT_ID"]
    if secrets.get("LLM_PROVIDER") == "anthropic":
        base_required.append("ANTHROPIC_API_KEY")
    elif secrets.get("LLM_PROVIDER") == "openai":
        base_required.append("OPENAI_API_KEY")
    elif secrets.get("LLM_PROVIDER") == "grok":
        base_required.append("XAI_API_KEY")
    if agent_type == "local":
        base_required.append("WALLET_PRIVATE_KEY")
    elif agent_type == "cdp":
        base_required += ["CDP_API_KEY_ID", "CDP_API_KEY_SECRET", "CDP_WALLET_SECRET"]
    missing = [k for k in base_required if not secrets.get(k)]
    print()
    print(f"  {C.BOLD}Next:{C.RESET}")
    print()
    print(f"    {C.CYAN}cd {target_dir} && npm install && npm run dev{C.RESET}")
    print()
    if missing:
        warn(f"Required secrets still empty in .env: {', '.join(missing)}")
        info("Fill them in (or re-run `veto agent configure` from inside the project) before `npm run dev`.")
    else:
        info("Everything required is in .env — you're ready to chat with your agent.")
    print()

    # ── Optional chain: hard-stop setup (fund + deploy) ──────────────
    # On testnet, hard-stop is the recommended default. On mainnet, the
    # contract is unaudited so we don't push it during init.
    if (
        interactive
        and agent_type == "local"
        and secrets.get("NETWORK") == "base-sepolia"
        and secrets.get("WALLET_PRIVATE_KEY")
    ):
        print(f"  {C.BOLD}Hard-stop (recommended on testnet){C.RESET}")
        print(f"  {C.DIM}A smart wallet that holds funds + refuses unauthorized spends at the chain level.{C.RESET}")
        print(f"  {C.DIM}You'll go through one faucet (browser auto-opens) and we'll deploy the contract.{C.RESET}")
        do_hard_stop = _prompt("     Set up now? [Y/n]:", default="Y").strip().lower()
        if do_hard_stop in ("y", "yes", ""):
            from . import agent_commands as _agent_cmds
            try:
                # Build a minimal args namespace each subcommand expects.
                ns_fund = argparse.Namespace(dir=str(target_dir), min_eth=0.005)
                _agent_cmds.cmd_agent_fund(ns_fund)
                ns_deploy = argparse.Namespace(
                    dir=str(target_dir), fund_eth=0.001, force=False,
                    i_understand_unaudited=False,
                )
                _agent_cmds.cmd_agent_deploy(ns_deploy)
            except SystemExit:
                # Each helper sys.exits on hard errors; surface a hint and stop.
                warn("Hard-stop setup didn't finish. Re-run `veto agent fund` then `veto agent deploy` later.")
        else:
            print(f"     {C.DIM}skipped — you can run `veto agent fund` and `veto agent deploy` later.{C.RESET}")
        print()


def cmd_agent_configure(args):
    """Re-run the onboarding prompts on an existing scaffolded project.

    Useful for:
      - Filling in keys you skipped during init
      - Rotating an Anthropic key without redoing everything
      - Adding CDP keys after you've gotten a CDP account set up
    """
    target_dir = Path(args.dir or ".").resolve()
    if not (target_dir / ".env.example").exists():
        err(f"Doesn't look like a scaffolded Veto agent project: {target_dir}")
        info("Run `veto agent configure` from inside a directory created by `veto agent init`,")
        info("or pass --dir <path> pointing to one.")
        sys.exit(1)

    # Detect agent type from existing .env.example (look for distinctive vars)
    example_text = (target_dir / ".env.example").read_text(encoding="utf-8")
    if "WALLET_PRIVATE_KEY" in example_text:
        detected_type = "local"
    elif "CDP_API_KEY_ID" in example_text:
        detected_type = "cdp"
    else:
        detected_type = "local"

    print()
    print(f"  {C.BOLD}{C.CYAN}veto agent configure{C.RESET}")
    print(f"  {C.DIM}{'─' * 56}{C.RESET}")
    print(f"  {C.DIM}dir:{C.RESET}   {target_dir}")
    print(f"  {C.DIM}type:{C.RESET}  {detected_type}  {C.DIM}(detected from .env.example){C.RESET}")
    print()

    secrets = _collect_agent_secrets(prompt=True, agent_type=detected_type)
    env_file = _write_env_file(target_dir, secrets, mode="chat")
    ok(f"Updated {env_file}")
    print()


# ── Entry point ──

def main():
    parser = argparse.ArgumentParser(
        prog="veto",
        description="Veto CLI — authorization for AI agents",
    )
    parser.add_argument("--api-key", help="Override saved API key")
    parser.add_argument("--base-url", help="Veto server URL (default: https://veto-ai.com)")

    sub = parser.add_subparsers(dest="command", required=True)

    # CLI-native signup — first command a new user runs.
    p_register = sub.add_parser(
        "register",
        help="Register a new Veto account from the CLI (no web required)",
        description=(
            "Register a new Veto account. Creates a User + Client + default Agent + Policy\n"
            "on the backend, saves your API key locally, and prints what you can try next.\n\n"
            f"Available presets: {', '.join(_ALLOWED_PRESETS)}\n"
            "  personal       — general-purpose, $500/tx, blocks gambling/mixers/adult\n"
            "  inference      — AI API calls, $5/tx, allowlists Anthropic/OpenAI/etc.\n"
            "  x402-micropay  — x402 testing, $1/tx, Base chain only, auto-approve <$0.10\n"
            "  ad-spend       — Meta/Google ad platforms, $1k/tx, escalate >$1k\n"
            "  dev            — dogfood/testing, loose limits, no merchant restrictions\n\n"
            "Example: veto register --email me@example.com --preset dev"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_register.add_argument("--email", required=True, help="Your email address (account identifier)")
    p_register.add_argument("--preset", help=f"Policy preset (default: personal). One of: {', '.join(_ALLOWED_PRESETS)}")
    p_register.add_argument("--mission", help="Custom mission for the default agent (overrides preset's default)")
    p_register.add_argument("--agent-name", help="Name for the default agent (default: 'default-agent')")
    p_register.add_argument("--org-name", help="Organization name (default: derived from email)")
    p_register.add_argument("--yes", "-y", action="store_true", help="Skip confirmation if existing config would be overwritten")
    p_register.set_defaults(func=cmd_register)

    # Headline command — what agents call before each real action.
    p_authorize = sub.add_parser(
        "authorize",
        help="Ask Veto whether an agent action is allowed (returns approve / deny / escalate)",
        description=(
            "Ask Veto whether an agent action is allowed. Returns approve/deny/escalate.\n\n"
            "MODE: This command is Mode-1 only. It always sends decision_only=true to\n"
            "the backend, so the engine evaluates and returns a signed receipt but does\n"
            "NOT execute any side effect (no Stripe card issued, no on-chain co-sign,\n"
            "no MCP forward). For Mode-2 (executor side effects) hit /api/v1/authorize/\n"
            "directly with decision_only:false.\n\n"
            "Two input modes:\n"
            "  Flags: veto authorize --agent <uuid> --amount 0.05 --merchant test --action payment\n"
            "  Stdin: echo '{\"agent_id\":\"...\",\"amount\":0.05,...}' | veto authorize -\n\n"
            f"Allowed --action values: {', '.join(_ALLOWED_ACTIONS)}\n\n"
            "Exit codes (deliberately distinct so shell scripts can branch on intent):\n"
            "  0  approved      — engine said yes, signed receipt issued\n"
            "  1  denied        — engine said no, signed receipt issued (deny is also evidence)\n"
            "  2  escalated     — needs human review, signed receipt issued\n"
            "  3  error         — input invalid / network failure / unparseable response\n\n"
            "Approved/denied/escalated are all *signed answers*. Code 3 is the only\n"
            "outcome where you should NOT trust a receipt-shaped field."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_authorize.add_argument("stdin", nargs="?", help="Pass '-' to read JSON object from stdin")
    p_authorize.add_argument("--agent", help="Agent UUID")
    p_authorize.add_argument("--amount", type=float, help="Amount (USD or token decimal)")
    p_authorize.add_argument("--merchant", help="Merchant or counterparty (e.g. 'api.anthropic.com')")
    p_authorize.add_argument(
        "--action",
        help=f"Action type. One of: {', '.join(_ALLOWED_ACTIONS)}",
    )
    p_authorize.add_argument("--description", help="Free-text description (optional)")
    p_authorize.add_argument(
        "--context",
        help="Conversation context — used by the engine for intent verification (optional)",
    )
    p_authorize.add_argument("--json", action="store_true", help="Output JSON to stdout instead of human-readable")
    p_authorize.add_argument("--quiet", "-q", action="store_true", help="Silent; exit code only")
    p_authorize.set_defaults(func=cmd_authorize)

    # Verify a Veto signed receipt — offline, via the issuer's JWKS endpoint.
    p_verify = sub.add_parser(
        "verify",
        help="Verify a Veto signed decision receipt (offline, via JWKS)",
        description=(
            "Verify a Veto signed decision receipt against the issuer's JWKS endpoint.\n\n"
            "Receipts are JWS-compact strings (Ed25519). The CLI fetches the public key from\n"
            "<base_url>/.well-known/jwks.json (cached for 1h), validates the signature, and\n"
            "prints the decoded payload.\n\n"
            "Examples:\n"
            "  veto verify <receipt-string>\n"
            "  echo '<receipt>' | veto verify -\n"
            "  veto verify <receipt> --json\n\n"
            "Exit codes:\n"
            "  0 = valid signature\n"
            "  1 = invalid signature\n"
            "  2 = malformed receipt or JWKS fetch failed\n"
            "  3 = input error"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_verify.add_argument("receipt", help="JWS-compact receipt string, or '-' to read from stdin")
    p_verify.add_argument("--json", action="store_true", help="Print {valid, payload} as JSON")
    p_verify.add_argument("--quiet", "-q", action="store_true", help="Silent; exit code only")
    p_verify.add_argument("--no-cache", action="store_true", help="Force a fresh JWKS fetch")
    p_verify.set_defaults(func=cmd_verify)

    # Policy authoring — YAML in, YAML out, versioned + revertible.
    p_policy = sub.add_parser(
        "policy",
        help="Author / inspect / dry-run security policies (YAML)",
        description=(
            "Author and manage security policies in YAML.\n\n"
            "Subcommands:\n"
            "  export <preset>          Print a preset as YAML (use as a starting template)\n"
            "  push <file>              Push a YAML file as a new policy version (auto-activates)\n"
            "  show                     Print the current active policy as YAML\n"
            "  list                     List all versions of policies for this client\n"
            "  check '<json-action>'    Dry-run an action against the active policy\n"
            "  activate <policy_id>     Roll back to / activate a specific policy version"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    psub = p_policy.add_subparsers(dest="policy_action", required=True)

    p_export = psub.add_parser("export", help="Print a preset as YAML")
    p_export.add_argument("preset", help=f"One of: {', '.join(_ALLOWED_PRESETS)}")
    p_export.set_defaults(func=cmd_policy_export)

    p_push = psub.add_parser("push", help="Push a YAML file as a new policy version")
    p_push.add_argument("file", help="Path to YAML policy file")
    p_push.set_defaults(func=cmd_policy_push)

    p_show = psub.add_parser("show", help="Print the active policy as YAML")
    p_show.set_defaults(func=cmd_policy_show)

    p_plist = psub.add_parser("list", help="List all policy versions")
    p_plist.set_defaults(func=cmd_policy_list)

    p_check = psub.add_parser(
        "check",
        help="Dry-run an action against the active policy (no transaction recorded)",
    )
    p_check.add_argument(
        "action_json",
        help="JSON action object, or '-' to read from stdin",
    )
    p_check.add_argument("--json", action="store_true", help="Output the full check response as JSON")
    p_check.add_argument("--verbose", "-v", action="store_true", help="Show signal details")
    p_check.set_defaults(func=cmd_policy_check)

    p_activate = psub.add_parser("activate", help="Activate a specific policy version")
    p_activate.add_argument("policy_id", help="UUID of the policy version to activate")
    p_activate.set_defaults(func=cmd_policy_activate)

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

    # ── `veto agent ...` — scaffolding + lifecycle commands for runnable agents
    p_agent = sub.add_parser(
        "agent",
        help="Scaffold and manage Veto-governed agents (`agent init`, more soon)",
        description=(
            "Commands for spinning up runnable agents that are pre-wired with\n"
            "Veto policy enforcement. v0.6 ships `agent init` for Coinbase CDP\n"
            "AgentKit (TypeScript). More integrations land as the build matures."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    asub = p_agent.add_subparsers(dest="agent_action", required=True)

    p_agent_init = asub.add_parser(
        "init",
        help="Scaffold a runnable Veto-governed agent project on disk",
        description=(
            "Creates a runnable agent project locally with Veto policy enforcement\n"
            "wired in. Provisions a smart-account wallet via Coinbase CDP and\n"
            "drops a TypeScript scaffold you can run with `npm run dev`.\n\n"
            f"Supported types:\n"
            + "\n".join(f"  {t:<8} — {desc}" for t, desc in _AGENT_TYPES.items())
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_agent_init.add_argument(
        "--type",
        choices=list(_AGENT_TYPES.keys()),
        default=_DEFAULT_AGENT_TYPE,
        help=f"Which wallet stack to scaffold (default: {_DEFAULT_AGENT_TYPE} — viem + local key)",
    )
    p_agent_init.add_argument(
        "--dir",
        help="Output directory for the generated project (default: ./veto-agent)",
    )
    p_agent_init.add_argument(
        "--name",
        help="Agent name baked into the generated config (default: default-agent)",
    )
    p_agent_init.add_argument(
        "--mission",
        help="Free-text mission baked into the agent's policy (default: a sensible inference-agent mission)",
    )
    p_agent_init.add_argument(
        "--no-prompt",
        action="store_true",
        help="Skip interactive prompts. Scaffold with empty .env (good for CI or scripted use).",
    )
    p_agent_init.set_defaults(func=cmd_agent_init)

    p_agent_configure = asub.add_parser(
        "configure",
        help="Re-run onboarding prompts on an existing scaffolded project (fill in skipped keys)",
        description=(
            "Re-prompt for the secrets the scaffolded agent needs (Veto / Anthropic / CDP)\n"
            "and rewrite the project's .env. Run this from inside the agent project,\n"
            "or pass --dir <path>."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_agent_configure.add_argument(
        "--dir",
        help="Path to an existing scaffolded project (default: current directory)",
    )
    p_agent_configure.set_defaults(func=cmd_agent_configure)

    # ── veto agent fund ──────────────────────────────────────────────
    from . import agent_commands as _agent_cmds
    p_agent_fund = asub.add_parser(
        "fund",
        help="Print the agent's wallet address, open a faucet (testnet) or buy guidance (mainnet), poll for funds",
        description=(
            "Show the EOA address from this project's .env, auto-open the right\n"
            "faucet (Sepolia) or print buy guidance (mainnet), then poll the chain\n"
            "until the wallet has enough ETH to deploy a smart wallet + run a few txs."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_agent_fund.add_argument("--dir", help="Path to a scaffolded project (default: cwd)")
    p_agent_fund.add_argument("--min-eth", type=float, default=0.005, help="Minimum balance to wait for (default: 0.005)")
    p_agent_fund.set_defaults(func=_agent_cmds.cmd_agent_fund)

    # ── veto agent deploy ────────────────────────────────────────────
    p_agent_deploy = asub.add_parser(
        "deploy",
        help="Deploy a VetoGuardedAccount, fund it from the EOA, wire WALLET_CONTRACT into .env",
        description=(
            "Deploy a VetoGuardedAccount smart wallet so this agent can spend with\n"
            "chain-level hard-stop enforcement. The contract refuses to release funds\n"
            "without a fresh, in-scope, Veto-signed mandate.\n\n"
            "Run after `veto agent fund` so the EOA has gas. Writes WALLET_CONTRACT\n"
            "to your .env when done."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_agent_deploy.add_argument("--dir", help="Path to a scaffolded project (default: cwd)")
    p_agent_deploy.add_argument("--fund-eth", type=float, default=0.001, help="ETH to seed the contract with from your EOA (default: 0.001)")
    p_agent_deploy.add_argument("--force", action="store_true", help="Redeploy even if WALLET_CONTRACT is already set")
    p_agent_deploy.add_argument(
        "--i-understand-unaudited", action="store_true",
        help="Required on mainnet: acknowledge VetoGuardedAccount is unaudited.",
    )
    p_agent_deploy.set_defaults(func=_agent_cmds.cmd_agent_deploy)

    # ── veto agent status ────────────────────────────────────────────
    p_agent_status = asub.add_parser(
        "status",
        help="Snapshot of the agent: wallet, contract, balances, Veto policy",
        description="Show the full state of this agent project — Veto keys, EOA + smart wallet balances, contract address.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_agent_status.add_argument("--dir", help="Path to a scaffolded project (default: cwd)")
    p_agent_status.set_defaults(func=_agent_cmds.cmd_agent_status)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
