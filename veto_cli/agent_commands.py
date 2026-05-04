"""
`veto agent` subcommands beyond `init` — fund, deploy, status.

Each verb is composable + re-runnable. `veto agent init` chains them together
for first-time onboarding; power users can drop in to any one of them later.
"""

from __future__ import annotations

import os
import sys
import time
import urllib.error
from pathlib import Path

from . import onchain


# ─── Color codes (mirror main.py's helper class) ──────────────────────

class C:
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RESET = "\033[0m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    CYAN = "\033[96m"


def _err(msg: str) -> None:
    print(f"  {C.RED}✗{C.RESET} {msg}", file=sys.stderr)


def _ok(msg: str) -> None:
    print(f"  {C.GREEN}✓{C.RESET} {msg}")


def _info(msg: str) -> None:
    print(f"  {C.DIM}·{C.RESET} {msg}")


def _warn(msg: str) -> None:
    print(f"  {C.YELLOW}!{C.RESET} {msg}")


def _header(title: str) -> None:
    print()
    print(f"  {C.BOLD}{C.CYAN}{title}{C.RESET}")
    print(f"  {C.DIM}{'─' * 56}{C.RESET}")


# ─── Env helpers ──────────────────────────────────────────────────────

def _read_env(target_dir: Path) -> dict[str, str]:
    """Parse a .env file into a dict. Tolerates blank lines + comments."""
    env_path = target_dir / ".env"
    if not env_path.exists():
        raise FileNotFoundError(f"No .env at {env_path}")
    out: dict[str, str] = {}
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        k, _, v = line.partition("=")
        out[k.strip()] = v.strip()
    return out


def _write_env_value(target_dir: Path, key: str, value: str) -> None:
    """Update or append a single key=value pair in .env, preserving the rest."""
    env_path = target_dir / ".env"
    if not env_path.exists():
        raise FileNotFoundError(f"No .env at {env_path}")
    lines = env_path.read_text(encoding="utf-8").splitlines()
    found = False
    for i, line in enumerate(lines):
        s = line.lstrip()
        if s.startswith("#") or "=" not in s:
            continue
        k = s.split("=", 1)[0].strip()
        if k == key:
            lines[i] = f"{key}={value}"
            found = True
            break
    if not found:
        lines.append(f"{key}={value}")
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# Network → (chain_id, default rpc) map. Mirrors the agent template's wallet-wrap.ts.
_NETWORKS = {
    "base-mainnet": (8453, "https://mainnet.base.org"),
    "base-sepolia": (84532, "https://sepolia.base.org"),
    "ethereum":     (1,    "https://eth.llamarpc.com"),
}


def _resolve_network(env: dict[str, str]) -> tuple[str, int, str]:
    """Pick (network_name, chain_id, rpc_url) from env, with sensible fallbacks."""
    network = env.get("NETWORK", "base-mainnet")
    rpc_url = env.get("RPC_URL") or _NETWORKS.get(network, (None, None))[1] or "https://mainnet.base.org"
    chain_id = int(env.get("CHAIN_ID") or _NETWORKS.get(network, (None, None))[0] or 8453)
    return network, chain_id, rpc_url


def _resolve_target_dir(args) -> Path:
    target = Path(getattr(args, "dir", None) or ".").resolve()
    if not (target / ".env").exists():
        _err(f"Doesn't look like a scaffolded Veto agent project: {target}")
        _info("Run from inside a directory created by `veto agent init`,")
        _info("or pass --dir <path> pointing to one.")
        sys.exit(1)
    return target


# ─── Address derivation (lazy import — eth_account is optional) ───────

def _address_from_pk(private_key_hex: str) -> str:
    from eth_account import Account
    return Account.from_key(private_key_hex).address


def _format_eth(wei: int) -> str:
    return f"{wei / 10**18:.6f} ETH"


# ─── veto agent fund ──────────────────────────────────────────────────

def cmd_agent_fund(args) -> None:
    """Print the EOA address, open a faucet (testnet) or buy guidance (mainnet),
    poll the chain until funds arrive."""
    target_dir = _resolve_target_dir(args)
    env = _read_env(target_dir)

    pk = env.get("WALLET_PRIVATE_KEY")
    if not pk:
        _err("WALLET_PRIVATE_KEY not set in .env. Run `veto agent configure`.")
        sys.exit(1)

    network, chain_id, rpc_url = _resolve_network(env)
    addr = _address_from_pk(pk)

    min_eth = float(getattr(args, "min_eth", 0.005) or 0.005)
    min_wei = int(min_eth * 10**18)

    _header("veto agent fund")
    print(f"  {C.DIM}network:{C.RESET}    {network} (chain {chain_id})")
    print(f"  {C.DIM}address:{C.RESET}    {C.BOLD}{addr}{C.RESET}")

    try:
        bal = onchain.get_balance(rpc_url, addr)
    except Exception as e:
        _err(f"RPC error checking balance: {e}")
        sys.exit(1)
    print(f"  {C.DIM}balance:{C.RESET}    {_format_eth(bal)}")
    print()

    if bal >= min_wei:
        _ok(f"Already funded (≥ {min_eth} ETH). Nothing to do.")
        return

    _info(f"Need at least {min_eth} ETH for gas + a smart-wallet deploy.")
    print()

    if "sepolia" in network:
        faucet = onchain.SEPOLIA_FAUCETS[0]
        print(f"  {C.BOLD}Opening the Base Sepolia faucet:{C.RESET}")
        print(f"  {C.CYAN}→ {faucet}{C.RESET}")
        opened = onchain.open_faucet(faucet)
        if not opened:
            _warn("Couldn't auto-open browser. Visit the URL manually.")
        print()
        print(f"  Paste this address into the faucet:")
        print(f"    {C.BOLD}{addr}{C.RESET}")
        print()
        print(f"  Other faucets if that one is rate-limited:")
        for url in onchain.SEPOLIA_FAUCETS[1:]:
            print(f"    {C.DIM}→ {url}{C.RESET}")
    else:
        # Mainnet — no faucets; explain how to fund.
        print(f"  {C.BOLD}This is mainnet — no free faucet.{C.RESET}")
        print(f"  Send {min_eth} ETH on {network} to:")
        print(f"    {C.BOLD}{addr}{C.RESET}")
        print(f"  From any wallet or a CEX. {explorer_link(chain_id, addr)}")
    print()

    print(f"  {C.DIM}Polling for funds (timeout 10 min)...{C.RESET}")

    last_print = 0.0

    def _on_tick(elapsed: int, balance: int) -> None:
        nonlocal last_print
        # Throttle output — once every ~10s.
        if elapsed - last_print < 10 and balance < min_wei:
            return
        last_print = elapsed
        if balance >= min_wei:
            print(f"  {C.GREEN}✓{C.RESET} {_format_eth(balance)} (funded after {elapsed}s)")
        else:
            print(f"  {C.DIM}·{C.RESET} {_format_eth(balance)} (waiting, {elapsed}s)")

    try:
        final_bal = onchain.wait_for_funds(
            rpc_url, addr, min_wei=min_wei, timeout_s=600, poll_s=5.0,
            on_tick=_on_tick,
        )
    except TimeoutError:
        _err("Timed out waiting for funds. Re-run `veto agent fund` to keep polling.")
        sys.exit(1)
    except Exception as e:
        _err(f"RPC error: {e}")
        sys.exit(1)

    print()
    _ok(f"Funded: {_format_eth(final_bal)}")
    if "sepolia" in network or network == "base-mainnet":
        _info(f"View: {onchain.explorer_address(chain_id, addr)}")
    print()
    _info("Try `veto agent deploy` next to deploy a smart wallet for hard-stop enforcement.")


def explorer_link(chain_id: int, addr: str) -> str:
    return f"View: {onchain.explorer_address(chain_id, addr)}"


# ─── veto agent deploy ────────────────────────────────────────────────

def cmd_agent_deploy(args) -> None:
    """Deploy a VetoGuardedAccount, fund it from the EOA, write WALLET_CONTRACT to .env."""
    target_dir = _resolve_target_dir(args)
    env = _read_env(target_dir)

    pk = env.get("WALLET_PRIVATE_KEY")
    if not pk:
        _err("WALLET_PRIVATE_KEY not set in .env. Run `veto agent configure`.")
        sys.exit(1)

    network, chain_id, rpc_url = _resolve_network(env)
    deployer_addr = _address_from_pk(pk)

    fund_eth = float(getattr(args, "fund_eth", 0.001) or 0.001)
    fund_wei = int(fund_eth * 10**18)
    veto_base_url = env.get("VETO_BASE_URL", "https://veto-ai.com")

    _header("veto agent deploy")
    print(f"  {C.DIM}network:{C.RESET}    {network} (chain {chain_id})")
    print(f"  {C.DIM}deployer:{C.RESET}   {deployer_addr}")

    if env.get("WALLET_CONTRACT"):
        _warn(f"WALLET_CONTRACT is already set: {env['WALLET_CONTRACT']}")
        if not getattr(args, "force", False):
            _info("Re-run with --force to redeploy a fresh contract.")
            sys.exit(1)

    # Estimate the real gas cost from the chain. Base Sepolia is ~1000x cheaper
    # than mainnet, and a fixed-1-gwei estimate would over-reject by orders of
    # magnitude. Use 2× actual gas price + the requested fund amount as the bar.
    try:
        bal = onchain.get_balance(rpc_url, deployer_addr)
        gas_price = onchain.get_gas_price(rpc_url)
    except Exception as e:
        _err(f"RPC error: {e}")
        sys.exit(1)
    deploy_gas_estimate = 700_000 * gas_price * 2  # 2× headroom
    fund_tx_gas = 21_000 * gas_price * 2
    needed_wei = deploy_gas_estimate + fund_wei + fund_tx_gas
    print(f"  {C.DIM}balance:{C.RESET}    {_format_eth(bal)}")
    print(f"  {C.DIM}gas price:{C.RESET}  {gas_price / 1e9:.4f} gwei")

    if bal < needed_wei:
        _err(f"Insufficient balance: have {_format_eth(bal)}, need ~{_format_eth(needed_wei)}.")
        _info(f"Try `veto agent fund` to top up, or pass --fund-eth 0 to skip funding the contract.")
        sys.exit(1)

    # Fetch the Veto on-chain signer.
    try:
        veto_signer = onchain.fetch_signer_address(veto_base_url)
    except (urllib.error.URLError, RuntimeError) as e:
        _err(f"Couldn't fetch Veto on-chain signer from {veto_base_url}: {e}")
        sys.exit(1)
    print(f"  {C.DIM}veto signer:{C.RESET} {veto_signer} {C.DIM}(from {veto_base_url}){C.RESET}")
    print()

    # Mainnet guard: contract is unaudited.
    if "mainnet" in network and not getattr(args, "i_understand_unaudited", False):
        _warn("VetoGuardedAccount is UNAUDITED. Don't put real money in it on mainnet.")
        _info("Re-run with --i-understand-unaudited if you really want to.")
        sys.exit(1)

    print(f"  {C.DIM}Deploying VetoGuardedAccount...{C.RESET}")
    try:
        contract_addr, deploy_tx = onchain.deploy_veto_guarded_account(
            deployer_private_key=pk,
            owner_address=deployer_addr,
            veto_signer_address=veto_signer,
            rpc_url=rpc_url,
            chain_id=chain_id,
        )
    except Exception as e:
        _err(f"Deploy failed: {e}")
        sys.exit(1)
    _ok(f"Deployed at {C.BOLD}{contract_addr}{C.RESET}")
    _info(f"tx:   {onchain.explorer_tx(chain_id, deploy_tx)}")

    # Fund the contract from the EOA.
    if fund_wei > 0:
        print()
        print(f"  {C.DIM}Funding contract with {fund_eth} ETH...{C.RESET}")
        try:
            fund_tx = onchain.fund_contract_from_deployer(
                deployer_private_key=pk,
                contract_address=contract_addr,
                amount_wei=fund_wei,
                rpc_url=rpc_url,
                chain_id=chain_id,
            )
        except Exception as e:
            _err(f"Funding failed: {e}")
            _info("The contract is deployed but empty. You can transfer ETH to it manually.")
            sys.exit(1)
        _ok(f"Funded with {fund_eth} ETH")
        _info(f"tx:   {onchain.explorer_tx(chain_id, fund_tx)}")

    # Write WALLET_CONTRACT to .env
    _write_env_value(target_dir, "WALLET_CONTRACT", contract_addr)
    print()
    _ok(f"Wrote WALLET_CONTRACT={contract_addr} to .env")
    print()
    print(f"  {C.BOLD}Hard-stop enforcement is now active.{C.RESET}")
    _info(f"View contract: {onchain.explorer_address(chain_id, contract_addr)}")
    _info("Try: `veto agent status` to see the full picture, or `npm run dev` to talk to your agent.")


# ─── veto agent status ────────────────────────────────────────────────

def cmd_agent_status(args) -> None:
    """Snapshot of the agent: wallet, contract, balances, policy."""
    target_dir = _resolve_target_dir(args)
    env = _read_env(target_dir)

    network, chain_id, rpc_url = _resolve_network(env)
    pk = env.get("WALLET_PRIVATE_KEY", "")

    _header("veto agent status")
    print(f"  {C.DIM}project:{C.RESET}    {target_dir}")
    print(f"  {C.DIM}network:{C.RESET}    {network} (chain {chain_id})")
    print()

    # Agent / Veto
    print(f"  {C.BOLD}Veto{C.RESET}")
    api_key = env.get("VETO_API_KEY", "")
    agent_id = env.get("VETO_AGENT_ID", "")
    if api_key:
        masked = api_key[:8] + "…" + api_key[-4:] if len(api_key) > 16 else "***"
        print(f"    {C.DIM}api_key:{C.RESET}    {masked}")
    else:
        print(f"    {C.YELLOW}api_key:    not set{C.RESET}")
    if agent_id:
        print(f"    {C.DIM}agent_id:{C.RESET}   {agent_id}")
    else:
        print(f"    {C.YELLOW}agent_id:   not set — run `veto register`{C.RESET}")
    print()

    # LLM
    print(f"  {C.BOLD}LLM brain{C.RESET}")
    provider = env.get("LLM_PROVIDER", "anthropic")
    key_var = {"anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY", "grok": "XAI_API_KEY"}.get(provider, "")
    has_key = bool(env.get(key_var, ""))
    print(f"    {C.DIM}provider:{C.RESET}   {provider} {C.GREEN}✓{C.RESET}" if has_key else f"    {C.DIM}provider:{C.RESET}   {provider} {C.YELLOW}(no key){C.RESET}")
    print()

    # EOA wallet
    print(f"  {C.BOLD}Wallet (EOA — pays gas){C.RESET}")
    if not pk:
        print(f"    {C.YELLOW}WALLET_PRIVATE_KEY not set{C.RESET}")
    else:
        eoa_addr = _address_from_pk(pk)
        print(f"    {C.DIM}address:{C.RESET}    {eoa_addr}")
        try:
            bal = onchain.get_balance(rpc_url, eoa_addr)
            print(f"    {C.DIM}balance:{C.RESET}    {_format_eth(bal)}")
        except Exception as e:
            print(f"    {C.YELLOW}balance:    (RPC error: {e}){C.RESET}")
    print()

    # Smart wallet
    contract = env.get("WALLET_CONTRACT", "")
    print(f"  {C.BOLD}Smart wallet (holds funds, hard-stop){C.RESET}")
    if not contract:
        print(f"    {C.DIM}not deployed — run `veto agent deploy` to enable hard-stop{C.RESET}")
    else:
        print(f"    {C.DIM}address:{C.RESET}    {contract}")
        try:
            bal = onchain.get_balance(rpc_url, contract)
            print(f"    {C.DIM}balance:{C.RESET}    {_format_eth(bal)}")
            print(f"    {C.DIM}view:{C.RESET}       {onchain.explorer_address(chain_id, contract)}")
        except Exception as e:
            print(f"    {C.YELLOW}balance:    (RPC error: {e}){C.RESET}")
    print()
