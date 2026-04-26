# Veto CLI

> One-command setup for the Veto authorization layer — protect every payment your AI agent makes.

Veto is the policy and approval layer for AI agents that take real actions: x402 payments, Stripe Issuing transactions, on-chain transfers. The Veto CLI auto-configures Veto for any MCP-compatible client (Claude Desktop, Claude Code, Cursor, Zed, Continue) so your agent calls Veto before every transaction — and the transaction is allowed, denied, or escalated for human approval based on policies you define.

## Install

```bash
pip install veto-cli
```

Requires Python 3.9+. No third-party dependencies — stdlib only.

## Quickstart

```bash
# 1. Sign up at https://veto-ai.com to get an API key.
# 2. Auto-configure your MCP client:
veto init --api-key veto_test_xxxxxxxxxxxx

# 3. Verify the integration:
veto test
```

`veto init` detects which MCP clients you have installed (Claude Desktop, Cursor, etc.) and writes the Veto MCP server into their config. Restart the client and your agent now routes every payment through Veto.

## Commands

| Command | What it does |
|---|---|
| `veto init` | Auto-detect MCP clients on your machine and add Veto to each one's config |
| `veto status [agent_id]` | Show your agent's current reputation tier and recent decision history |
| `veto test [agent_id]` | Fire a synthetic test transaction to confirm the integration works |
| `veto list` | List all agents linked to your Veto account |
| `veto uninstall` | Remove Veto from MCP client configs (does not delete your account) |
| `veto mcp` | Run the Veto MCP server in foreground (for debugging) |

## What Veto evaluates on every authorize call

Each transaction passes through an 8-step pipeline before approval:

1. **Pre-checks** — agent suspended? amount sane?
2. **Policy enforcement** — per-tx limit, daily/monthly caps, merchant allowlist/blocklist
3. **Prompt injection detection** — 40 regex patterns over the action description
4. **Merchant fraud screening** — known-fraud database, typosquatting (SequenceMatcher), suspicious TLDs
5. **Intent verification** — does the action match the agent's stated purpose?
6. **Anomaly detection** — amount spike (>3× rolling avg), velocity, merchant diversity
7. **LLM final verdict** — Claude Sonnet reviews the case
8. **Reputation weighting** — agent trust tier modulates final risk score

Output: `approve` | `deny` | `escalate` (with risk score 0.0–1.0 and a human-readable reason).

## Configuration

The CLI stores state in `~/.veto/config.json` (mode `0o600`). It contains your API key and known agent IDs. No transaction data is stored locally.

By default the CLI talks to `https://veto-ai.com`. To point at a self-hosted Veto:

```bash
veto init --api-key XXX --base-url https://veto.your-company.com
```

## Links

- **Sign up:** https://veto-ai.com
- **Docs:** https://veto-ai.com/docs
- **Discord:** https://discord.gg/veto-ai
- **GitHub:** https://github.com/veto-protocol

## License

MIT. See [LICENSE](LICENSE).
