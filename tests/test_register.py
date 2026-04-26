"""
Tests for `veto register` CLI command.

Covers:
  - Successful registration → API key + default_agent saved to ~/.veto/config.json
  - Backend errors (409 duplicate, 400 invalid email/preset) → exit 3 with helpful message
  - Network errors → exit 3
  - --yes skips overwrite confirmation when existing config exists
  - cmd_authorize falls back to default_agent from saved config when --agent omitted

These stub `veto_cli.api.register` and `veto_cli.api.authorize` so they never hit the network,
and stub `_save_state` so they never touch the real ~/.veto/config.json.
"""

import io
import json
import sys
import unittest
from contextlib import redirect_stdout, redirect_stderr
from unittest.mock import patch

from veto_cli import main
from veto_cli import api as api_module


def _run_cli(argv, stdin: str = "", state: dict | None = None, captured_save: dict | None = None):
    """Run the CLI; intercepts _save_state into `captured_save` so tests can assert what was saved."""
    if state is None:
        state = {}
    if captured_save is None:
        captured_save = {}

    old_argv = sys.argv
    old_stdin = sys.stdin
    sys.argv = ["veto"] + list(argv)
    sys.stdin = io.StringIO(stdin)

    out_buf, err_buf = io.StringIO(), io.StringIO()

    def fake_save(payload):
        captured_save.clear()
        captured_save.update(payload)

    try:
        with redirect_stdout(out_buf), redirect_stderr(err_buf):
            with patch("veto_cli.main._load_state", return_value=state):
                with patch("veto_cli.main._save_state", side_effect=fake_save):
                    try:
                        main.main()
                        code = 0
                    except SystemExit as e:
                        code = e.code if isinstance(e.code, int) else 1
        return code, out_buf.getvalue(), err_buf.getvalue(), captured_save
    finally:
        sys.argv = old_argv
        sys.stdin = old_stdin


# ── Successful registration ──

class TestRegisterSuccess(unittest.TestCase):
    def test_register_saves_api_key_and_default_agent(self):
        fake_response = {
            "api_key": "veto_test_abcdef123456",
            "client_id": "client-uuid",
            "agent_id": "agent-uuid-xyz",
            "agent_name": "default-agent",
            "mission": "General-purpose personal assistant agent.",
            "org_name": "alice's Veto",
            "policy": {
                "preset": "personal",
                "name": "Personal",
                "max_per_tx": "500.00",
                "daily_limit": "2000.00",
                "monthly_limit": "25000.00",
                "auto_approve_below": "50.00",
                "require_human_approval_above": "500.00",
                "merchant_blocklist": ["gambling", "casino"],
                "merchant_allowlist": [],
                "chain_allowlist": [],
            },
        }
        captured = {}
        with patch.object(api_module, "register", return_value=fake_response) as mock_call:
            code, out, err, saved = _run_cli(
                ["register", "--email", "alice@example.com"],
                captured_save=captured,
            )

        self.assertEqual(code, 0)
        self.assertIn("Welcome to Veto", out)
        self.assertIn("alice@example.com", out)
        self.assertIn("default-agent", out)
        # Saved state has everything we need for subsequent commands
        self.assertEqual(saved["api_key"], "veto_test_abcdef123456")
        self.assertEqual(saved["default_agent"], "agent-uuid-xyz")
        self.assertIn("base_url", saved)
        # API was called with the right args
        mock_call.assert_called_once()
        kwargs = mock_call.call_args.kwargs
        self.assertEqual(kwargs["email"], "alice@example.com")

    def test_register_passes_preset_and_mission_through(self):
        fake_response = {
            "api_key": "k",
            "client_id": "c",
            "agent_id": "a",
            "agent_name": "test-bot",
            "mission": "Custom mission.",
            "org_name": "Org",
            "policy": {"preset": "dev", "name": "Development", "max_per_tx": "500.00",
                       "daily_limit": "1000.00", "monthly_limit": "5000.00",
                       "auto_approve_below": "10.00", "require_human_approval_above": "200.00",
                       "merchant_allowlist": [], "merchant_blocklist": [], "chain_allowlist": []},
        }
        with patch.object(api_module, "register", return_value=fake_response) as mock_call:
            _run_cli([
                "register",
                "--email", "bob@example.com",
                "--preset", "dev",
                "--mission", "Custom mission.",
                "--agent-name", "test-bot",
            ])
        kwargs = mock_call.call_args.kwargs
        self.assertEqual(kwargs["preset"], "dev")
        self.assertEqual(kwargs["mission"], "Custom mission.")
        self.assertEqual(kwargs["agent_name"], "test-bot")


