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


def register(
    base_url: str,
    email: str,
    preset: str | None = None,
    mission: str | None = None,
    agent_name: str | None = None,
    org_name: str | None = None,
) -> dict:
    """
    POST /api/v1/register/ — CLI-native signup.

    Creates a User + Client + default AIAgent + SecurityPolicy on the backend
    and returns {api_key, client_id, agent_id, agent_name, mission, org_name, policy}.

    No auth required (this is the bootstrap endpoint).
    """
    body = {"email": email}
    if preset:
        body["preset"] = preset
    if mission:
        body["mission"] = mission
    if agent_name:
        body["agent_name"] = agent_name
    if org_name:
        body["org_name"] = org_name

    url = f"{base_url.rstrip('/')}/api/v1/register/"
    headers = {
        "Content-Type": "application/json",
        "User-Agent": f"veto-cli/{__version__}",
    }
    data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        try:
            payload = json.loads(e.read().decode())
        except Exception:
            raise VetoAPIError(f"HTTP {e.code}: {e.reason}", status_code=e.code)
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


# ---------------------------------------------------------------------------
# Policy authoring — back `veto policy export/push/show/check/activate`.
# Wire format is JSON; CLI converts YAML <-> dict via PyYAML.
# ---------------------------------------------------------------------------

def policy_export_preset(base_url: str, preset_name: str) -> dict:
    """GET /api/v1/policies/presets/<name>/ — public, no auth."""
    url = f"{base_url.rstrip('/')}/api/v1/policies/presets/{preset_name}/"
    headers = {"User-Agent": f"veto-cli/{__version__}"}
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        try:
            payload = json.loads(e.read().decode())
        except Exception:
            raise VetoAPIError(f"HTTP {e.code}: {e.reason}", status_code=e.code)
        raise VetoAPIError(payload.get("error", f"HTTP {e.code}"), status_code=e.code, body=payload)
    except urllib.error.URLError as e:
        raise VetoAPIError(f"Connection failed: {e.reason}")


def policy_push(base_url: str, api_key: str, policy: dict) -> dict:
    """POST /api/v1/policies/ — push a new version. Auto-activates."""
    return _request(base_url, api_key, "POST", "/api/v1/policies/", policy)


def policy_show_active(base_url: str, api_key: str) -> dict:
    """GET /api/v1/policies/active/ — current active policy as canonical dict."""
    return _request(base_url, api_key, "GET", "/api/v1/policies/active/")


def policy_list(base_url: str, api_key: str) -> dict:
    """GET /api/v1/policies/ — all this client's versions, newest first."""
    return _request(base_url, api_key, "GET", "/api/v1/policies/")


def policy_check(
    base_url: str,
    api_key: str,
    agent_id: str,
    action: str,
    amount: float | None = None,
    merchant: str = "",
    description: str = "",
    context: str = "",
    extra: dict | None = None,
) -> dict:
    """POST /api/v1/policies/check/ — dry-run an action. No Transaction is persisted."""
    body = {
        "agent_id": agent_id,
        "action": action,
        "amount": amount,
        "merchant": merchant,
        "description": description,
        "context": context,
    }
    if extra:
        for k, v in extra.items():
            if k not in body or body[k] in (None, ""):
                body[k] = v
    return _request(base_url, api_key, "POST", "/api/v1/policies/check/", body)


def policy_activate(base_url: str, api_key: str, policy_id: str) -> dict:
    """POST /api/v1/policies/<id>/activate/ — roll back to / activate a specific version."""
    return _request(base_url, api_key, "POST", f"/api/v1/policies/{policy_id}/activate/")
