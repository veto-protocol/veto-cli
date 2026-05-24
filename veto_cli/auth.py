"""Magic-link auth for the Python `veto` CLI.

Mirrors the npm `@veto-protocol/cli` package's login flow exactly:

  1. CLI asks for email + generates a `dc_…` device_code.
  2. POST /api/v1/auth/email/start/ {email, device_code}
  3. Open the user's webmail (best-effort, gmail/outlook/etc. by domain).
  4. Poll /api/v1/auth/cli/poll/ every 2s until the user clicks the magic
     link in their inbox.
  5. Save the returned api_key + agent_id + client_id + email to
     ~/.veto/config.json.

stdlib only (urllib + ssl) — keeps `pip install veto-cli` dependency-free
and consistent with the rest of veto_cli.api.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass


_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")

POLL_INTERVAL_S = 2.0
POLL_TIMEOUT_S = 15 * 60  # 15 min — matches MagicLinkToken.TOKEN_TTL server-side

_SSL_CTX = ssl.create_default_context()


# ── Webmail open-by-domain (matches the npm CLI's mapping + extras) ──

_WEBMAIL = {
    "gmail.com":      "https://mail.google.com/mail/u/0/#inbox",
    "googlemail.com": "https://mail.google.com/mail/u/0/#inbox",
    "outlook.com":    "https://outlook.live.com/mail/",
    "hotmail.com":    "https://outlook.live.com/mail/",
    "live.com":       "https://outlook.live.com/mail/",
    "msn.com":        "https://outlook.live.com/mail/",
    "yahoo.com":      "https://mail.yahoo.com",
    "ymail.com":      "https://mail.yahoo.com",
    "icloud.com":     "https://www.icloud.com/mail",
    "me.com":         "https://www.icloud.com/mail",
    "mac.com":        "https://www.icloud.com/mail",
    "protonmail.com": "https://mail.proton.me",
    "proton.me":      "https://mail.proton.me",
    "pm.me":          "https://mail.proton.me",
    "fastmail.com":   "https://app.fastmail.com",
    "hey.com":        "https://app.hey.com",
}


def is_valid_email(s: str) -> bool:
    return bool(_EMAIL_RE.match(s.strip())) and len(s.strip()) <= 254


def generate_device_code() -> str:
    """`dc_` + 24 random url-safe bytes. Matches the backend regex
    ^[A-Za-z0-9_-]{8,64}$ and the convention used by @veto-protocol/cli."""
    return "dc_" + secrets.token_urlsafe(24)


def open_inbox_for(email: str) -> str | None:
    """Open the user's webmail provider. Returns the URL opened, or None.

    Best-effort: silently no-ops on headless systems (SSH, CI, etc.).
    """
    try:
        domain = email.split("@", 1)[1].strip().lower()
    except IndexError:
        return None
    url = _WEBMAIL.get(domain) or f"https://{domain}"
    try:
        if sys.platform == "darwin":
            subprocess.run(["open", url], check=False, stderr=subprocess.DEVNULL)
        elif sys.platform == "win32":
            os.startfile(url)  # type: ignore[attr-defined]
        else:
            subprocess.run(["xdg-open", url], check=False, stderr=subprocess.DEVNULL)
    except Exception:
        return None
    return url


# ── HTTP helpers (stdlib urllib) ──

class AuthError(Exception):
    """Server returned an error response (non-2xx) during auth."""


def _post_json(url: str, body: dict, timeout: float = 15.0) -> tuple[int, dict]:
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "veto-cli-python",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_SSL_CTX) as resp:
            payload = json.loads(resp.read().decode("utf-8") or "{}")
            return resp.status, payload
    except urllib.error.HTTPError as e:
        try:
            payload = json.loads(e.read().decode("utf-8") or "{}")
        except Exception:
            payload = {}
        return e.code, payload


def start(*, api_base: str, email: str, device_code: str) -> int:
    """Trigger the magic-link email. Returns the server's `expires_in` seconds."""
    url = f"{api_base.rstrip('/')}/auth/email/start/"
    status, payload = _post_json(url, {"email": email, "device_code": device_code})
    if status >= 400:
        raise AuthError(payload.get("error") or f"HTTP {status}")
    return int(payload.get("expires_in", 900))


@dataclass
class PollReady:
    api_key: str
    agent_id: str
    client_id: str


def poll_once(*, api_base: str, device_code: str) -> PollReady | None:
    """One poll attempt. None = still pending. Raises AuthError on terminal failures."""
    url = f"{api_base.rstrip('/')}/auth/cli/poll/"
    status, payload = _post_json(url, {"device_code": device_code})

    if status == 410:
        raise AuthError("Magic link expired. Run `veto login` again.")
    if status == 404:
        raise AuthError("device_code not found. Run `veto login` again.")
    if status >= 400:
        raise AuthError(payload.get("error") or f"HTTP {status}")

    if payload.get("status") == "ready":
        return PollReady(
            api_key=payload["api_key"],
            agent_id=payload["agent_id"],
            client_id=payload["client_id"],
        )
    return None  # still pending


def poll_until_ready(
    *,
    api_base: str,
    device_code: str,
    interval_s: float = POLL_INTERVAL_S,
    timeout_s: float = POLL_TIMEOUT_S,
    on_tick=None,
) -> PollReady:
    start_t = time.monotonic()
    while True:
        elapsed = int(time.monotonic() - start_t)
        if elapsed >= timeout_s:
            raise TimeoutError(f"Timed out after {timeout_s:.0f}s waiting for magic link.")
        ready = poll_once(api_base=api_base, device_code=device_code)
        if ready is not None:
            return ready
        if on_tick is not None:
            on_tick(elapsed)
        time.sleep(interval_s)
