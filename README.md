# Veto CLI

> **Any agent. Any payment rail. Safe transactions.**
> The safety layer for the agent economy. Decides every spend at the moment of decision, signs every answer, and (when you opt in) refuses unauthorized spends at the chain level.

Veto sits between your AI agents and the money. Every spend gets checked against your rules in real time, every decision ships with a cryptographically-signed receipt anyone can verify offline, and an optional smart wallet contract enforces the policy directly on-chain.

- **Source (this CLI)** — https://github.com/veto-protocol/veto-cli
- **Live contract on Base Sepolia** — [`0xCBbb…92c5`](https://sepolia.basescan.org/address/0xCBbbC4b924AF40D29f135c3a88b6F650d55d92c5)
- **Verify a receipt offline** — [`/.well-known/jwks.json`](https://veto-ai.com/.well-known/jwks.json)

---

## Install

```bash
pip install veto-cli
```

Python 3.9+. Pulls in PyYAML (policy authoring), `cryptography` (offline receipt verification), and `eth_account` (the smart-wallet deploy path).

## Quickstart

```bash
# 1. Register a Veto account from the terminal
veto register --email me@example.com --preset inference

# 2. Ask Veto whether an action is allowed
veto authorize --amount 0.05 --merchant api.openai.com --action payment
# → APPROVED · risk 0.18 · signed receipt issued
```

Every authorize call returns a **signed Ed25519 receipt**. Verify offline:

```bash
veto authorize --amount 0.05 --merchant api.openai.com --action payment --json \
  | jq -r .receipt | veto verify -
# → ✓ VERIFIED — Ed25519 / engine 0.1.1
#     decision:        APPROVE
#     policy:          Inference v1
#     policy_hash:     53aa6184…
```

The verifier fetches the public key from `veto-ai.com/.well-known/jwks.json` (cached locally) and validates the signature without contacting Veto's runtime. Tamper-evident, replay-deterministic, anyone-auditable.

---

## Scaffold a governed agent in 60 seconds

```bash
veto agent init --name my-agent --dir ./my-agent
```

This generates a runnable TypeScript project with:

- A local viem wallet (private key in `.env` — you own it, no third-party vendor)
- An LLM brain you choose during setup (Anthropic Claude, OpenAI, or xAI Grok)
- Tool wrappers for `send_eth`, `send_usdc`, `get_balance`, `get_address`, `policy_update`
- Every governed call routed through Veto's `authorize` first — denies halt the agent before broadcast
- Optional **on-chain hard-stop** via `WALLET_CONTRACT` env var

The full 4-step interactive lifecycle:

```bash
veto agent init      # scaffold the project + generate keys
veto agent fund      # auto-open faucet, poll for funds, confirm
veto agent deploy    # deploy a VetoGuardedAccount smart wallet (testnet)
veto agent status    # snapshot of agent + wallet + contract + policy
```

When `WALLET_CONTRACT` is set, `send_*` calls go through `executeWithMandate(...)` on a deployed smart wallet that refuses spends without a fresh, in-scope, Veto-signed mandate. The chain refuses, not just our SDK.

---

## What Veto checks before money moves

Eight stages. Every signal that fires is recorded in a signed receipt — so *"why was this denied?"* always has a structured answer in `engine_trace`.

| # | Stage | What it catches |
|---|---|---|
| 1 | **Your rules** | Caps, daily limits, allow- and blocklists for merchants, chains, tokens, addresses |
| 2 | **Prompt-injection** | "Ignore previous instructions" patterns and friends |
| 3 | **Misspelled merchants** | `api-anthropc.com`, `аpple.com` (Cyrillic homoglyph) — for *every* user, allowlist or not |
| 4 | **Crypto safety** | OFAC sanctioned addresses (live feed), address-poisoning attacks, known-drainer contracts |
| 5 | **Intent** | Does the spend match the agent's mission and recent context? Crypto-aware. |
| 6 | **Anomaly** | Velocity bursts, merchant-diversity spikes, off-pattern amounts |
| 7 | **Behavior baseline** | Per-agent rolling stats — distinguishes "trading bot doing 20 tx/min" from "inference agent suddenly doing 20 tx/min" |
| 8 | **Final decision** | Weighted aggregation, fraud floor, human-required floor, signed receipt with full trace |

Output: `approve` / `deny` / `escalate` plus a `risk_score` (0–1), structured `reason_codes`, and the full `engine_trace`. The receipt signs all of it.

---

## On-chain hard-stop (live on Base Sepolia)

A minimal smart wallet (`VetoGuardedAccount`) holds the agent's funds and only releases them on a fresh, in-scope, Veto-signed mandate. Single-use, time-bound, scope-locked. Deployed and proven:

| | |
|---|---|
| **Contract** | [`0xCBbbC4b924AF40D29f135c3a88b6F650d55d92c5`](https://sepolia.basescan.org/address/0xCBbbC4b924AF40D29f135c3a88b6F650d55d92c5) |
| **First execution** | [`0x2f9ec…d2af`](https://sepolia.basescan.org/tx/0x2f9ec691a6f5958bea296c5f630b26d1be1d93667dc3c974671cce0773cad2af) — 0.000001 ETH transferred |
| **Replay rejected** | `MandateAlreadySpent()` selector `0xffa64355` — the chain refused a duplicate |
| **Verifier** | [`@veto/mandate-verifier`](https://github.com/veto-protocol/mandate-verifier) (TS, Node 18+) |

Verification: secp256k1 EIP-712 + `ecrecover` (~3k gas). Domain separator binds `chainId` + `verifyingContract` — no cross-chain or cross-contract replay either. Each mandate carries a single-use `jti` the contract tracks on-chain.

Production audited contracts ship in v2.

---

## Policy authoring — full lifecycle

Five presets to start from (`personal` *(default)*, `inference`, `x402-micropay`, `ad-spend`, `dev`). When the preset isn't enough:

```bash
# Export a preset as a starting point
veto policy export inference > my-policy.yaml

# Edit the YAML
$EDITOR my-policy.yaml

# Push it. Auto-versioned + auto-active. Old version deactivated.
veto policy push my-policy.yaml
# → ✓ Policy v2 pushed — now active

# Dry-run an action without recording a transaction
veto policy check '{"action":"payment","amount":50,"merchant":"amazon.com"}'
# → ✗ WOULD DENY — risk 1.00, dry-run
#     reason_codes: AMOUNT_CAP_EXCEEDED, MERCHANT_NOT_ALLOWLISTED

# Roll back to a prior version (instant)
veto policy activate <prior-policy-id>
```

Every push creates a new versioned row. Receipts cite the exact `policy_id`, `version_number`, and `policy_hash` active at decision time — so an auditor in 12 months can prove which exact policy contents governed any past decision.

The schema is open and MIT-licensed: [github.com/veto-protocol/x402-policy-schema](https://github.com/veto-protocol/x402-policy-schema).

---

## All commands

| Command | What it does |
|---|---|
| `veto register` | CLI-native signup. Creates account + default agent + preset policy. |
| `veto authorize` | Ask Veto whether an action is allowed. Headline command. |
| `veto verify` | Verify a Veto receipt offline against the issuer's JWKS endpoint. |
| `veto policy export/push/show/list/check/activate` | Author and manage versioned YAML policies. |
| `veto agent init/configure/fund/deploy/status` | Scaffold a runnable Veto-governed agent project, fund it, deploy its smart wallet, see live state. |
| `veto init` | Auto-detect MCP clients (Claude Desktop, Cursor, Zed, Continue) and configure them. |
| `veto status [agent_id]` | Show agent reputation tier + recent decision history. |
| `veto mcp` | Run the Veto MCP server in stdio mode (used by MCP clients). |

---

## Composes with any rail

Veto sits one layer above the rails — your stack picks the rail, Veto governs the spend. It works with:

- **x402** — Coinbase's HTTP 402 micropayment protocol (`veto.authorize` runs before the agent signs the x402 payload)
- **AP2** — Google's Agent Payments Protocol (receipts reserve `mandate_ref` for AP2 intent mandates)
- **Stripe MPP** — when shipped (Stripe Issuing webhook integration on the roadmap)
- **Direct EVM/Solana** — `crypto_transfer` with chain + address + token + amount-in-base-units

The policy, the receipt, and the engine are the same regardless of rail. You don't switch products to switch rails.

---

## v0.6 today — what's live, what's next

**Live in v0.6:**
- Multi-dim YAML policy with versioning + rollback
- Ed25519-signed decision receipts (JWS-compact) with public JWKS
- Engine improvements: canonical typosquat, address-poisoning, OFAC live feed, per-agent behavioral baselines, structured `engine_trace`
- `veto agent init` scaffolds local-viem agents in 60 seconds
- Stub `VetoGuardedAccount` deployed and proven on Base Sepolia
- `@veto/mandate-verifier` TS package — offline mandate verification
- MCP integration for Claude Desktop, Cursor, Zed, Continue

**Roadmap:**
- Audited `VetoGuardedAccount` + ERC-4337 module variant on mainnet (Base, Ethereum, Optimism, Arbitrum)
- Safe Guard Module for multisigs / treasuries
- Stripe Issuing webhook for fiat hard-stop (no MSB licensing — customer's existing Stripe account)
- Dynamic.xyz / Privy embedded-wallet templates
- Hosted MCP endpoint
- Telegram + email approval bots for `escalate` decisions

What we deliberately won't build: custodial signing (would make Veto a money transmitter), hosted agent runtime (we're not a runtime competitor), proprietary policy formats (the schema stays open).

---

## Configuration

State at `~/.veto/config.json` (mode `0600`): API key, default agent ID, base URL. No transaction data stored locally.

Default backend: `https://veto-ai.com`. Override with `--base-url` on any command (or via `VETO_BASE_URL` env var).

---

## Links

- **Source (this CLI)** — https://github.com/veto-protocol/veto-cli
- **Live smart wallet on Base Sepolia** — https://sepolia.basescan.org/address/0xCBbbC4b924AF40D29f135c3a88b6F650d55d92c5
- **Open policy schema (APPS)** — https://github.com/veto-protocol/x402-policy-schema
- **Mandate verifier (TS)** — https://github.com/veto-protocol/mandate-verifier
- **Smart wallet contract source** — https://github.com/veto-protocol/contracts
- **Veto's own published policies** — https://github.com/veto-protocol/veto-policies
- **Public JWKS for receipt verification** — https://veto-ai.com/.well-known/jwks.json
- **Documentation** — https://github.com/veto-protocol/docs

## License

Elastic License v2 (ELv2). See [LICENSE](LICENSE) for the full text and copyright. You may use, modify, and embed Veto freely. You may not host Veto as a managed service to third parties or strip the licensing notices.
