"""
Tests for `veto authorize` CLI command.

Covers:
  - Input validation (missing args, bad stdin) → exit 3
  - Response handling (approved/denied/escalated/error) → exit 0/1/2/3
  - Output modes: human-readable (default), --json, --quiet
  - Stdin parsing + extra-field pass-through

These tests stub `veto_cli.api.authorize` so they never hit the network.
Run from `cli/` with: `python -m unittest discover tests`
"""

import io
import json
import sys
import unittest
from contextlib import redirect_stdout, redirect_stderr
from unittest.mock import patch

from veto_cli import main
from veto_cli import api as api_module


def _run_cli(argv, stdin: str = "", state: dict | None = None):
    """
    Invoke the CLI with the given argv. Returns (exit_code, stdout, stderr).

    `state` overrides what _load_state() returns (useful for fake API key).
    `stdin` is a string fed to sys.stdin if the command reads it.
    """
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


# ── Validation tests (no API call) ──

class TestAuthorizeValidation(unittest.TestCase):
    def test_missing_all_required_args_exits_3(self):
        code, out, err = _run_cli(["authorize"], state={})
        self.assertEqual(code, 3)
        self.assertIn("Missing required input", err)
        self.assertEqual(out, "")  # no stdout pollution

    def test_missing_api_key_exits_3(self):
        # Provide all CLI args but no saved state and no --api-key flag
        code, out, err = _run_cli(
            ["authorize", "--agent", "abc", "--amount", "0.05", "--merchant", "x", "--action", "payment"],
            state={},
        )
        self.assertEqual(code, 3)
        self.assertIn("API key", err)

    def test_missing_required_args_json_mode_outputs_valid_json(self):
        code, out, err = _run_cli(["authorize", "--json"], state={})
        self.assertEqual(code, 3)
        # JSON output to stdout, not stderr
        payload = json.loads(out)
        self.assertEqual(payload["status"], "error")
        self.assertIn("missing", payload["error"].lower())

    def test_invalid_stdin_json_exits_3(self):
        code, out, err = _run_cli(["authorize", "-"], stdin="not json")
        self.assertEqual(code, 3)
        self.assertIn("Invalid JSON", err)

    def test_invalid_stdin_json_in_json_mode_outputs_json_error(self):
        code, out, err = _run_cli(["authorize", "-", "--json"], stdin="[1,2,3]")
        self.assertEqual(code, 3)
        payload = json.loads(out)
        self.assertEqual(payload["status"], "error")
        self.assertIn("stdin", payload["error"].lower())


# ── Response handling tests (with mocked API) ──

class TestAuthorizeResponseHandling(unittest.TestCase):
    BASE_ARGS = [
        "authorize",
        "--agent", "agent-uuid",
        "--amount", "0.05",
        "--merchant", "api.test.com",
        "--action", "payment",
    ]

    def _run_with_response(self, response: dict, extra_args: list = None):
        with patch.object(api_module, "authorize", return_value=response) as mock_call:
            code, out, err = _run_cli(self.BASE_ARGS + (extra_args or []))
        return code, out, err, mock_call

    def test_approved_exits_0(self):
        code, out, err, _ = self._run_with_response({
            "transaction_id": "tx-1",
            "status": "approved",
            "risk_score": 0.12,
            "decision_only": True,
        })
        self.assertEqual(code, 0)
        self.assertIn("APPROVED", out)
        self.assertIn("tx-1", out)

    def test_executed_exits_0(self):
        # Status "executed" (Mode 2 path) should also exit 0
        code, out, err, _ = self._run_with_response({
            "transaction_id": "tx-2",
            "status": "executed",
            "risk_score": 0.05,
        })
        self.assertEqual(code, 0)

    def test_denied_exits_1(self):
        code, out, err, _ = self._run_with_response({
            "transaction_id": "tx-3",
            "status": "denied",
            "risk_score": 0.85,
            "reason": "AMOUNT_CAP_EXCEEDED",
        })
        self.assertEqual(code, 1)
        self.assertIn("DENIED", out)
        self.assertIn("AMOUNT_CAP_EXCEEDED", out)

    def test_escalated_exits_2(self):
        code, out, err, _ = self._run_with_response({
            "transaction_id": "tx-4",
            "status": "escalated",
            "risk_score": 0.55,
            "reason": "Human approval required.",
        })
        self.assertEqual(code, 2)
        self.assertIn("ESCALATED", out)

    def test_unexpected_status_exits_3(self):
        code, out, err, _ = self._run_with_response({
            "transaction_id": "tx-5",
            "status": "weird-future-status",
        })
        self.assertEqual(code, 3)

    def test_api_error_exits_3(self):
        with patch.object(
            api_module, "authorize",
            side_effect=api_module.VetoAPIError("network down"),
        ):
            code, out, err = _run_cli(self.BASE_ARGS)
        self.assertEqual(code, 3)
        self.assertIn("Request failed", err)

    def test_api_error_json_mode_outputs_json(self):
        with patch.object(
            api_module, "authorize",
            side_effect=api_module.VetoAPIError("network down", status_code=503),
        ):
            code, out, err = _run_cli(self.BASE_ARGS + ["--json"])
        self.assertEqual(code, 3)
        payload = json.loads(out)
        self.assertEqual(payload["status"], "error")
        self.assertEqual(payload["status_code"], 503)
        self.assertIn("network down", payload["error"])

    def test_json_mode_passes_response_through(self):
        response = {
            "transaction_id": "tx-6",
            "status": "approved",
            "risk_score": 0.1,
            "decision_only": True,
            "extra_field": {"nested": "value"},
        }
        code, out, err, _ = self._run_with_response(response, extra_args=["--json"])
        self.assertEqual(code, 0)
        # JSON mode emits exactly the response, nothing else on stdout
        parsed = json.loads(out)
        self.assertEqual(parsed, response)

    def test_quiet_mode_silent_on_approved(self):
        code, out, err, _ = self._run_with_response(
            {"transaction_id": "tx-7", "status": "approved", "risk_score": 0.1},
            extra_args=["--quiet"],
        )
        self.assertEqual(code, 0)
        self.assertEqual(out, "")
        self.assertEqual(err, "")

    def test_quiet_mode_silent_on_denied(self):
        code, out, err, _ = self._run_with_response(
            {"transaction_id": "tx-8", "status": "denied", "risk_score": 0.9, "reason": "X"},
            extra_args=["--quiet"],
        )
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertEqual(err, "")


