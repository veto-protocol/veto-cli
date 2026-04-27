"""
Tests for `veto mcp` server — the JSON-RPC-over-stdio MCP shim that proxies
tool calls to Veto's HTTP API.

Coverage:
  - TOOLS list shape (all 6 tools, valid inputSchema for the new ones)
  - handle_tool_call routes each tool to the correct HTTP endpoint + body
  - tools/list and tools/call dispatch via the JSON-RPC loop
  - Unknown tool returns an error result (not a JSON-RPC error)

Run from `cli/` with: `python -m unittest discover tests`
"""

import io
import json
import sys
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from veto_cli import mcp_server


_BASE_URL = "https://example.test"
_API_KEY = "veto_test_fake"


# ---------------------------------------------------------------------------
# TOOLS list shape
# ---------------------------------------------------------------------------

class ToolsListShapeTest(unittest.TestCase):

    def test_tools_list_includes_all_six_tools(self):
        names = {t["name"] for t in mcp_server.TOOLS}
        expected = {
            "veto_authorize",
            "veto_crypto_authorize",
            "veto_check_status",
            "veto_reputation",
            "veto_policy_show",
            "veto_policy_check",
        }
        self.assertEqual(names, expected)

    def test_each_tool_has_required_mcp_fields(self):
        for tool in mcp_server.TOOLS:
            self.assertIn("name", tool)
            self.assertIn("description", tool)
            self.assertIn("inputSchema", tool)
            schema = tool["inputSchema"]
            self.assertEqual(schema["type"], "object")
            self.assertIn("properties", schema)
            # required is optional in JSON Schema but MCP clients prefer it
            self.assertIn("required", schema)

    def test_policy_show_takes_no_required_args(self):
        tool = next(t for t in mcp_server.TOOLS if t["name"] == "veto_policy_show")
        self.assertEqual(tool["inputSchema"]["required"], [])

    def test_policy_check_requires_agent_id_and_action(self):
        tool = next(t for t in mcp_server.TOOLS if t["name"] == "veto_policy_check")
        self.assertEqual(set(tool["inputSchema"]["required"]), {"agent_id", "action"})
        # Action is constrained to the same enum as authorize
        self.assertEqual(
            set(tool["inputSchema"]["properties"]["action"]["enum"]),
            {"payment", "crypto_transfer", "tool_execution"},
        )


# ---------------------------------------------------------------------------
# handle_tool_call — routing
# ---------------------------------------------------------------------------

class HandleToolCallRoutingTest(unittest.TestCase):

    def _call(self, name, args):
        with patch.object(mcp_server, "_http") as mock_http:
            mock_http.return_value = {"ok": True}
            mcp_server.handle_tool_call(name, args, _BASE_URL, _API_KEY)
            return mock_http

    def test_policy_show_routes_to_get_active(self):
        mock = self._call("veto_policy_show", {})
        mock.assert_called_once_with(_BASE_URL, _API_KEY, "GET", "/api/v1/policies/active/")

    def test_policy_check_routes_to_post_check_with_full_body(self):
        mock = self._call("veto_policy_check", {
            "agent_id": "agent-uuid",
            "action": "payment",
            "amount": 5.50,
            "merchant": "api.anthropic.com",
            "description": "test",
            "context": "user asked",
        })
        mock.assert_called_once()
        args = mock.call_args.args
        self.assertEqual(args[0], _BASE_URL)
        self.assertEqual(args[1], _API_KEY)
        self.assertEqual(args[2], "POST")
        self.assertEqual(args[3], "/api/v1/policies/check/")
        body = mock.call_args.args[4]
        self.assertEqual(body["agent_id"], "agent-uuid")
        self.assertEqual(body["action"], "payment")
        self.assertEqual(body["amount"], 5.50)
        self.assertEqual(body["merchant"], "api.anthropic.com")

    def test_policy_check_passes_through_crypto_fields_when_present(self):
        mock = self._call("veto_policy_check", {
            "agent_id": "agent-uuid",
            "action": "crypto_transfer",
            "chain": "base",
            "to_address": "0xabc",
            "token_contract": "0xtok",
            "amount_wei": "1000000",
        })
        body = mock.call_args.args[4]
        self.assertEqual(body["chain"], "base")
        self.assertEqual(body["to_address"], "0xabc")
        self.assertEqual(body["token_contract"], "0xtok")
        self.assertEqual(body["amount_wei"], "1000000")

    def test_policy_check_omits_empty_crypto_fields(self):
        """Passthrough is gated on presence — empty values shouldn't pollute the body."""
        mock = self._call("veto_policy_check", {
            "agent_id": "agent-uuid",
            "action": "payment",
        })
        body = mock.call_args.args[4]
        for k in ("chain", "to_address", "token_contract", "amount_wei"):
            self.assertNotIn(k, body)

    def test_authorize_still_routes_to_authorize_endpoint(self):
        """Regression: existing tools must keep working after we added the new ones."""
        mock = self._call("veto_authorize", {
            "agent_id": "a",
            "action": "payment",
            "description": "d",
            "context": "c",
        })
        mock.assert_called_once_with(
            _BASE_URL, _API_KEY, "POST", "/api/v1/authorize/", unittest.mock.ANY
        )

    def test_unknown_tool_returns_error_dict(self):
        # Doesn't even touch the network
        with patch.object(mcp_server, "_http") as mock_http:
            r = mcp_server.handle_tool_call("veto_does_not_exist", {}, _BASE_URL, _API_KEY)
        self.assertIn("error", r)
        self.assertIn("Unknown tool", r["error"])
        mock_http.assert_not_called()