# ── Errors ──

class TestRegisterErrors(unittest.TestCase):
    def test_duplicate_email_409_exits_3_with_hint(self):
        with patch.object(
            api_module, "register",
            side_effect=api_module.VetoAPIError("Email already registered. ...", status_code=409),
        ):
            code, out, err, _ = _run_cli(["register", "--email", "dup@example.com"])
        self.assertEqual(code, 3)
        self.assertIn("already registered", err)
        self.assertIn("--api-key", err)  # hint about veto init

    def test_invalid_preset_400_exits_3(self):
        with patch.object(
            api_module, "register",
            side_effect=api_module.VetoAPIError("Invalid preset. Allowed: ...", status_code=400),
        ):
            code, out, err, _ = _run_cli(["register", "--email", "x@x.com", "--preset", "nope"])
        self.assertEqual(code, 3)
        self.assertIn("Invalid preset", err)

    def test_network_error_exits_3(self):
        with patch.object(
            api_module, "register",
            side_effect=api_module.VetoAPIError("Connection failed: timed out"),
        ):
            code, out, err, _ = _run_cli(["register", "--email", "x@x.com"])
        self.assertEqual(code, 3)
        self.assertIn("Registration failed", err)


# ── Existing config protection ──

class TestRegisterExistingConfig(unittest.TestCase):
    def test_existing_api_key_with_yes_flag_overwrites(self):
        """`--yes` short-circuits the confirmation prompt."""
        fake_response = {
            "api_key": "veto_test_new",
            "client_id": "c",
            "agent_id": "a-new",
            "agent_name": "default-agent",
            "mission": "x",
            "org_name": "o",
            "policy": {"preset": "personal", "name": "Personal", "max_per_tx": "500.00",
                       "daily_limit": "2000.00", "monthly_limit": "25000.00",
                       "auto_approve_below": "50.00", "require_human_approval_above": "500.00",
                       "merchant_allowlist": [], "merchant_blocklist": [], "chain_allowlist": []},
        }
        captured = {}
        with patch.object(api_module, "register", return_value=fake_response):
            code, out, err, saved = _run_cli(
                ["register", "--email", "x@x.com", "--yes"],
                state={"api_key": "veto_test_old", "default_agent": "old-agent"},
                captured_save=captured,
            )
        self.assertEqual(code, 0)
        self.assertEqual(saved["api_key"], "veto_test_new")  # overwrote


# ── Default agent fallback in cmd_authorize ──

class TestAuthorizeDefaultAgentFallback(unittest.TestCase):
    """After `veto register`, subsequent `veto authorize` should use the saved default_agent."""

    def test_authorize_uses_default_agent_from_state(self):
        seen = {}

        def fake_authorize(base_url, api_key, agent_id, **kwargs):
            seen["agent_id"] = agent_id
            return {"transaction_id": "tx", "status": "approved", "risk_score": 0.1}

        with patch.object(api_module, "authorize", side_effect=fake_authorize):
            code, out, err, _ = _run_cli(
                # NOTE: no --agent flag
                ["authorize", "--amount", "0.05", "--merchant", "x", "--action", "payment"],
                state={"api_key": "k", "default_agent": "saved-agent-uuid"},
            )

        self.assertEqual(code, 0)
        self.assertEqual(seen["agent_id"], "saved-agent-uuid")

    def test_authorize_flag_wins_over_default_agent(self):
        seen = {}

        def fake_authorize(base_url, api_key, agent_id, **kwargs):
            seen["agent_id"] = agent_id
            return {"transaction_id": "tx", "status": "approved", "risk_score": 0.1}

        with patch.object(api_module, "authorize", side_effect=fake_authorize):
            _run_cli(
                ["authorize", "--agent", "explicit", "--amount", "0.05", "--merchant", "x", "--action", "payment"],
                state={"api_key": "k", "default_agent": "saved-fallback"},
            )
        self.assertEqual(seen["agent_id"], "explicit")

    def test_authorize_no_agent_no_default_exits_3(self):
        code, out, err, _ = _run_cli(
            ["authorize", "--amount", "0.05", "--merchant", "x", "--action", "payment"],
            state={"api_key": "k"},  # no default_agent
        )
        self.assertEqual(code, 3)
        self.assertIn("--agent", err)


if __name__ == "__main__":
    unittest.main()
