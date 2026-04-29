"""
Tests for `veto policy` CLI commands (export, push, show, list, check, activate).

Stubs `veto_cli.api.policy_*` so tests never hit the network. PyYAML is required
to run these (added as a CLI dep in pyproject.toml; tests skip if absent so a
bare-stdlib environment doesn't break the rest of the test suite).

Run from `cli/` with: `python -m unittest discover tests`
"""

import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from unittest.mock import patch

try:
    import yaml  # noqa: F401
    _HAS_YAML = True
except ImportError:
    _HAS_YAML = False

from veto_cli import main
from veto_cli import api as api_module


def _run_cli(argv, stdin: str = "", state: dict | None = None):
    if state is None:
        state = {
            "api_key": "veto_test_fake",
            "base_url": "https://example.test",
            "default_agent": "00000000-0000-0000-0000-000000000001",
        }

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


_PRESET_RESPONSE = {
    "version": 1,
    "name": "AI Inference",
    "scope": "agent",
    "max_per_transaction": "5.00",
    "daily_limit": "50.00",
    "monthly_limit": "500.00",
    "auto_approve_below": "1.00",
    "require_human_approval_above": "5.00",
    "crypto_daily_limit_usd": None,
    "merchant_allowlist": ["api.anthropic.com", "api.openai.com"],
    "merchant_blocklist": [],
    "category_allowlist": [],
    "chain_allowlist": [],
    "token_allowlist": [],
    "address_allowlist": [],
    "address_blocklist": [],
    "_meta": {"exported_from_preset": "inference", "default_mission": "..."},
}

_ACTIVE_RESPONSE = dict(_PRESET_RESPONSE)
_ACTIVE_RESPONSE["_meta"] = {
    "policy_id": "11111111-1111-1111-1111-111111111111",
    "version_number": 3,
    "is_active": True,
    "created_at": "2026-04-27T10:00:00+00:00",
}

_PUSH_RESPONSE = {
    "policy_id": "22222222-2222-2222-2222-222222222222",
    "version_number": 4,
    "is_active": True,
    "name": "Custom",
    "scope": "agent",
    "agent_id": "00000000-0000-0000-0000-000000000001",
    "created_at": "2026-04-27T11:00:00+00:00",
}


@unittest.skipUnless(_HAS_YAML, "PyYAML required for veto policy commands")
class TestPolicyExport(unittest.TestCase):

    @patch.object(api_module, "policy_export_preset", return_value=_PRESET_RESPONSE)
    def test_export_prints_valid_yaml_with_expected_fields(self, mock_fetch):
        code, out, _ = _run_cli(["policy", "export", "inference"])
        self.assertEqual(code, 0)
        # Reparse to verify YAML validity + content
        parsed = yaml.safe_load(out)
        self.assertEqual(parsed["name"], "AI Inference")
        self.assertEqual(parsed["max_per_transaction"], "5.00")
        self.assertIn("api.anthropic.com", parsed["merchant_allowlist"])
        mock_fetch.assert_called_once()

    @patch.object(
        api_module, "policy_export_preset",
        side_effect=api_module.VetoAPIError("Unknown preset", status_code=404),
    )
    def test_export_404_exits_3(self, _):
        code, _out, err = _run_cli(["policy", "export", "bogus"])
        self.assertEqual(code, 3)
        self.assertIn("Could not fetch preset", err)


