"""
Tests for `veto verify` CLI command + the receipts verifier module.

Strategy: generate a fresh Ed25519 keypair in setUp, build a real JWS-compact
receipt signed with that keypair, mock fetch_jwks() to return the public half,
and assert the CLI verifies successfully end-to-end.

Run from `cli/` with: `python -m unittest discover tests`
"""

import base64
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from unittest.mock import patch

try:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives import serialization
    _HAS_CRYPTO = True
except ImportError:
    _HAS_CRYPTO = False

from veto_cli import main
from veto_cli import receipts as rcpt


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _make_keypair():
    sk = Ed25519PrivateKey.generate()
    pub_bytes = sk.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return sk, pub_bytes


def _sign(sk, payload: dict, kid: str = "veto-receipts-v1") -> str:
    """Build a real JWS compact receipt — same format as the server emits."""
    header = {"alg": "EdDSA", "typ": "JWT", "kid": kid}
    h_b64 = _b64url(json.dumps(header, sort_keys=True, separators=(",", ":")).encode())
    p_b64 = _b64url(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode())
    signing_input = f"{h_b64}.{p_b64}".encode("ascii")
    sig = sk.sign(signing_input)
    return f"{h_b64}.{p_b64}.{_b64url(sig)}"


def _jwks_doc(pub_bytes: bytes, kid: str = "veto-receipts-v1") -> dict:
    return {
        "keys": [
            {
                "kty": "OKP",
                "crv": "Ed25519",
                "kid": kid,
                "alg": "EdDSA",
                "use": "sig",
                "x": _b64url(pub_bytes),
            }
        ]
    }


def _run_cli(argv, stdin: str = "", state: dict | None = None):
    if state is None:
        state = {"api_key": "veto_test_fake", "base_url": "https://example.test"}

    old_argv = sys.argv
    old_stdin = sys.stdin
    sys.argv = ["veto"] + list(argv)
    sys.stdin = io.StringIO(stdin)

    out_buf, err_buf = io.StringIO(), io.StringIO()
    try:
        with redirect_stdout(out_buf), redirect_stderr(err_buf):
            with patch("veto_cli.main._load_state", return_value=state):
                try:
                    main.main()
                    code = 0
                except SystemExit as e:
                    code = e.code if isinstance(e.code, int) else 1
        return code, out_buf.getvalue(), err_buf.getvalue()
    finally:
        sys.argv = old_argv
        sys.stdin = old_stdin


# ---------------------------------------------------------------------------
# Module-level verifier tests
# ---------------------------------------------------------------------------

@unittest.skipUnless(_HAS_CRYPTO, "cryptography lib required for veto verify")
class VerifierModuleTest(unittest.TestCase):

    def setUp(self):
        self.sk, self.pub_bytes = _make_keypair()
        # Use a temp cache file so tests don't pollute ~/.veto/jwks_cache.json
        fd, self.cache_path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        os.unlink(self.cache_path)  # remove so first call writes fresh
        self.cache_patch = patch.object(rcpt, "JWKS_CACHE_PATH", self.cache_path)
        self.cache_patch.start()

    def tearDown(self):
        self.cache_patch.stop()
        if os.path.exists(self.cache_path):
            os.unlink(self.cache_path)

    def test_verify_real_receipt_with_mocked_jwks(self):
        receipt = _sign(self.sk, {"iss": "veto", "sub": "tx-1", "decision": "approve"})
        with patch.object(rcpt, "fetch_jwks", return_value=_jwks_doc(self.pub_bytes)):
            payload = rcpt.verify_receipt(receipt, "https://example.test")
        self.assertEqual(payload["sub"], "tx-1")
        self.assertEqual(payload["decision"], "approve")

    def test_invalid_signature_raises_invalid_receipt(self):
        receipt = _sign(self.sk, {"iss": "veto", "sub": "tx-2"})
        # Wrong key in the JWKS — verification should fail
        _, wrong_pub = _make_keypair()
        with patch.object(rcpt, "fetch_jwks", return_value=_jwks_doc(wrong_pub)):
            with self.assertRaises(rcpt.InvalidReceipt):
                rcpt.verify_receipt(receipt, "https://example.test")

    def test_unknown_kid_raises_key_fetch_error(self):
        receipt = _sign(self.sk, {"sub": "x"}, kid="some-other-kid")
        with patch.object(rcpt, "fetch_jwks", return_value=_jwks_doc(self.pub_bytes)):
            with self.assertRaises(rcpt.KeyFetchError):
                rcpt.verify_receipt(receipt, "https://example.test")

    def test_malformed_receipt_raises(self):
        with patch.object(rcpt, "fetch_jwks", return_value=_jwks_doc(self.pub_bytes)):
            for bad in ["", "abc", "abc.def", "a.b.c.d", "not.valid.base64!!!"]:
                with self.assertRaises(rcpt.MalformedReceipt):
                    rcpt.verify_receipt(bad, "https://example.test")

    def test_jwks_cache_avoids_second_network_call(self):
        receipt = _sign(self.sk, {"sub": "tx-3"})
        jwks = _jwks_doc(self.pub_bytes)
        # Patch the urllib call inside fetch_jwks rather than fetch_jwks itself,
        # so the cache layer actually runs.
        with patch("veto_cli.receipts.urllib.request.urlopen") as mock_open:
            class _Resp:
                def __enter__(self): return self
                def __exit__(self, *a): pass
                def read(self): return json.dumps(jwks).encode()
            mock_open.return_value = _Resp()

            # First call: fetches network
            rcpt.verify_receipt(receipt, "https://example.test")
            # Second call: should hit cache, urlopen NOT called again
            rcpt.verify_receipt(receipt, "https://example.test")
            self.assertEqual(mock_open.call_count, 1)