# ---------------------------------------------------------------------------
# JSON-RPC dispatch loop
# ---------------------------------------------------------------------------

class MCPRpcLoopTest(unittest.TestCase):
    """Drive the MCPServer.run() loop with stdin lines and inspect stdout."""

    def _drive(self, messages: list[dict]) -> list[dict]:
        """Feed JSON-RPC messages to the server, return responses."""
        stdin_text = "\n".join(json.dumps(m) for m in messages) + "\n"
        out_buf = io.StringIO()
        old_stdin = sys.stdin
        sys.stdin = io.StringIO(stdin_text)
        try:
            with redirect_stdout(out_buf):
                mcp_server.MCPServer(base_url=_BASE_URL, api_key=_API_KEY).run()
        finally:
            sys.stdin = old_stdin
        responses = []
        for line in out_buf.getvalue().splitlines():
            if line.strip():
                responses.append(json.loads(line))
        return responses

    def test_initialize_returns_capabilities_and_server_info(self):
        responses = self._drive([{"jsonrpc": "2.0", "id": 1, "method": "initialize"}])
        self.assertEqual(len(responses), 1)
        r = responses[0]
        self.assertEqual(r["id"], 1)
        self.assertIn("protocolVersion", r["result"])
        self.assertEqual(r["result"]["serverInfo"]["name"], "veto")

    def test_tools_list_returns_all_tools(self):
        responses = self._drive([{"jsonrpc": "2.0", "id": 2, "method": "tools/list"}])
        tools = responses[0]["result"]["tools"]
        names = {t["name"] for t in tools}
        self.assertIn("veto_policy_show", names)
        self.assertIn("veto_policy_check", names)
        self.assertEqual(len(tools), 6)

    def test_tools_call_for_policy_show_invokes_handler(self):
        with patch.object(mcp_server, "handle_tool_call", return_value={"name": "active"}) as mock:
            responses = self._drive([{
                "jsonrpc": "2.0", "id": 3, "method": "tools/call",
                "params": {"name": "veto_policy_show", "arguments": {}},
            }])
        mock.assert_called_once_with("veto_policy_show", {}, _BASE_URL, _API_KEY)
        # Result is wrapped as MCP content[0].text holding the JSON
        result = responses[0]["result"]
        self.assertIn("content", result)
        text = result["content"][0]["text"]
        self.assertEqual(json.loads(text), {"name": "active"})
        self.assertFalse(result["isError"])

    def test_unknown_method_returns_jsonrpc_error(self):
        responses = self._drive([{"jsonrpc": "2.0", "id": 4, "method": "totally/unknown"}])
        self.assertIn("error", responses[0])
        self.assertEqual(responses[0]["error"]["code"], -32601)


if __name__ == "__main__":
    unittest.main()