@unittest.skipUnless(_HAS_YAML, "PyYAML required for veto policy commands")
class TestPolicyPush(unittest.TestCase):

    def _write_yaml(self, data: dict) -> str:
        fd, path = tempfile.mkstemp(suffix=".yaml")
        os.close(fd)
        with open(path, "w") as f:
            yaml.dump(data, f)
        self.addCleanup(os.unlink, path)
        return path

    @patch.object(api_module, "policy_push", return_value=_PUSH_RESPONSE)
    def test_push_strips_meta_and_sends_payload(self, mock_push):
        path = self._write_yaml(_PRESET_RESPONSE)
        code, out, _ = _run_cli(["policy", "push", path])
        self.assertEqual(code, 0)
        # _meta block must NOT be sent to backend
        sent = mock_push.call_args.args[2]
        self.assertNotIn("_meta", sent)
        self.assertEqual(sent["name"], "AI Inference")
        self.assertIn("v4 pushed", out)

    @patch.object(api_module, "policy_push", return_value=_PUSH_RESPONSE)
    def test_push_strips_meta_round_trip_with_active_policy_meta(self, mock_push):
        """Round-trip safety: someone runs `veto policy show > p.yaml`, edits, then
        `veto policy push p.yaml`. The active-policy _meta block (policy_id,
        version_number, is_active, created_at) is read-only — must never be
        sent back to the server (would create version_number conflicts).
        """
        active_with_meta = {
            "version": 1,
            "name": "Custom",
            "scope": "agent",
            "max_per_transaction": "5.00",
            "daily_limit": "50.00",
            "monthly_limit": "500.00",
            "merchant_allowlist": [],
            "merchant_blocklist": [],
            "_meta": {
                "policy_id": "11111111-1111-1111-1111-111111111111",
                "version_number": 7,
                "is_active": True,
                "created_at": "2026-04-29T10:00:00+00:00",
            },
        }
        path = self._write_yaml(active_with_meta)
        code, _out, _ = _run_cli(["policy", "push", path])
        self.assertEqual(code, 0)
        sent = mock_push.call_args.args[2]
        self.assertNotIn("_meta", sent)
        # And none of the read-only fields leaked into the top level either
        for read_only_field in ("policy_id", "version_number", "is_active", "created_at"):
            self.assertNotIn(read_only_field, sent)

    def test_push_missing_file_exits_3(self):
        code, _out, err = _run_cli(["policy", "push", "/tmp/does-not-exist-12345.yaml"])
        self.assertEqual(code, 3)
        self.assertIn("File not found", err)

    def test_push_invalid_yaml_exits_3(self):
        fd, path = tempfile.mkstemp(suffix=".yaml")
        os.close(fd)
        with open(path, "w") as f:
            f.write("bad: yaml: : [unclosed")
        self.addCleanup(os.unlink, path)
        code, _out, err = _run_cli(["policy", "push", path])
        self.assertEqual(code, 3)
        self.assertIn("YAML parse error", err)

    @patch.object(
        api_module, "policy_push",
        side_effect=api_module.VetoAPIError(
            "daily_limit must be ≥ 0", status_code=400, body={"field": "daily_limit"}
        ),
    )
    def test_push_validation_error_surfaces_field(self, _):
        path = self._write_yaml(_PRESET_RESPONSE)
        code, _out, err = _run_cli(["policy", "push", path])
        self.assertEqual(code, 3)
        self.assertIn("Push failed", err)
        self.assertIn("daily_limit", err)

    def test_push_no_api_key_exits_3(self):
        path = self._write_yaml(_PRESET_RESPONSE)
        code, _out, err = _run_cli(["policy", "push", path], state={})
        self.assertEqual(code, 3)
        self.assertIn("No API key", err)


@unittest.skipUnless(_HAS_YAML, "PyYAML required for veto policy commands")
class TestPolicyShow(unittest.TestCase):

    @patch.object(api_module, "policy_show_active", return_value=_ACTIVE_RESPONSE)
    def test_show_prints_active_as_yaml(self, mock_show):
        code, out, _ = _run_cli(["policy", "show"])
        self.assertEqual(code, 0)
        parsed = yaml.safe_load(out)
        self.assertEqual(parsed["name"], "AI Inference")
        self.assertEqual(parsed["_meta"]["version_number"], 3)
        mock_show.assert_called_once()


class TestPolicyList(unittest.TestCase):

    @patch.object(api_module, "policy_list", return_value={
        "policies": [
            {"policy_id": "p3", "name": "C", "version_number": 3, "is_active": True, "scope": "agent", "agent_id": "a", "created_at": "2026-01-01T00:00:00Z"},
            {"policy_id": "p2", "name": "B", "version_number": 2, "is_active": False, "scope": "agent", "agent_id": "a", "created_at": "2026-01-01T00:00:00Z"},
            {"policy_id": "p1", "name": "A", "version_number": 1, "is_active": False, "scope": "agent", "agent_id": "a", "created_at": "2026-01-01T00:00:00Z"},
        ]
    })
    def test_list_renders_versions_with_active_marker(self, _):
        code, out, _ = _run_cli(["policy", "list"])
        self.assertEqual(code, 0)
        # Active marker (●) is a green bullet for the latest version
        self.assertIn("v3", out)
        self.assertIn("v2", out)
        self.assertIn("v1", out)
        # Names appear in output (newest first)
        v3_idx = out.find("v3")
        v1_idx = out.find("v1")
        self.assertLess(v3_idx, v1_idx)

    @patch.object(api_module, "policy_list", return_value={"policies": []})
    def test_list_empty_shows_hint(self, _):
        code, out, _ = _run_cli(["policy", "list"])
        self.assertEqual(code, 0)
        self.assertIn("No policies yet", out)