# ---------------------------------------------------------------------------
# CLI command tests
# ---------------------------------------------------------------------------

@unittest.skipUnless(_HAS_CRYPTO, "cryptography lib required for veto verify")
class VerifyCliTest(unittest.TestCase):

    def setUp(self):
        self.sk, self.pub_bytes = _make_keypair()
        fd, self.cache_path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        os.unlink(self.cache_path)
        self.cache_patch = patch.object(rcpt, "JWKS_CACHE_PATH", self.cache_path)
        self.cache_patch.start()

    def tearDown(self):
        self.cache_patch.stop()
        if os.path.exists(self.cache_path):
            os.unlink(self.cache_path)

    def _good_receipt(self, **payload_overrides) -> str:
        payload = {
            "iss": "veto",
            "sub": "tx-cli-1",
            "iat": 1745000000,
            "decision": "deny",
            "risk_score": 0.95,
            "reason_codes": ["AMOUNT_CAP_EXCEEDED"],
            "engine_version": "0.1.0",
            "input_fingerprint": "abc123" * 10,
            "agent_id": "agent-1",
            "client_id": "client-1",
            "policy": {"id": "pol-1", "version_number": 3, "name": "Custom"},
        }
        payload.update(payload_overrides)
        return _sign(self.sk, payload)

    def test_verify_valid_receipt_exit_0_and_json_payload(self):
        receipt = self._good_receipt()
        with patch.object(rcpt, "fetch_jwks", return_value=_jwks_doc(self.pub_bytes)):
            code, out, _ = _run_cli(["verify", receipt, "--json"])
        self.assertEqual(code, 0)
        body = json.loads(out)
        self.assertTrue(body["valid"])
        self.assertEqual(body["payload"]["decision"], "deny")
        self.assertEqual(body["payload"]["policy"]["version_number"], 3)

    def test_verify_human_readable_shows_decision_and_policy(self):
        receipt = self._good_receipt()
        with patch.object(rcpt, "fetch_jwks", return_value=_jwks_doc(self.pub_bytes)):
            code, out, _ = _run_cli(["verify", receipt])
        self.assertEqual(code, 0)
        self.assertIn("VERIFIED", out)
        self.assertIn("DENY", out)
        self.assertIn("AMOUNT_CAP_EXCEEDED", out)
        self.assertIn("Custom v3", out)

    def test_verify_stdin_input(self):
        receipt = self._good_receipt(decision="approve", reason_codes=[])
        with patch.object(rcpt, "fetch_jwks", return_value=_jwks_doc(self.pub_bytes)):
            code, out, _ = _run_cli(["verify", "-", "--json"], stdin=receipt)
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["payload"]["decision"], "approve")

    def test_verify_invalid_signature_exit_1(self):
        receipt = self._good_receipt()
        _, wrong_pub = _make_keypair()
        with patch.object(rcpt, "fetch_jwks", return_value=_jwks_doc(wrong_pub)):
            code, _out, err = _run_cli(["verify", receipt])
        self.assertEqual(code, 1)
        self.assertIn("INVALID RECEIPT", err)

    def test_verify_invalid_signature_json_includes_untrusted_payload(self):
        """Even when sig fails, --json surfaces what was claimed (clearly marked untrusted)."""
        receipt = self._good_receipt(sub="tx-evil")
        _, wrong_pub = _make_keypair()
        with patch.object(rcpt, "fetch_jwks", return_value=_jwks_doc(wrong_pub)):
            code, out, _ = _run_cli(["verify", receipt, "--json"])
        self.assertEqual(code, 1)
        body = json.loads(out)
        self.assertFalse(body["valid"])
        self.assertEqual(body["untrusted_payload"]["sub"], "tx-evil")

    def test_verify_malformed_receipt_exit_2(self):
        with patch.object(rcpt, "fetch_jwks", return_value=_jwks_doc(self.pub_bytes)):
            code, _out, err = _run_cli(["verify", "garbage-not-jws"])
        self.assertEqual(code, 2)
        self.assertIn("Malformed", err)

    def test_verify_jwks_fetch_failure_exit_2(self):
        receipt = self._good_receipt()
        with patch.object(
            rcpt, "fetch_jwks",
            side_effect=rcpt.KeyFetchError("Connection refused"),
        ):
            code, _out, err = _run_cli(["verify", receipt])
        self.assertEqual(code, 2)
        self.assertIn("JWKS fetch failed", err)

    def test_verify_unknown_kid_exit_2(self):
        receipt = _sign(self.sk, {"sub": "x"}, kid="not-our-kid")
        with patch.object(rcpt, "fetch_jwks", return_value=_jwks_doc(self.pub_bytes)):
            code, _out, err = _run_cli(["verify", receipt])
        self.assertEqual(code, 2)
        self.assertIn("JWKS fetch failed", err)

    def test_verify_quiet_silent_on_invalid(self):
        receipt = self._good_receipt()
        _, wrong_pub = _make_keypair()
        with patch.object(rcpt, "fetch_jwks", return_value=_jwks_doc(wrong_pub)):
            code, out, err = _run_cli(["verify", receipt, "--quiet"])
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertEqual(err, "")

    def test_verify_empty_input_exit_3(self):
        code, _out, err = _run_cli(["verify", "-"], stdin="")
        self.assertEqual(code, 3)
        self.assertIn("empty", err)


if __name__ == "__main__":
    unittest.main()
