"""
On-chain helpers for `veto agent init` — deploy a VetoGuardedAccount and wait
for funds.

We deploy from Python (no Foundry on the user's machine) by reading the
bundled compiled artifact in `cli/veto_cli/contracts/VetoGuardedAccount.json`,
ABI-encoding the constructor args, signing the deploy tx with eth_account,
and broadcasting via raw JSON-RPC.

Lazy imports — eth_account / eth_abi are only loaded when the user opts into
hard-stop, so the cooperative path stays light.
"""

from __future__ import annotations

import json
import os
import time
import urllib.request
import webbrowser
from importlib import resources
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass


# --- RPC defaults --------------------------------------------------------

CHAIN_RPCS = {
    8453:  "https://mainnet.base.org",
    84532: "https://sepolia.base.org",
    1:     "https://eth.llamarpc.com",
}

# Public Sepolia faucets — first one auto-opens; the rest are listed as
# fallbacks in case the user doesn't have an Alchemy account.
SEPOLIA_FAUCETS = [
    "https://www.alchemy.com/faucets/base-sepolia",
    "https://docs.base.org/tools/network-faucets",
    "https://www.coinbase.com/faucets/base-ethereum-sepolia-faucet",
]

# Block explorer URL prefix per chain id, for printing tx + address links.
EXPLORERS = {
    8453:  "https://basescan.org",
    84532: "https://sepolia.basescan.org",
    1:     "https://etherscan.io",
}


def explorer_address(chain_id: int, addr: str) -> str:
    base = EXPLORERS.get(chain_id)
    return f"{base}/address/{addr}" if base else addr


def explorer_tx(chain_id: int, tx_hash: str) -> str:
    base = EXPLORERS.get(chain_id)
    return f"{base}/tx/{tx_hash}" if base else tx_hash


# --- Bundled artifact ----------------------------------------------------

def _load_artifact() -> dict:
    """Read the bundled compiled VetoGuardedAccount artifact."""
    with resources.files(__package__).joinpath("contracts/VetoGuardedAccount.json").open("rb") as f:
        return json.load(f)


# --- JSON-RPC helpers (no web3.py dep) -----------------------------------