# ── Stdin tests ──

class TestAuthorizeStdin(unittest.TestCase):
    def test_stdin_json_parsed_correctly(self):
        stdin_payload = {
            "agent_id": "agent-from-stdin",
            "amount": 0.10,
            "merchant": "stdin.test.com",
            "action": "payment",
            "description": "via stdin",
        }
        seen_kwargs = {}

        def fake_authorize(base_url, api_key, agent_id, **kwargs):
            seen_kwargs["agent_id"] = agent_id
            seen_kwargs.update(kwargs)
            return {"transaction_id": "tx-stdin", "status": "approved", "risk_score": 0.1}

        with patch.object(api_module, "authorize", side_effect=fake_authorize):
            code, out, err = _run_cli(
                ["authorize", "-"],
                stdin=json.dumps(stdin_payload),
            )

        self.assertEqual(code, 0)
        self.assertEqual(seen_kwargs["agent_id"], "agent-from-stdin")
        self.assertEqual(seen_kwargs["merchant"], "stdin.test.com")
        self.assertEqual(seen_kwargs["action"], "payment")
        self.assertEqual(seen_kwargs["description"], "via stdin")

    def test_stdin_extra_fields_passed_through_extra(self):
        # Fields outside the standard set (chain, to_address, etc.) should land in `extra`.
        stdin_payload = {
            "agent_id": "agent-extra",
            "amount": 0.001,
            "merchant": "0xdeadbeef",
            "action": "crypto_transfer",
            "chain": "base",
            "to_address": "0xabc",
            "token_contract": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
            "amount_wei": "1000",
        }
        seen_kwargs = {}

        def fake_authorize(base_url, api_key, agent_id, **kwargs):
            seen_kwargs.update(kwargs)
            return {"transaction_id": "tx-crypto", "status": "approved", "risk_score": 0.1}

        with patch.object(api_module, "authorize", side_effect=fake_authorize):
            code, _, _ = _run_cli(["authorize", "-"], stdin=json.dumps(stdin_payload))

        self.assertEqual(code, 0)
        self.assertIn("extra", seen_kwargs)
        self.assertEqual(seen_kwargs["extra"]["chain"], "base")
        self.assertEqual(seen_kwargs["extra"]["to_address"], "0xabc")
        self.assertEqual(seen_kwargs["extra"]["amount_wei"], "1000")

    def test_stdin_agent_alias_accepted(self):
        # Accept "agent" as alias for "agent_id" in stdin payloads.
        stdin_payload = {
            "agent": "alias-agent",  # not "agent_id"
            "amount": 0.05,
            "merchant": "test",
            "action": "payment",
        }

        def fake_authorize(base_url, api_key, agent_id, **kwargs):
            return {"transaction_id": "tx", "status": "approved", "risk_score": 0.1}

        with patch.object(api_module, "authorize", side_effect=fake_authorize) as mock_call:
            code, _, _ = _run_cli(["authorize", "-"], stdin=json.dumps(stdin_payload))

        self.assertEqual(code, 0)
        # api.authorize should have been called with agent_id="alias-agent"
        self.assertEqual(mock_call.call_args.args[2], "alias-agent")


# ── decision_only is always set by the CLI ──

class TestAuthorizeDecisionOnly(unittest.TestCase):
    def test_cli_always_sends_decision_only_true(self):
        """Mode 1 is the CLI's contract — never trigger executor side effects."""
        seen_kwargs = {}

        def fake_authorize(base_url, api_key, agent_id, **kwargs):
            seen_kwargs.update(kwargs)
            return {"transaction_id": "tx", "status": "approved", "risk_score": 0.1}

        with patch.object(api_module, "authorize", side_effect=fake_authorize):
            code, _, _ = _run_cli([
                "authorize",
                "--agent", "abc",
                "--amount", "0.05",
                "--merchant", "x",
                "--action", "payment",
            ])

        self.assertEqual(code, 0)
        self.assertTrue(seen_kwargs["decision_only"])


if __name__ == "__main__":
    unittest.main()
