<div align="center">

<br>

<img src="https://veto-ai.com/veto-logo.png" alt="Veto" width="220">

<br><br>

<h3>The safety layer for AI agents that spend money.</h3>

<p>
  Any agent. Any payment rail. Safe transactions.<br>
  Real-time policy + signed decision receipts + optional on-chain hard-stop.
</p>

<p>
  <a href="https://pypi.org/project/veto-cli/"><img src="https://img.shields.io/pypi/v/veto-cli.svg?style=flat-square&color=06B6D4&label=pypi" alt="PyPI"></a>
  <a href="https://pypi.org/project/veto-cli/"><img src="https://img.shields.io/pypi/dm/veto-cli.svg?style=flat-square&color=10B981&label=downloads" alt="downloads"></a>
  <a href="https://github.com/veto-protocol/veto-cli/stargazers"><img src="https://img.shields.io/github/stars/veto-protocol/veto-cli?style=flat-square&color=FFD700&label=stars" alt="stars"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-ELv2-22d3ee?style=flat-square" alt="license"></a>
  <a href="https://www.python.org/"><img src="https://img.shields.io/badge/Python-%E2%89%A53.9-3776AB?style=flat-square&logo=python&logoColor=white" alt="Python"></a>
  <a href="https://x402.org"><img src="https://img.shields.io/badge/x402-native-10B981?style=flat-square" alt="x402"></a>
  <a href="https://sepolia.basescan.org/address/0xCBbbC4b924AF40D29f135c3a88b6F650d55d92c5"><img src="https://img.shields.io/badge/Base_Sepolia-live-0052FF?style=flat-square&logo=coinbase&logoColor=white" alt="Base Sepolia live"></a>
  <a href="https://veto-ai.com/.well-known/jwks.json"><img src="https://img.shields.io/badge/Ed25519-signed_receipts-22d3ee?style=flat-square" alt="signed receipts"></a>
</p>

<p>
  <a href="#quick-start">Quick&nbsp;start</a> ·
  <a href="#what-veto-checks">Engine</a> ·
  <a href="#on-chain-hard-stop">On-chain</a> ·
  <a href="#scaffold-an-agent">Scaffold</a> ·
  <a href="#the-comparison">Comparison</a> ·
  <a href="#how-it-works">Architecture</a> ·
  <a href="#all-commands">Commands</a> ·
  <a href="#community">Community</a>
</p>

</div>

---

## The pitch in one paragraph

Veto sits between AI agents and the money. Every spend an agent attempts is checked against a YAML policy you author — caps, allowlists, escalation thresholds, on-chain rules — and an 8-stage risk engine that catches typosquats, address-poisoning, sanctioned addresses, prompt injection, and behavioral anomalies. Every decision ships with a cryptographically-signed receipt anyone can verify offline. For agents that need adversarial-grade enforcement, an optional smart wallet contract refuses to release funds without a fresh, in-scope, Veto-signed mandate — **the chain refuses, not just our SDK**. Composes with x402, AP2, Stripe MPP, Verifiable Intent.