def _rpc(rpc_url: str, method: str, params: list, *, timeout: int = 30) -> object:
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    req = urllib.request.Request(
        rpc_url,
        data=body,
        headers={"Content-Type": "application/json", "User-Agent": "veto-cli"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        out = json.loads(resp.read())
    if "error" in out:
        raise RuntimeError(f"RPC error from {method}: {out['error']}")
    return out["result"]


def get_balance(rpc_url: str, address: str) -> int:
    """Return the native balance in wei."""
    hex_bal = _rpc(rpc_url, "eth_getBalance", [address, "latest"])
    return int(hex_bal, 16)


def get_chain_id(rpc_url: str) -> int:
    return int(_rpc(rpc_url, "eth_chainId", []), 16)


def get_nonce(rpc_url: str, address: str) -> int:
    return int(_rpc(rpc_url, "eth_getTransactionCount", [address, "pending"]), 16)


def get_gas_price(rpc_url: str) -> int:
    return int(_rpc(rpc_url, "eth_gasPrice", []), 16)


def send_raw_tx(rpc_url: str, signed_hex: str) -> str:
    return _rpc(rpc_url, "eth_sendRawTransaction", [signed_hex])


def wait_for_receipt(rpc_url: str, tx_hash: str, *, timeout_s: int = 180, poll_s: float = 2.0) -> dict:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        out = _rpc(rpc_url, "eth_getTransactionReceipt", [tx_hash])
        if out is not None:
            return out  # type: ignore[return-value]
        time.sleep(poll_s)
    raise TimeoutError(f"Tx {tx_hash} not mined within {timeout_s}s")


# --- Faucet handoff ------------------------------------------------------

def open_faucet(faucet_url: str) -> bool:
    """Best-effort browser open. Returns True if the OS reported success."""
    try:
        return webbrowser.open(faucet_url)
    except Exception:
        return False


def wait_for_funds(
    rpc_url: str,
    address: str,
    *,
    min_wei: int,
    timeout_s: int = 600,
    poll_s: float = 5.0,
    on_tick=None,
) -> int:
    """Poll until the address has at least `min_wei`. Returns the actual balance.

    `on_tick(elapsed_s, balance_wei)` is called each cycle so callers can
    print a spinner / progress line.
    """
    started = time.time()
    while True:
        bal = get_balance(rpc_url, address)
        if on_tick is not None:
            on_tick(int(time.time() - started), bal)
        if bal >= min_wei:
            return bal
        if time.time() - started > timeout_s:
            raise TimeoutError(
                f"Timed out after {timeout_s}s waiting for ≥ {min_wei} wei at {address}"
            )
        time.sleep(poll_s)


# --- Deployment ----------------------------------------------------------

def fetch_signer_address(veto_base_url: str) -> str:
    """Hit GET /api/v1/onchain-signer/ and return Veto's secp256k1 address."""
    url = veto_base_url.rstrip("/") + "/api/v1/onchain-signer/"
    req = urllib.request.Request(url, headers={"User-Agent": "veto-cli"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        body = json.loads(resp.read())
    addr = body.get("address")
    if not addr or not isinstance(addr, str) or not addr.startswith("0x"):
        raise RuntimeError(f"Bad onchain-signer response from {url}: {body}")
    return addr


def deploy_veto_guarded_account(
    *,
    deployer_private_key: str,
    owner_address: str,
    veto_signer_address: str,
    rpc_url: str,
    chain_id: int,
    tx_timeout_s: int = 180,
) -> tuple[str, str]:
    """Deploy a fresh VetoGuardedAccount.

    Returns (contract_address, deploy_tx_hash).
    """
    from eth_account import Account
    from eth_abi import encode as abi_encode

    artifact = _load_artifact()
    bytecode = artifact["bytecode"]
    if bytecode.startswith("0x"):
        bytecode = bytecode[2:]

    # Constructor signature: constructor(address _owner, address _vetoSigner)
    ctor_args = abi_encode(
        ["address", "address"],
        [_as_checksum(owner_address), _as_checksum(veto_signer_address)],
    )
    deploy_data = "0x" + bytecode + ctor_args.hex()

    deployer = Account.from_key(deployer_private_key)
    nonce = get_nonce(rpc_url, deployer.address)
    gas_price = get_gas_price(rpc_url)

    # Estimate gas — fall back to a generous default if estimation fails.
    try:
        est_hex = _rpc(
            rpc_url,
            "eth_estimateGas",
            [{"from": deployer.address, "data": deploy_data}],
        )
        gas_limit = int(int(est_hex, 16) * 12 // 10)  # 20% headroom
    except Exception:
        gas_limit = 1_500_000

    tx = {
        "from": deployer.address,
        "to": None,  # contract creation
        "data": deploy_data,
        "value": 0,
        "gas": gas_limit,
        "gasPrice": gas_price,
        "nonce": nonce,
        "chainId": chain_id,
    }
    signed = Account.sign_transaction(tx, deployer.key)
    raw_hex = "0x" + signed.raw_transaction.hex()
    tx_hash = send_raw_tx(rpc_url, raw_hex)
    receipt = wait_for_receipt(rpc_url, tx_hash, timeout_s=tx_timeout_s)
    if int(receipt.get("status", "0x0"), 16) != 1:
        raise RuntimeError(f"Deploy reverted: {receipt}")
    contract_address = receipt.get("contractAddress")
    if not contract_address:
        raise RuntimeError(f"Deploy receipt has no contractAddress: {receipt}")
    return _as_checksum(contract_address), tx_hash


def fund_contract_from_deployer(
    *,
    deployer_private_key: str,
    contract_address: str,
    amount_wei: int,
    rpc_url: str,
    chain_id: int,
    tx_timeout_s: int = 180,
) -> str:
    """Send `amount_wei` from the deployer EOA to the contract. Returns tx hash."""
    from eth_account import Account

    deployer = Account.from_key(deployer_private_key)
    nonce = get_nonce(rpc_url, deployer.address)
    gas_price = get_gas_price(rpc_url)

    tx = {
        "from": deployer.address,
        "to": _as_checksum(contract_address),
        "value": amount_wei,
        "gas": 30_000,
        "gasPrice": gas_price,
        "nonce": nonce,
        "chainId": chain_id,
        "data": "0x",
    }
    signed = Account.sign_transaction(tx, deployer.key)
    raw_hex = "0x" + signed.raw_transaction.hex()
    tx_hash = send_raw_tx(rpc_url, raw_hex)
    wait_for_receipt(rpc_url, tx_hash, timeout_s=tx_timeout_s)
    return tx_hash


def _as_checksum(addr: str) -> str:
    """Use eth_utils to_checksum_address; falls back to lowercase if eth_utils
    isn't available (which would be surprising — eth_account brings it in)."""
    try:
        from eth_utils import to_checksum_address
        return to_checksum_address(addr)
    except Exception:
        return addr.lower()
