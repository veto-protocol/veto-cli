"""
Client-side verifier for Veto signed decision receipts.

The receipt is a JWS compact string (header.payload.signature) signed with
Ed25519. To verify, fetch the public key from the issuer's JWKS endpoint at
`<base_url>/.well-known/jwks.json`, find the key matching the `kid` in the
receipt header, and check the signature.

Used by:
  - `veto verify <receipt>` CLI command
  - Anyone who wants offline verification without trusting Veto's runtime

Stdlib + `cryptography` (which is already a transitive dep of most Python
environments and the canonical Ed25519 library).
"""

from __future__ import annotations

import base64
import json
import os
import time
import urllib.error
import urllib.request

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.exceptions import InvalidSignature


# Local cache of JWKS responses keyed by base URL.
# Public keys are not secret — 0644 is fine. TTL is 1 hour (matches JWKS Cache-Control).
JWKS_CACHE_PATH = os.path.expanduser("~/.veto/jwks_cache.json")
JWKS_CACHE_TTL_SECS = 3600


class ReceiptError(Exception):
    """Base for all receipt verification failures."""


class MalformedReceipt(ReceiptError):
    """Receipt couldn't be parsed (wrong segment count, bad base64, etc)."""


class InvalidReceipt(ReceiptError):
    """Receipt parsed but signature is invalid OR key/algorithm mismatch."""


class KeyFetchError(ReceiptError):
    """JWKS endpoint unreachable or key with the cited kid not found."""


def _b64url_decode(data: str) -> bytes:
    pad = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + pad)


# ---------------------------------------------------------------------------
# JWKS fetch + cache
# ---------------------------------------------------------------------------

def _read_cache() -> dict:
    if not os.path.exists(JWKS_CACHE_PATH):
        return {}
    try:
        with open(JWKS_CACHE_PATH) as f:
            return json.load(f)
    except Exception:
        return {}


def _write_cache(cache: dict) -> None:
    os.makedirs(os.path.dirname(JWKS_CACHE_PATH), exist_ok=True)
    tmp = JWKS_CACHE_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(cache, f, indent=2)
    os.replace(tmp, JWKS_CACHE_PATH)


def fetch_jwks(base_url: str, *, no_cache: bool = False, timeout: int = 10) -> dict:
    """Return the JWKS document for `base_url`. Caches for ~1 hour."""
    base_url = base_url.rstrip("/")
    now = int(time.time())

    cache = _read_cache() if not no_cache else {}
    entry = cache.get(base_url)
    if entry and (now - int(entry.get("fetched_at", 0)) < JWKS_CACHE_TTL_SECS):
        return entry["jwks"]

    url = f"{base_url}/.well-known/jwks.json"
    req = urllib.request.Request(url, headers={"User-Agent": "veto-cli-verifier"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            jwks = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        raise KeyFetchError(f"JWKS fetch returned HTTP {e.code} from {url}")
    except urllib.error.URLError as e:
        raise KeyFetchError(f"JWKS fetch failed: {e.reason}")
    except (json.JSONDecodeError, ValueError) as e:
        raise KeyFetchError(f"JWKS body is not valid JSON: {e}")

    if not isinstance(jwks, dict) or "keys" not in jwks:
        raise KeyFetchError("JWKS response missing 'keys' array")

    cache[base_url] = {"fetched_at": now, "jwks": jwks}
    try:
        _write_cache(cache)
    except OSError:
        pass  # cache write failures should not fail verification
    return jwks


def _public_key_for_kid(jwks: dict, kid: str) -> Ed25519PublicKey:
    """Pick the Ed25519 key matching `kid` out of a JWKS document."""
    for key in jwks.get("keys", []):
        if key.get("kid") != kid:
            continue
        if key.get("kty") != "OKP" or key.get("crv") != "Ed25519":
            raise KeyFetchError(
                f"Key {kid} is not Ed25519 (kty={key.get('kty')}, crv={key.get('crv')})"
            )
        x = key.get("x")
        if not x:
            raise KeyFetchError(f"Key {kid} has no 'x' (public key bytes)")
        try:
            return Ed25519PublicKey.from_public_bytes(_b64url_decode(x))
        except Exception as e:
            raise KeyFetchError(f"Key {kid} could not be loaded: {e}")
    raise KeyFetchError(f"No JWKS key matches kid={kid!r}")


# ---------------------------------------------------------------------------
# Receipt verification
# ---------------------------------------------------------------------------

def parse_receipt_unsafe(receipt: str) -> tuple[dict, dict, bytes, bytes]:
    """
    Decode a JWS compact receipt WITHOUT verifying. Returns (header, payload,
    signing_input_bytes, signature_bytes). Used by callers that want to
    inspect before verifying — but never trust the payload until verify_receipt
    has run.
    """
    if not isinstance(receipt, str):
        raise MalformedReceipt("Receipt must be a string")
    parts = receipt.strip().split(".")
    if len(parts) != 3:
        raise MalformedReceipt(f"Expected 3 JWS segments, got {len(parts)}")
    header_b64, payload_b64, sig_b64 = parts
    try:
        header = json.loads(_b64url_decode(header_b64).decode())
        payload = json.loads(_b64url_decode(payload_b64).decode())
        signature = _b64url_decode(sig_b64)
    except Exception as e:
        raise MalformedReceipt(f"Receipt segment decode failed: {e}")
    signing_input = f"{header_b64}.{payload_b64}".encode("ascii")
    return header, payload, signing_input, signature


def verify_receipt(
    receipt: str, base_url: str, *, no_cache: bool = False
) -> dict:
    """
    Verify `receipt` against the JWKS at `base_url`. Returns the decoded payload.

    Raises:
      MalformedReceipt — couldn't parse the JWS structure
      KeyFetchError   — JWKS unreachable, or no key matches the receipt's kid
      InvalidReceipt  — signature didn't verify, or alg mismatch
    """
    header, payload, signing_input, sig = parse_receipt_unsafe(receipt)

    alg = header.get("alg")
    if alg != "EdDSA":
        raise InvalidReceipt(f"Unsupported alg: {alg!r}, expected EdDSA")
    kid = header.get("kid")
    if not kid:
        raise InvalidReceipt("Receipt header missing 'kid'")

    jwks = fetch_jwks(base_url, no_cache=no_cache)
    public_key = _public_key_for_kid(jwks, kid)

    try:
        public_key.verify(sig, signing_input)
    except InvalidSignature:
        raise InvalidReceipt("Signature did not verify against the JWKS public key.")

    return payload