class TestPolicyCheck(unittest.TestCase):

    _CHECK_APPROVE = {
        "decision": "approve",
        "risk_score": 0.1,
        "denial_reason": "",
        "reason_codes": [],
        "signals": [],
        "policy": {"policy_id": "p1", "version_number": 2, "name": "Custom"},
        "dry_run": True,
    }

    _CHECK_DENY = {
        "decision": "deny",
        "risk_score": 1.0,
        "denial_reason": "Amount exceeds per-tx limit",
        "reason_codes": ["AMOUNT_CAP_EXCEEDED", "MERCHANT_NOT_ALLOWLISTED"],
        "signals": [{"name": "over_tx_limit", "score": 1.0, "reason": "..."}],
        "policy": {"policy_id": "p1", "version_number": 2, "name": "Custom"},
        "dry_run": True,
    }

    @patch.object(api_module, "policy_check")
    def test_check_approve_prints_would_approve(self, mock_check):
        mock_check.return_value = self._CHECK_APPROVE
        action = json.dumps({"action": "payment", "amount": 5.00, "merchant": "x"})
        code, out, _ = _run_cli(["policy", "check", action])
        self.assertEqual(code, 0)
        self.assertIn("WOULD APPROVE", out)

    @patch.object(api_module, "policy_check")
    def test_check_deny_surfaces_reason_codes(self, mock_check):
        """Regression: CLI now surfaces reason_codes in human output for dry-runs,
        matching the shape of `veto authorize --json`."""
        mock_check.return_value = self._CHECK_DENY
        action = json.dumps({"action": "payment", "amount": 50000, "merchant": "amazon.com"})
        code, out, _ = _run_cli(["policy", "check", action])
        self.assertEqual(code, 0)
        self.assertIn("WOULD DENY", out)
        # Both canonical reason codes appear in output, not just the prose denial_reason
        self.assertIn("AMOUNT_CAP_EXCEEDED", out)
        self.assertIn("MERCHANT_NOT_ALLOWLISTED", out)

    @patch.object(api_module, "policy_check")
    def test_check_deny_prints_would_deny_with_reason(self, mock_check):
        mock_check.return_value = self._CHECK_DENY
        action = json.dumps({"action": "payment", "amount": 50000, "merchant": "x"})
        code, out, _ = _run_cli(["policy", "check", action])
        self.assertEqual(code, 0)
        self.assertIn("WOULD DENY", out)
        self.assertIn("Amount exceeds per-tx limit", out)

    @patch.object(api_module, "policy_check")
    def test_check_json_mode_passes_response_through(self, mock_check):
        mock_check.return_value = self._CHECK_APPROVE
        action = json.dumps({"action": "payment", "amount": 5})
        code, out, _ = _run_cli(["policy", "check", action, "--json"])
        self.assertEqual(code, 0)
        parsed = json.loads(out)
        self.assertEqual(parsed["decision"], "approve")
        self.assertTrue(parsed["dry_run"])

    def test_check_invalid_json_exits_3(self):
        code, _out, err = _run_cli(["policy", "check", "{not valid json"])
        self.assertEqual(code, 3)
        self.assertIn("Invalid JSON", err)

    def test_check_no_agent_id_no_default_exits_3(self):
        code, _out, err = _run_cli(
            ["policy", "check", json.dumps({"action": "payment", "amount": 1})],
            state={"api_key": "veto_test_fake", "base_url": "https://example.test"},
        )
        self.assertEqual(code, 3)
        self.assertIn("agent_id required", err)


class TestPolicyActivate(unittest.TestCase):

    @patch.object(api_module, "policy_activate", return_value={
        "policy_id": "abc",
        "version_number": 1,
        "name": "V1",
        "is_active": True,
        "activated_at": "2026-04-27T12:00:00Z",
    })
    def test_activate_prints_confirmation(self, mock_activate):
        code, out, _ = _run_cli(["policy", "activate", "abc-123"])
        self.assertEqual(code, 0)
        self.assertIn("Activated v1", out)
        mock_activate.assert_called_once_with("https://example.test", "veto_test_fake", "abc-123")

    @patch.object(
        api_module, "policy_activate",
        side_effect=api_module.VetoAPIError("Policy version not found", status_code=404),
    )
    def test_activate_unknown_id_exits_3(self, _):
        code, _out, err = _run_cli(["policy", "activate", "00000000-0000-0000-0000-000000000999"])
        self.assertEqual(code, 3)
        self.assertIn("Activate failed", err)


if __name__ == "__main__":
    unittest.main()
