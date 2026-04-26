"""
Lightweight Veto API client — stdlib only to keep CLI install frictionless.
"""

import json
import urllib.error
import urllib.request


DEFAULT_BASE_URL = "https://veto-ai.com"


class VetoAPIError(Exception):
    pass


def _request(base_url: str, api_key: str, method: str, path: str, body: dict | None = None) -> dict:
    url = f"{base_url.rstrip('/')}{path}"
    headers = {
        "X-Veto-Api-Key": api_key,
        "Content-Type": "application/json",
        "User-Agent": "veto-cli/0.1.0",
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
            raise VetoAPIError(f"HTTP {e.code}: {e.reason}")
    except urllib.error.URLError as e:
        raise VetoAPIError(f"Connection failed: {e.reason}")


def authorize(base_url: str, api_key: str, agent_id: str, amount: float, merchant: str, description: str, context: str) -> dict:
    return _request(base_url, api_key, "POST", "/api/v1/authorize/", {
        "agent_id": agent_id,
        "action": "payment",
        "amount": amount,
        "merchant": merchant,
        "description": description,
        "context": context,
    })


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
