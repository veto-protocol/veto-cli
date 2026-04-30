# Veto CLI

> Authorization for AI agent payments — multi-dimensional YAML policy + Ed25519-signed decision receipts + offline verification. Composes with Stripe MPP, x402, AP2, Verifiable Intent.

Veto is the **policy + signed-evidence layer** for agents that take real actions across rails (x402, MPP, on-chain). Your agent calls `veto authorize` before each action, and the action is approved, denied, or escalated based on a YAML policy you author. Every decision ships with a cryptographically-signed receipt anyone can verify offline.

## Install

The one-liner (curl) drops a self-contained venv at `~/.veto`:

```bash
curl -fsSL https://veto-ai.com/install.sh | bash
```

Or via Python:

```bash
pip install veto-cli      # or: pipx install veto-cli
```

Python 3.9+. Pulls in PyYAML (policy authoring) and `cryptography` (offline receipt verification).

## Quickstart — three commands

```bash
# 1. Install
pip install veto-cli

# 2. Register an account from the terminal (no website, no form)
veto register --email me@example.com --preset x402-micropay
# → ✓ Welcome to Veto. API key + default agent saved to ~/.veto/config.json

# 3. Ask Veto whether an action is allowed
veto authorize --amount 0.05 --merchant api.openai.com --action payment
# → APPROVED / DENIED / ESCALATED. Exit code 0/1/2/3.
```

Every authorize call produces a **signed Ed25519 receipt**. Verify any receipt offline:

```bash
veto authorize --amount 0.05 --merchant api.openai.com --action payment --json | jq -r .receipt | veto verify -
# → ✓ VERIFIED — Ed25519 / 0.1.1
#     decision:         APPROVE
#     decision_layer:   operator_policy
#     policy:           x402 Micropayments v1
#     policy_hash:      53aa6184…
#     transaction_id:   …
```

The verifier fetches the public key from `veto-ai.com/.well-known/jwks.json` (cached locally) and validates the signature without contacting Veto's runtime. Tamper-evident, replay-deterministic, anyone-auditable.

## Five policy presets to start from

`veto register` applies a policy preset so your agent has sensible limits from the first authorize call. Pick one with `--preset`:

| Preset | For | Defaults |
|---|---|---|
| `personal` *(default)* | General-purpose agent | $500/tx, $2k/day, blocks gambling/mixers/adult |
| `inference` | AI API calls | $5/tx, allowlists Anthropic/OpenAI/Replicate/etc. |
| `x402-micropay` | x402 testing | $1/tx, Base chain only, auto-approve <$0.10 |
| `ad-spend` | Meta/Google ads | $1k/tx, escalate >$1k |
| `dev` | Dogfooding/testing | $500/tx, no merchant restrictions |

## Customizing your policy — full lifecycle

When the preset isn't enough, author your own:

```bash
# Export a preset as a starting point
veto policy export inference > my-policy.yaml

# Edit the YAML — any text editor
$EDITOR my-policy.yaml

# Push it to Veto. Auto-versioned + auto-active. Old version deactivated.
veto policy push my-policy.yaml
# → ✓ Policy v2 pushed — now active

# See your active policy as YAML
veto policy show

# Dry-run an action without recording a transaction
veto policy check '{"action":"payment","amount":50,"merchant":"amazon.com"}'
# → ✗ WOULD DENY — risk 1.00, dry-run
#     reason_codes: AMOUNT_CAP_EXCEEDED, MERCHANT_NOT_ALLOWLISTED

# List all your versions, newest first, with relative timestamps
veto policy list

# Roll back to a prior version (instant)
veto policy activate <prior-policy-id>
```

Every push creates a new versioned row. Receipts cite the exact `policy_id`, `version_number`, and `policy_hash` that was active at decision time — so an auditor in 12 months can prove which exact policy contents governed any past decision.

## All commands

| Command | What it does |
|---|---|
| `veto register` | CLI-native signup. Creates account + default agent + preset policy. |
| `veto authorize` | Ask Veto whether an action is allowed. Headline command. |
| `veto verify` | Verify a Veto receipt offline against the issuer's JWKS endpoint. |
| `veto policy export/push/show/list/check/activate` | Author and manage versioned YAML policies. |
| `veto init` | Auto-detect MCP clients on your machine (Claude Desktop, Cursor, Zed, Continue) and configure them to use Veto's MCP server. |
| `veto status [agent_id]` | Show agent reputation tier + recent decision history. |
| `veto list` / `uninstall` | List / remove Veto from MCP client configs. |
| `veto mcp` | Run the Veto MCP server in stdio mode (used internally by MCP clients). |

## What Veto evaluates on every authorize call

8-step pipeline:

1. **Pre-checks** — agent suspended? kill switch? amount sane?
2. **Policy enforcement** — per-tx / daily / monthly caps; merchant + address + chain + token allowlists/blocklists. Allowlist violations are hard deny at any amount.
3. **Prompt injection detection** — 40+ regex patterns over the agent's stated context.
4. **Merchant fraud screening** — known-fraud DB, typosquat detection, suspicious TLDs, hyphen-heavy domains.
5. **Intent verification** — Claude Sonnet (or keyword fallback) checks whether the action matches the agent's mission.
6. **Anomaly detection** — amount spikes (>3× 30-day avg), velocity bursts, merchant-diversity anomalies.
7. **LLM final verdict** — Claude reviews aggregated signals.
8. **Reputation weighting** — elite agents get more leeway, risky agents stricter scrutiny.

Output: `approve` | `deny` | `escalate` plus a `risk_score` (0–1) and structured `reason_codes` (`AMOUNT_CAP_EXCEEDED`, `MERCHANT_NOT_ALLOWLISTED`, `KNOWN_FRAUD_MERCHANT`, etc.). Receipt signs all of it.

## v1 — the if-statement is the enforcement

Wire `veto.authorize()` in front of every agent action and have your agent treat the verdict as ground truth: approve → execute, deny → halt, escalate → wait for a human. **Two lines of cooperation, infinite cryptographic auditability.**

```python
verdict = veto.authorize(action)
if verdict.decision == "approve":
    execute(action)
elif verdict.decision == "escalate":
    notify_human(verdict)
# deny → drop the action, keep the receipt
```

The if-statement is your enforcement point. The receipt is your audit trail. Same operating model as Stripe Radar — your code asks, the engine answers, your code obeys — well-suited to the threat model that matters most: bugs, hallucinations, runaway loops, accidental over-spend.

## v2 — enforcement moves to the rail

In v2, the cooperation step disappears. The rails themselves require a Veto signature to settle, so a non-cooperative agent literally can't broadcast the transaction. **Same policy, same receipt format, same JWKS endpoint — different enforcement surface.** v1 operators carry forward without changes; the receipt format already reserves a `mandate_ref` field for forward compatibility.

Mechanism specifics land closer to ship.

## Configuration

State at `~/.veto/config.json` (mode `0600`): API key, default agent ID, base URL. No transaction data stored locally.

Default backend: `https://veto-ai.com`. Override with `--base-url` on any command (or via `VETO_BASE_URL` env var).

## Links

- **Source (this CLI):** https://github.com/veto-protocol/veto-cli
- **Open policy schema (APPS):** https://github.com/veto-protocol/x402-policy-schema
- **Veto's own published policies:** https://github.com/veto-protocol/veto-policies
- **Public JWKS for receipt verification:** https://veto-ai.com/.well-known/jwks.json

## License

Elastic License v2 (ELv2). See [LICENSE](LICENSE). Copyright Investech Global LLC. You may use, modify, and embed Veto freely. You may not host Veto as a managed service to third parties or strip the licensing notices.
