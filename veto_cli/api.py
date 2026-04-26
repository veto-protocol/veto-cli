"""
Lightweight Veto API client — stdlib only to keep CLI install frictionless.
"""

import json
import urllib.error
import urllib.request

from veto_cli import __version__


DEFAULT_BASE_URL = "https://veto-ai.com"


class VetoAPIError(Exception):
    """Raised when the Veto API returns an error or is unreachable."""

    def __init__(self, message: str, status_code: int | None = None, body: dict | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.body = body or {}


def _request(base_url: str, api_key: str, method: str, path: str, body: dict | None = None) -> dict:
    url = f"{base_url.rstrip('/')}{path}"
    headers = {
        "X-Veto-Api-Key": api_key,
        "Content-Type": "application/json",
        "User-Agent": f"veto-cli/{__version__}",
    }
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        # Try to parse JSON error body; surface it through the exception so callers can decide.
        try:
            payload = json.loads(e.read().decode())
        except Exception:
            raise VetoAPIError(f"HTTP {e.code}: {e.reason}", status_code=e.code)
        # If server returned a structured error (denied tx etc.), still pass it back so caller can use status field
        if isinstance(payload, dict) and "status" in payload:
            return payload
        raise VetoAPIError(payload.get("error", f"HTTP {e.code}"), status_code=e.code, body=payload)
    except urllib.error.URLError as e:
        raise VetoAPIError(f"Connection failed: {e.reason}")


def authorize(
    base_url: str,
    api_key: str,
    agent_id: str,
    amount: float | None,
    merchant: str,
    description: str = "",
    context: str = "",
    action: str = "payment",
    decision_only: bool = False,
    extra: dict | None = None,
) -> dict:
    """
    POST /api/v1/authorize/

    `action` must be one of the backend's allowed types — currently
    "payment", "crypto_transfer", or "tool_execution".

    `decision_only=True` runs the engine + records the transaction but
    skips executor side effects (Stripe card creation, crypto sign, MCP forward).
    Used by `veto authorize` CLI for pure Mode 1 decision flows.

    `extra` lets stdin-fed JSON pass through fields like `chain`, `to_address`,
    `token_contract`, `amount_wei`, `currency`, `payload`, `idempotency_key`.
    """
    body = {
        "agent_id": agent_id,
        "action": action,
        "amount": amount,
        "merchant": merchant,
        "description": description,
        "context": context,
        "decision_only": decision_only,
    }
    if extra:
        # Don't let extra clobber required core fields
        for k, v in extra.items():
            if k not in body or body[k] in (None, ""):
                body[k] = v
    return _request(base_url, api_key, "POST", "/api/v1/authorize/", body)


def get_reputation(base_url: str, agent_id: str) -> dict:
    """Public endpoint — no auth."""
    url = f"{base_url.rstrip('/')}/api/v1/public/reputation/{agent_id}/"
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode())
        except Exception:
            raise VetoAPIError(f"HTTP {e.code}: {e.reason}")


def verify_key(base_url: str, api_key: str) -> bool:
    """Quick check that API key is valid."""
    try:
        r = _request(base_url, api_key, "POST", "/api/v1/authorize/", {})
        # 400 (missing fields) means key is valid but request is invalid — that's a valid key
        return True
    except VetoAPIError:
        return False
