"""
Tests for veto_cli.api low-level helpers — verify_key + _request status passthrough.

Covers regressions for two bugs found 2026-04-29:

  1. verify_key returned False for valid keys because _request raises
     VetoAPIError on HTTP 400, and verify_key swallowed all exceptions
     instead of distinguishing "key authenticated, body bad" (400) from
     "key invalid" (401/403).

  2. _request used to swallow ANY response with a "status" field on non-2xx.
     Tightened to only accept known decision statuses so unrelated server
     errors that happen to include a "status" key don't return as success.
"""

import json
import unittest
import urllib.error
from io import BytesIO
from unittest.mock import patch

from veto_cli import api as api_module


def _make_http_error(code: int, body: dict | str) -> urllib.error.HTTPError:
    """Build an HTTPError that urlopen would raise, with a JSON body."""
    if isinstance(body, dict):
        body_bytes = json.dumps(body).encode()
    else:
        body_bytes = body.encode() if isinstance(body, str) else body
    return urllib.error.HTTPError(
        url="https://example.test/api/v1/authorize/",
        code=code,
        msg=f"HTTP {code}",
        hdrs=None,
        fp=BytesIO(body_bytes),
    )


class VerifyKeyTest(unittest.TestCase):
    """The verify_key probe must distinguish 'key valid, body bad' (400) from 'key invalid' (401/403)."""

    @patch.object(api_module, "_request")
    def test_400_means_key_valid(self, mock_request):
        mock_request.side_effect = api_module.VetoAPIError(
            "agent_id and action are required.", status_code=400
        )
        self.assertTrue(api_module.verify_key("https://example.test", "veto_test_xxx"))

    @patch.object(api_module, "_request")
    def test_401_means_key_invalid(self, mock_request):
        mock_request.side_effect = api_module.VetoAPIError(
            "Invalid API key.", status_code=401
        )
        self.assertFalse(api_module.verify_key("https://example.test", "veto_bad_key"))

    @patch.object(api_module, "_request")
    def test_403_means_key_invalid(self, mock_request):
        mock_request.side_effect = api_module.VetoAPIError(
            "Forbidden.", status_code=403
        )
        self.assertFalse(api_module.verify_key("https://example.test", "veto_bad_key"))

    @patch.object(api_module, "_request")
    def test_500_means_server_problem_not_valid_key(self, mock_request):
        """5xx is treated as unreachable/unverified, not as a valid key."""
        mock_request.side_effect = api_module.VetoAPIError(
            "Internal Server Error.", status_code=500
        )
        self.assertFalse(api_module.verify_key("https://example.test", "veto_test_xxx"))

    @patch.object(api_module, "_request")
    def test_network_failure_returns_false(self, mock_request):
        mock_request.side_effect = api_module.VetoAPIError("Connection failed: timeout")
        self.assertFalse(api_module.verify_key("https://example.test", "veto_test_xxx"))

    @patch.object(api_module, "_request")
    def test_2xx_also_means_valid_defensively(self, mock_request):
        """Defensive: if server ever changed to return 200 instead of 400, still treat as valid."""
        mock_request.return_value = {"status": "ok"}
        self.assertTrue(api_module.verify_key("https://example.test", "veto_test_xxx"))


class RequestStatusPassthroughTest(unittest.TestCase):
    """_request should pass through ONLY known decision statuses on non-2xx — not any 'status' key."""

    @patch("veto_cli.api.urllib.request.urlopen")
    def test_403_with_denied_status_returns_payload(self, mock_urlopen):
        """A real denied tx (403 + {'status': 'denied'}) should come back as data, not an exception."""
        mock_urlopen.side_effect = _make_http_error(
            403, {"status": "denied", "transaction_id": "abc", "reason": "AMOUNT_CAP_EXCEEDED"}
        )
        r = api_module._request(
            "https://example.test", "veto_test_xxx", "POST", "/api/v1/authorize/", {"x": 1}
        )
        self.assertEqual(r["status"], "denied")
        self.assertEqual(r["transaction_id"], "abc")

    @patch("veto_cli.api.urllib.request.urlopen")
    def test_400_with_unknown_status_field_raises(self, mock_urlopen):
        """An error with a misleading 'status' field but a value we don't recognize must NOT pass through."""
        mock_urlopen.side_effect = _make_http_error(
            400, {"status": "weird_unknown_value", "error": "something went wrong"}
        )
        with self.assertRaises(api_module.VetoAPIError) as cm:
            api_module._request(
                "https://example.test", "veto_test_xxx", "POST", "/api/v1/authorize/", {}
            )
        self.assertEqual(cm.exception.status_code, 400)

    @patch("veto_cli.api.urllib.request.urlopen")
    def test_400_without_status_raises(self, mock_urlopen):
        """The 'verify_key' empty-body probe path: 400 + {'error': '...'} (no status field) → raises."""
        mock_urlopen.side_effect = _make_http_error(
            400, {"error": "agent_id and action are required."}
        )
        with self.assertRaises(api_module.VetoAPIError) as cm:
            api_module._request(
                "https://example.test", "veto_test_xxx", "POST", "/api/v1/authorize/", {}
            )
        self.assertEqual(cm.exception.status_code, 400)

    @patch("veto_cli.api.urllib.request.urlopen")
    def test_200_executed_status_returns_payload(self, mock_urlopen):
        """200 with status=executed (Mode 2 happy path) returns normally via the urlopen path."""
        # urlopen success path doesn't go through HTTPError handling — just JSON parse.
        class _Resp:
            def __enter__(self): return self
            def __exit__(self, *a): pass
            def read(self): return json.dumps({"status": "executed", "result": {}}).encode()
        mock_urlopen.return_value = _Resp()

        r = api_module._request(
            "https://example.test", "veto_test_xxx", "POST", "/api/v1/authorize/", {}
        )
        self.assertEqual(r["status"], "executed")


if __name__ == "__main__":
    unittest.main()
