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
    print(f"  {C.BOLD}Try it:{C.RESET}")
    print(f"    {C.CYAN}veto authorize --amount 50000 --merchant amazon.com --action payment{C.RESET}")
    print(f"    {C.DIM}→ should be DENIED (over per-tx cap){C.RESET}")
    print()
    print(f"    {C.CYAN}veto authorize --amount 0.05 --merchant api.test.com --action payment{C.RESET}")
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
        print()
        if status in ("approved", "executed"):
            ok(f"{C.BOLD}{C.GREEN}APPROVED{C.RESET} {C.DIM}— risk {risk:.2f}{C.RESET}")
            if tx_id:
                info(f"transaction_id: {C.DIM}{tx_id}{C.RESET}")
        elif status == "denied":
            err(f"{C.BOLD}DENIED{C.RESET} {C.DIM}— risk {risk:.2f}{C.RESET}")
            reason = r.get("reason", "")
            if reason:
                info(f"reason: {reason}")
            if tx_id:
                info(f"transaction_id: {C.DIM}{tx_id}{C.RESET}")
        elif status == "escalated":
            warn(f"{C.BOLD}ESCALATED{C.RESET} {C.DIM}— risk {risk:.2f}{C.RESET}")
            reason = r.get("reason", "Human approval required.")
            info(reason)
            info(f"review at {C.DIM}{base_url}/dashboard/{C.RESET}")
            if tx_id:
                info(f"transaction_id: {C.DIM}{tx_id}{C.RESET}")
        else:
            err(f"Unexpected response status: {status}")
            info(f"raw: {r}")
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
        print(f"  {C.DIM}risk_score:{C.RESET}      {payload.get('risk_score', '?')}")
        if payload.get("reason_codes"):
            print(f"  {C.DIM}reason_codes:{C.RESET}    {', '.join(payload['reason_codes'])}")
        if payload.get("policy"):
            p = payload["policy"]
            print(f"  {C.DIM}policy:{C.RESET}          {p.get('name', '')} v{p.get('version_number', '?')}")
            print(f"  {C.DIM}policy_id:{C.RESET}       {C.DIM}{p.get('id', '')}{C.RESET}")
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

    print()
    print(f"  {C.BOLD}Policy versions:{C.RESET}")
    print()
    for p in policies:
        marker = f"{C.GREEN}●{C.RESET}" if p["is_active"] else f"{C.DIM}·{C.RESET}"
        active_label = f"{C.GREEN}active{C.RESET}" if p["is_active"] else f"{C.DIM}inactive{C.RESET}"
        print(
            f"  {marker} v{p['version_number']:<3}  {p['name']:30s}  "
            f"{active_label}  {C.DIM}{p['policy_id']}{C.RESET}"
        )
    print()


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
            "Two input modes:\n"
            "  Flags: veto authorize --agent <uuid> --amount 0.05 --merchant test --action payment\n"
            "  Stdin: echo '{\"agent_id\":\"...\",\"amount\":0.05,...}' | veto authorize -\n\n"
            f"Allowed --action values: {', '.join(_ALLOWED_ACTIONS)}\n"
            "Exit codes: 0=approved, 1=denied, 2=escalated, 3=error"
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

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