Built by [Investech Global LLC](https://veto-ai.com). Elastic License v2. Python + TypeScript scaffolding for agents.

> **Layer 3 — Operational Policy**
>
> The agent-commerce stack has rails (x402, MPP, AP2) and consent (Verifiable Intent, AP2 mandates).
> The layer between agent and rail — *operator-side governance, signed evidence, refusal at the moment of decision* — has been empty.
> Veto is that layer.

---

## Quick start

```bash
# 1. Install — agent-friendly (used by Claude Code skills, MCP plugins, scripts)
curl -fsSL https://veto-ai.com/install.sh | bash

# Or human-friendly (pip)
pip install veto-cli

# 2. Register a Veto account from the terminal — no website, no form
veto register --email me@example.com --preset inference

# 3. Ask Veto whether an action is allowed
veto authorize --amount 0.05 --merchant api.openai.com --action payment
```

Output:

```text
✓ APPROVED — risk 0.18
  reason_codes:    REPUTATION_NEW
  policy:          AI Inference v1
  policy_hash:     53aa6184…
  transaction_id:  e9f1c2a4…
  receipt:         eyJhbGciOiJFZERTQSIs… (Ed25519, verifiable offline)
```

That's it. No SaaS account, no credit card, no MCP setup required. The API key lives in `~/.veto/config.json` (mode `0600`) — only your user can read it.

---

## What Veto checks

Eight stages. Every signal that fires lands in the receipt's `engine_trace` — so *"why was this denied?"* always has a structured answer.

```text
> veto authorize --amount 14500 --merchant api-anthropc.com --action payment

  ✗ DENIED — risk 1.00
    01 your_rules                  ✓ within caps
    02 prompt_injection            ✓ no patterns
    03 misspelled_merchants        ✗ TYPOSQUAT_CANONICAL
                                     api-anthropc.com ↔ api.anthropic.com (94%)
    04 crypto_safety               (n/a — fiat)
    05 intent                      ⚠ INTENT_PARTIAL — mission says "inference", merchant unverified
    06 anomaly                     ✗ AMOUNT_ANOMALY (47× 30-day avg)
    07 behavior_baseline           ✗ AMOUNT_ABOVE_BASELINE_P99
    08 final_decision              ✗ DENY — fraud floor + amount cap
```

| # | Stage | What it catches |
|---|---|---|
| 1 | **Your rules** | Caps, daily limits, allow- and blocklists for merchants, chains, tokens, addresses |
| 2 | **Prompt-injection** | "Ignore previous instructions" patterns and friends |
| 3 | **Misspelled merchants** | `api-anthropc.com`, `аpple.com` (Cyrillic homoglyph) — for *every* user, allowlist or not |
| 4 | **Crypto safety** | OFAC sanctioned addresses (live feed), address-poisoning attacks, known-drainer contracts |
| 5 | **Intent** | Does the spend match the agent's mission and recent context? Crypto-aware. |
| 6 | **Anomaly** | Velocity bursts, merchant-diversity spikes, off-pattern amounts |
| 7 | **Behavior baseline** | Per-agent rolling stats — distinguishes "trading bot at 20 tx/min (normal)" from "inference agent at 20 tx/min (suspicious)" |
| 8 | **Final decision** | Weighted aggregation, fraud floor, human-required floor, signed receipt with full trace |

Output: `approve` / `deny` / `escalate` plus a `risk_score` (0–1), structured `reason_codes`, and the full `engine_trace`. The receipt signs all of it.

---

## On-chain hard-stop

A minimal smart wallet (`VetoGuardedAccount`) holds the agent's funds and only releases them on a fresh, in-scope, Veto-signed mandate. Single-use, time-bound, scope-locked. Deployed and proven:

| | |
|---|---|
| **Live contract** | [`0xCBbbC4b924AF40D29f135c3a88b6F650d55d92c5`](https://sepolia.basescan.org/address/0xCBbbC4b924AF40D29f135c3a88b6F650d55d92c5) on Base Sepolia |
| **First execution** | [`0x2f9ec…d2af`](https://sepolia.basescan.org/tx/0x2f9ec691a6f5958bea296c5f630b26d1be1d93667dc3c974671cce0773cad2af) — 0.000001 ETH transferred |
| **Replay rejected** | `MandateAlreadySpent()` selector `0xffa64355` — the chain refused a duplicate |
| **Off-chain verifier** | [`@veto/mandate-verifier`](https://github.com/veto-protocol/mandate-verifier) (TS, Node 18+) |
| **Source** | [`veto-protocol/contracts`](https://github.com/veto-protocol/contracts) |

Verification: secp256k1 EIP-712 + `ecrecover` (~3k gas). Domain separator binds `chainId` + `verifyingContract` → no cross-chain or cross-contract replay either. Each mandate carries a single-use `jti` the contract tracks on-chain. **Production audited contracts ship in v2.**

---

## Scaffold an agent

```bash
veto agent init --name my-agent --dir ./my-agent
```

Generates a runnable TypeScript project with a local viem wallet (you own the key — no third-party vendor), an LLM brain you choose during setup (Anthropic Claude, OpenAI, or xAI Grok), tool wrappers for `send_eth` / `send_usdc` / `get_balance`, and every governed call routed through Veto's `authorize` first. Denies halt the agent before broadcast.

The full 4-step interactive lifecycle:

```text
veto agent init      # scaffold the project + generate keys + write .env
veto agent fund      # auto-open faucet, poll for funds, confirm
veto agent deploy    # deploy a VetoGuardedAccount smart wallet (testnet)
veto agent status    # snapshot of agent + wallet + contract + policy
```

When `WALLET_CONTRACT` is set in `.env`, `send_*` calls go through `executeWithMandate(...)` on the deployed smart wallet. The chain refuses spends without a fresh, in-scope, Veto-signed mandate. Cooperative on the SDK side, hard-stop on the chain side, simultaneously.

---

## Why Veto

<table>
<tr>
<td width="33%" valign="top">

### 🔒 &nbsp;Signed by default

Every approve, deny, escalate ships with an Ed25519-signed receipt over the canonical decision payload — engine version, policy fingerprint, signal scores, decision. Anyone verifies offline against `/.well-known/jwks.json`. The audit trail can't be rewritten.

</td>
<td width="33%" valign="top">

### ⛓️ &nbsp;Optional on-chain hard-stop

For adversarial threat models, a smart wallet contract refuses to settle without a fresh Veto mandate. Live on Base Sepolia today; audited mainnet ships next. Same SDK, same policy, additional chain-level guarantee.

</td>
<td width="33%" valign="top">

### 🛤️ &nbsp;Rail-agnostic

x402 (USDC over HTTP 402), Stripe MPP, AP2, direct EVM/Solana, Verifiable Intent. Veto sits one layer above the rail — pick whatever the rest of your stack picked. The policy travels with the agent.

</td>
</tr>
</table>

---

## The comparison

|                                          | Wallet stacks  | Risk engines      | Schema specs       | **Veto**                          |
| ---------------------------------------- | -------------- | ----------------- | ------------------ | --------------------------------- |
| Holds the agent's wallet                 | ✅              | ❌                 | ❌                  | ❌ *(non-custodial by design)*    |
| **Per-tx & daily caps**                  | ⚠️ wallet limit | ✅                 | ✅ *(spec only)*    | ✅ **enforced + versioned**       |
| **Merchant + address allowlists**        | ❌              | ⚠️ flat list      | ✅                  | ✅ **YAML + rollback**            |
| **Typosquat + address-poisoning checks** | ❌              | ⚠️ basic          | ❌                  | ✅ **canonical + homoglyph-aware** |
| **OFAC sanctioned-address live feed**    | ❌              | ⚠️ static         | ❌                  | ✅ **OFAC SDN, refreshed**        |
| **Per-agent behavioral baselines**       | ❌              | ⚠️ per-account    | ❌                  | ✅ **percentile-aware, per-agent** |
| **Signed decision receipts**             | ❌              | ❌                 | ❌                  | ✅ **Ed25519 + JWKS, offline-verifiable** |
| **On-chain hard-stop**                   | ❌              | ❌                 | ❌                  | ✅ **VetoGuardedAccount + EIP-712 mandate** |
| **Composable across rails**              | ❌ rail-bound   | ⚠️ vendor-bound  | ✅                  | ✅ **x402 / MPP / AP2 / on-chain** |
| **Open source where it matters**         | ❌              | ❌                 | ✅                  | ✅ **CLI + schema + contract + verifier** |

**Veto is the operator-policy layer for autonomous-spending agents.** The thing that makes "agent has a wallet" go from scary demo to production default.

---

## All commands

| Command | What it does |
|---------|--------------|
| `veto register` | CLI-native signup. Creates account + default agent + preset policy. |
| `veto authorize` | Ask Veto whether an action is allowed. Headline command. |
| `veto verify` | Verify a Veto receipt offline against the issuer's JWKS endpoint. |
| `veto policy export/push/show/list/check/activate` | Author and manage versioned YAML policies. |
| `veto agent init` | Scaffold a runnable Veto-governed agent project (TypeScript). |
| `veto agent fund` | Open a faucet for the agent's wallet, poll for funds. |
| `veto agent deploy` | Deploy a `VetoGuardedAccount` smart wallet (testnet). |
| `veto agent status` | Snapshot of agent + wallet + contract + policy state. |
| `veto agent configure` | Re-run onboarding to fill in skipped keys. |
| `veto init` | Auto-detect MCP clients (Claude Desktop, Cursor, Zed, Continue) and configure them. |
| `veto status [agent_id]` | Show agent reputation tier + recent decision history. |
| `veto mcp` | Run the Veto MCP server in stdio mode (used by MCP clients). |

---

## Five policy presets to start from

`veto register` applies a policy preset so your agent has sensible limits from the first authorize call. Pick one with `--preset`:

| Preset | For | Defaults |
|--------|-----|----------|
| `personal` *(default)* | General-purpose agent | $500/tx, $2k/day, blocks gambling/mixers/adult |
| `inference` | AI API calls | $5/tx, allowlists Anthropic/OpenAI/Replicate/etc. |
| `x402-micropay` | x402 testing | $1/tx, Base chain only, auto-approve <$0.10 |
| `ad-spend` | Meta/Google ads | $1k/tx, escalate >$1k |
| `dev` | Dogfooding/testing | $500/tx, no merchant restrictions |

When the preset isn't enough:

```bash
veto policy export inference > my-policy.yaml
$EDITOR my-policy.yaml
veto policy push my-policy.yaml      # auto-versioned, auto-active
veto policy check '{"action":"payment","amount":50,"merchant":"amazon.com"}'
veto policy activate <prior-policy-id>   # instant rollback
```

Every push creates a new versioned row. Receipts cite the exact `policy_id`, `version_number`, and `policy_hash` active at decision time — so an auditor in 12 months can prove which exact policy contents governed any past decision.

---

## How it works

```
┌──────────────────────────────────────────────────────────────────┐
│  AGENT — your code, your stack, your runtime                     │
│  Calls veto.authorize() before each spend                        │
└────────────────────────┬─────────────────────────────────────────┘
                         │ HTTPS
                         ▼
┌──────────────────────────────────────────────────────────────────┐
│  VETO ENGINE — 8-stage pipeline                                  │
│  Policy · Prompt-inj · Typosquat · Crypto safety                 │
│  Intent · Anomaly · Baseline · Aggregator                        │
└────────────────────────┬─────────────────────────────────────────┘
                         │
       ┌─────────────────┴─────────────────┐
       ▼                                   ▼
┌──────────────┐                 ┌──────────────────────┐
│  Receipt     │                 │  Mandate (optional)  │
│  Ed25519 JWS │                 │  Ed25519 JWT (off-   │
│  for audit   │                 │  chain)              │
│              │                 │  + secp256k1 EIP-712 │
│              │                 │  (on-chain)          │
└──────────────┘                 └──────────┬───────────┘
                                            │
                                            ▼
                                 ┌──────────────────────┐
                                 │  VetoGuardedAccount  │
                                 │  smart wallet        │
                                 │  ecrecover · verify  │
                                 │  scope · settle      │
                                 │  or revert           │
                                 └──────────────────────┘
```

The cooperative path (left, just the receipt) is enough for most threat models — bugs, hallucinations, runaway loops. The hard-stop path (right, with the smart wallet) closes the adversarial case where the agent code itself is compromised. Same engine, same policy, two enforcement surfaces.

---

## Composes with

| Spec | One-line | How Veto composes |
|------|----------|-------------------|
| [x402](https://x402.org) | HTTP 402 micropayments (USDC on Base) | `veto authorize` runs before the agent signs the x402 payload |
| [AP2](https://ap2-protocol.org/) (Google) | User → Agent intent mandates | Receipts carry `mandate_ref` to cite an upstream AP2 mandate |
| [Stripe MPP](https://stripe.com/blog/machine-payments-protocol) | Agent-to-merchant card-rail payments | Veto sits above; rail handles settlement |
| [Verifiable Intent](https://verifiableintent.dev/) (Mastercard + Google) | Sibling of AP2 | Same pattern as AP2 |
| [ACP](https://www.agenticcommerce.dev/) (OpenAI + Stripe) | Catalog/cart/checkout API | Different layer (Layer 5); orthogonal |

Different layer, different problem, complementary primitive. When all four exist on a transaction, the agent carries: AP2/VI mandate (legal consent), Veto receipt (operational compliance), ACP merchant flow (commerce), MPP/x402 settlement (money). All four produce signed credentials.

---

## Documentation

- 📐 [Architecture](https://github.com/veto-protocol/docs/blob/main/docs/architecture.md) — the 5-layer stack, engine pipeline, on-chain hard-stop
- 🚀 [Quickstart](https://github.com/veto-protocol/docs/blob/main/docs/quickstart.md) — first 60 seconds (install → authorize → verify → agent init)
- 📜 [Receipts](https://github.com/veto-protocol/docs/blob/main/docs/receipts.md) — receipt format spec, signing, verification, audit guarantees
- 🛡️ [Policies](https://github.com/veto-protocol/docs/blob/main/docs/policies.md) — YAML format, presets, customization, lifecycle
- 🗺️ [Roadmap](https://github.com/veto-protocol/docs/blob/main/docs/roadmap.md) — what's shipped (v0.6) → what's next (audit + mainnet)

---

## Public artifacts

| Artifact | Repository |
|----------|------------|
| CLI source (this repo) | [veto-protocol/veto-cli](https://github.com/veto-protocol/veto-cli) |
| APPS — open policy schema | [veto-protocol/x402-policy-schema](https://github.com/veto-protocol/x402-policy-schema) |
| Mandate verifier (TS) | [veto-protocol/mandate-verifier](https://github.com/veto-protocol/mandate-verifier) |
| Smart wallet contract | [veto-protocol/contracts](https://github.com/veto-protocol/contracts) |
| Veto's own published policies | [veto-protocol/veto-policies](https://github.com/veto-protocol/veto-policies) |
| Documentation | [veto-protocol/docs](https://github.com/veto-protocol/docs) |
| Public JWKS (Ed25519 signing key) | https://veto-ai.com/.well-known/jwks.json |
| Live contract on Base Sepolia | https://sepolia.basescan.org/address/0xCBbbC4b924AF40D29f135c3a88b6F650d55d92c5 |

---

## Community

- 🐦 [@veto_ai](https://twitter.com/veto_ai) — release notes, demos, ecosystem updates
- 🐛 [Issues](https://github.com/veto-protocol/veto-cli/issues) — bugs and feature requests
- ✉️ [tomer@veto-ai.com](mailto:tomer@veto-ai.com) — direct line to the founder

---

## Development

```bash
git clone https://github.com/veto-protocol/veto-cli.git
cd veto-cli
pip install -e ".[dev]"
pytest                                # unit tests
veto --help                           # local CLI
```

**Contributing:** open an issue first to discuss meaningful changes. PRs welcome on bugs, docs, new policy presets, and engine signal additions.

---

## License

Elastic License v2 (ELv2). See [LICENSE](LICENSE) for the full text and copyright. You may use, modify, and embed Veto freely. You may not host Veto as a managed service to third parties or strip the licensing notices.

---

<div align="center">

**The safety layer for AI agents that spend money.**<br>
<sub>Any agent. Any payment rail. Safe transactions.</sub>

<br><br>

<sub>Built by <a href="https://veto-ai.com">Investech Global LLC</a> · ELv2-licensed.</sub>

</div>
