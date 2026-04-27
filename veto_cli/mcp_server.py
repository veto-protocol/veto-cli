"""
Veto MCP Server — minimal JSON-RPC-over-stdio implementation.

This is what MCP clients (Claude Desktop, Cursor, etc.) spawn as a subprocess.
It speaks MCP protocol on stdin/stdout and proxies tool calls to Veto's API.

Run:
    python -m veto_cli.mcp_server --api-key <key> --base-url https://veto-ai.com
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any


def _http(base_url: str, api_key: str, method: str, path: str, body: dict | None = None) -> dict:
    url = f"{base_url.rstrip('/')}{path}"
    headers = {
        "X-Veto-Api-Key": api_key,
        "Content-Type": "application/json",
        "User-Agent": "veto-mcp/0.1.0",
    }
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode())
        except Exception:
            return {"error": f"HTTP {e.code}: {e.reason}"}
    except urllib.error.URLError as e:
        return {"error": f"Connection failed: {e.reason}"}


TOOLS = [
    {
        "name": "veto_authorize",
        "description": (
            "Request authorization from Veto before making a fiat payment. "
            "Veto evaluates against policy, fraud signals, and prompt injection. "
            "Returns a virtual Stripe card on approve. ALWAYS call before spending money."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "agent_id": {"type": "string", "description": "Your registered agent UUID in Veto"},
                "action": {
                    "type": "string",
                    "enum": ["payment", "tool_execution"],
                    "description": "payment for fiat via Stripe; use veto_crypto_authorize for on-chain payments",
                },
                "amount": {"type": "number", "description": "Transaction amount in the given currency"},
                "currency": {"type": "string", "description": "ISO currency code", "default": "USD"},
                "merchant": {"type": "string", "description": "Who the payment is going to"},
                "description": {"type": "string", "description": "What this transaction is for"},
                "context": {"type": "string", "description": "The original user request that led to this action"},
            },
            "required": ["agent_id", "action", "description", "context"],
        },
    },
    {
        "name": "veto_crypto_authorize",
        "description": (
            "Request authorization from Veto before signing a crypto transaction. "
            "Call this BEFORE broadcasting any on-chain transfer, token approval, or contract "
            "interaction that moves value. Veto checks the destination against OFAC sanctions, "
            "known scam databases, policy limits, and returns an approval token (signature) on "
            "approve or a denial reason. The signature is a cryptographic receipt — in advisory "
            "mode it's for audit; in smart-account mode it's the co-signature the wallet needs "
            "to execute on-chain."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "agent_id": {"type": "string", "description": "Your registered agent UUID in Veto"},
                "chain": {
                    "type": "string",
                    "enum": ["base", "ethereum", "optimism", "arbitrum", "polygon", "solana"],
                    "description": "Which blockchain the transaction will execute on",
                },
                "to_address": {"type": "string", "description": "Destination wallet/contract address"},
                "token_contract": {
                    "type": "string",
                    "description": "ERC-20/SPL contract address. Omit or empty string = native asset (ETH/SOL).",
                },
                "amount": {"type": "number", "description": "Value in USD (for policy checks)"},
                "amount_wei": {"type": "string", "description": "Exact on-chain amount (wei/lamports) as a string"},
                "description": {"type": "string", "description": "What this crypto transaction is for"},
                "context": {"type": "string", "description": "The original user request that led to this action"},
            },
            "required": ["agent_id", "chain", "to_address", "description", "context"],
        },
    },
    {
        "name": "veto_check_status",
        "description": "Check the status of a previously submitted Veto transaction. Use this to poll escalated transactions that are waiting for human approval.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "transaction_id": {"type": "string", "description": "The transaction UUID returned by veto_authorize"},
            },
            "required": ["transaction_id"],
        },
    },
    {
        "name": "veto_reputation",
        "description": "Look up the reputation score (0-1000, credit-score-style) for any AI agent. Use this before trusting an unfamiliar agent or checking your own agent's standing.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "agent_id": {"type": "string", "description": "The agent UUID to look up"},
            },
            "required": ["agent_id"],
        },
    },
    {
        "name": "veto_policy_show",
        "description": (
            "Return the agent owner's currently-active Veto security policy as JSON. "
            "Use this to introspect what limits, allowlists, and approval thresholds apply "
            "before attempting an action — so you can plan within bounds instead of "
            "discovering them by being denied. Includes per-tx / daily / monthly caps, "
            "merchant allowlist + blocklist, chain allowlist, approval thresholds, and "
            "the policy version_number that receipts will cite."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "veto_policy_check",
        "description": (
            "Dry-run a proposed action against the active policy WITHOUT recording a "
            "transaction or producing side effects. Returns {decision, risk_score, "
            "reason_codes, signals, policy}. Use this for pre-flight: an agent calls "
            "policy_check, sees the action would be denied with reason_code "
            "MERCHANT_NOT_ALLOWLISTED, and asks the user to update the allowlist before "
            "wasting work. veto_authorize is the real call; this is the cheap preview."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "agent_id": {"type": "string", "description": "Your registered agent UUID in Veto"},
                "action": {
                    "type": "string",
                    "enum": ["payment", "crypto_transfer", "tool_execution"],
                    "description": "Action type — same values as veto_authorize",
                },
                "amount": {"type": "number", "description": "Transaction amount in the given currency"},
                "currency": {"type": "string", "description": "ISO currency code", "default": "USD"},
                "merchant": {"type": "string", "description": "Who the payment would go to"},
                "description": {"type": "string", "description": "What this transaction is for"},
                "context": {"type": "string", "description": "The original user request that led to this action"},
                "chain": {
                    "type": "string",
                    "description": "Blockchain (only for crypto_transfer): base, ethereum, polygon, etc.",
                },
                "to_address": {"type": "string", "description": "Destination address (only for crypto_transfer)"},
                "token_contract": {
                    "type": "string",
                    "description": "ERC-20/SPL contract address (only for crypto_transfer)",
                },
            },
            "required": ["agent_id", "action"],
        },
    },
]


def handle_tool_call(tool_name: str, arguments: dict, base_url: str, api_key: str) -> dict:
    if tool_name == "veto_authorize":
        return _http(base_url, api_key, "POST", "/api/v1/authorize/", {
            "agent_id": arguments["agent_id"],
            "action": arguments["action"],
            "amount": arguments.get("amount"),
            "currency": arguments.get("currency", "USD"),
            "merchant": arguments.get("merchant", ""),
            "description": arguments.get("description", ""),
            "context": arguments.get("context", ""),
        })
    elif tool_name == "veto_crypto_authorize":
        return _http(base_url, api_key, "POST", "/api/v1/authorize/", {
            "agent_id": arguments["agent_id"],
            "action": "crypto_transfer",
            "chain": arguments.get("chain", ""),
            "to_address": arguments.get("to_address", ""),
            "token_contract": arguments.get("token_contract", ""),
            "amount": arguments.get("amount"),
            "amount_wei": arguments.get("amount_wei", ""),
            "description": arguments.get("description", ""),
            "context": arguments.get("context", ""),
        })
    elif tool_name == "veto_check_status":
        return _http(base_url, api_key, "GET", f"/api/v1/transactions/{arguments['transaction_id']}/")
    elif tool_name == "veto_reputation":
        return _http(base_url, api_key, "GET", f"/api/v1/public/reputation/{arguments['agent_id']}/")
    elif tool_name == "veto_policy_show":
        return _http(base_url, api_key, "GET", "/api/v1/policies/active/")
    elif tool_name == "veto_policy_check":
        body = {
            "agent_id": arguments["agent_id"],
            "action": arguments["action"],
            "amount": arguments.get("amount"),
            "currency": arguments.get("currency", "USD"),
            "merchant": arguments.get("merchant", ""),
            "description": arguments.get("description", ""),
            "context": arguments.get("context", ""),
        }
        # Pass through crypto-specific fields when present so check evaluates
        # against the same engine pipeline as a real authorize would.
        for k in ("chain", "to_address", "token_contract", "amount_wei"):
            if arguments.get(k):
                body[k] = arguments[k]
        return _http(base_url, api_key, "POST", "/api/v1/policies/check/", body)
    return {"error": f"Unknown tool: {tool_name}"}


class MCPServer:
    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url
        self.api_key = api_key

    def run(self):
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                self._error(None, -32700, "Parse error")
                continue

            msg_id = message.get("id")
            method = message.get("method", "")

            if method == "initialize":
                self._result(msg_id, {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": "veto", "version": "0.1.0"},
                })
            elif method == "notifications/initialized":
                pass
            elif method == "tools/list":
                self._result(msg_id, {"tools": TOOLS})
            elif method == "tools/call":
                params = message.get("params", {})
                result = handle_tool_call(params.get("name", ""), params.get("arguments", {}), self.base_url, self.api_key)
                self._result(msg_id, {
                    "content": [{"type": "text", "text": json.dumps(result, indent=2)}],
                    "isError": "error" in result and result.get("status") not in ("denied", "escalated", "executed"),
                })
            elif method == "ping":
                self._result(msg_id, {})
            else:
                self._error(msg_id, -32601, f"Method not found: {method}")

    def _result(self, msg_id: Any, result: dict):
        sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": msg_id, "result": result}) + "\n")
        sys.stdout.flush()

    def _error(self, msg_id: Any, code: int, message: str):
        sys.stdout.write(json.dumps({
            "jsonrpc": "2.0", "id": msg_id,
            "error": {"code": code, "message": message},
        }) + "\n")
        sys.stdout.flush()


def main():
    p = argparse.ArgumentParser(description="Veto MCP Server")
    p.add_argument("--api-key", default=os.environ.get("VETO_API_KEY"))
    p.add_argument("--base-url", default=os.environ.get("VETO_BASE_URL", "https://veto-ai.com"))
    args = p.parse_args()

    if not args.api_key:
        sys.stderr.write("Error: --api-key required (or set VETO_API_KEY env var)\n")
        sys.exit(1)

    MCPServer(base_url=args.base_url, api_key=args.api_key).run()


if __name__ == "__main__":
    main()
