# {{AGENT_NAME}}

A conversational, tool-using AI agent governed by Veto.
Local viem wallet — **no third-party wallet vendor**. You own the private key.

Scaffolded by `veto agent init`.

---

## What this is

An autonomous agent that:

- **Talks** — you message it in natural language, it replies
- **Reasons** — Anthropic Claude (or OpenAI / Grok — your choice via `LLM_PROVIDER`)
- **Acts** — sends ETH and USDC on Base via a wallet whose key lives in your `.env`. No Coinbase, no Privy, no third party.
- **Is governed** — every send goes through Veto's policy engine first. Approve / deny / escalate, with a signed receipt for the audit trail.

You run this on infrastructure you choose: your laptop, a Fly.io VM, Modal, Replit Deployments, your VPS — anywhere Node.js runs. Veto never hosts the agent; nobody but you holds the key.

---

## How it works

```
   YOU ──── message ────►  AGENT (this code)
                              │
                              ▼ LLM (Claude/GPT/Grok) reads your message + persona
                              │
                              ▼ decides which tool to call (e.g. send_usdc)
                              │
                              ▼  Veto-wrapped tool calls /api/v1/authorize/
                              │
                              ▼  policy engine returns approve/deny/escalate
                              │  + signed mandate JWT (v2 — for hard-stop wallets)
                              │
                              ▼  if approved: viem signs + broadcasts
                                if denied: agent halts, reports reason codes
                                if escalated: agent waits for human
                              │
                              ▼  agent replies to you
```

**v0.6 enforcement is cooperative:** the agent calls Veto, Veto returns a verdict, the agent honors it. The Veto mandate JWT comes back too — when v2's smart-account modules ship, you'll be able to upgrade your wallet to one that requires the mandate at the chain level. Then the deny becomes a hard-stop on chain, not just in your app's code.

---

## Setup

### 1. Get your API keys

| Key | Where to get it |
|---|---|
| **Veto** (`VETO_API_KEY` + `VETO_AGENT_ID`) | Run `veto register --preset inference --email you@example.com` |
| **LLM** (one of Anthropic / OpenAI / Grok) | https://console.anthropic.com or https://platform.openai.com or https://console.x.ai |

That's it. The wallet is generated locally during `veto agent init`.

### 2. Fund the wallet

`veto agent init` printed your wallet address. Send some ETH (for gas) and USDC to it.

For **mainnet**: send from your own wallet or a CEX.
For **testnet** (`base-sepolia`): use a faucet:
- ETH: https://www.alchemy.com/faucets/base-sepolia
- USDC: https://faucet.circle.com (pick Base Sepolia)

### 3. Install + run

```bash
npm install
npm run dev
```

You'll get a CLI prompt:

```
  {{AGENT_NAME}} — governed by Veto
  Type a message to talk. Ctrl+C to exit.

>
```

Talk to it. Try: *"who are you?"*, *"what's my address and balance?"*, *"send $0.10 USDC to 0x..."*, *"show me my current policy"*.

---

## Deploy 24/7

Local mode is great for development. For an always-on agent, deploy somewhere that runs Node.js processes 24/7:

### Option A — Fly.io (free tier, fastest 24/7)

```bash
brew install flyctl
fly auth signup
fly launch --no-deploy --copy-config
fly secrets set VETO_API_KEY=… VETO_AGENT_ID=… ANTHROPIC_API_KEY=… WALLET_PRIVATE_KEY=… RPC_URL=…
fly deploy
```

### Option B — Railway / Render

Both auto-detect the Dockerfile. Push your repo, set env vars in their dashboard, deploy.

### Option C — Replit Deployments

Import the project, paste secrets, hit Deploy → Reserved VM.

### Option D — Your own VPS / Modal

```bash
docker build -t {{AGENT_NAME}} .
docker run --env-file .env -p 8080:8080 {{AGENT_NAME}}
```

---

## Customize

| What | File | When to edit |
|---|---|---|
| **Persona / system prompt** | `src/persona.ts` | Change who the agent is, tone, how it behaves on deny/escalate |
| **Wallet actions** | `src/tools/wallet-wrap.ts` | Add new tools (swaps, contract calls), change network defaults |
| **LLM provider** | `.env` (`LLM_PROVIDER=anthropic\|openai\|grok`) | Switch brain by setting one env var + the matching API key |
| **Memory** | `src/memory.ts` | Swap to SQLite/Redis for durable history (in-memory only in v0.6) |

### Outside the code: your Veto policy

Spending caps, allowlists, escalation triggers live in your Veto policy:

```bash
veto policy show
veto policy export inference > my-policy.yaml
$EDITOR my-policy.yaml
veto policy push my-policy.yaml
```

The agent itself can read or update the policy via the `policy_update` tool. Lock it behind escalation in your policy if you don't want the agent to relax its own constraints.

---

## Hard-stop (opt-in, v0.6 testnet preview)

Today the agent's wallet is a plain EOA — Veto's deny stops the agent's code from sending, but the wallet itself COULD send if something bypassed the agent code. The hard-stop closes that gap by making the chain itself enforce the policy.

There's a stub contract you can deploy and try on Base Sepolia today:

1. Deploy a `VetoGuardedAccount` (in the Veto repo at `contracts/`). It holds funds and only releases them when presented with a fresh, in-scope mandate signed by Veto.
2. Fund it with testnet ETH for gas + the tokens you want the agent to spend.
3. Set `WALLET_CONTRACT=<address>` in your `.env`.
4. Restart the agent.

From that point, `send_eth` and `send_usdc` route through `VetoGuardedAccount.executeWithMandate(...)` instead of a direct EOA transfer. Veto's authorize endpoint returns a paired secp256k1 EIP-712 signature alongside the JWT mandate; the contract verifies it via `ecrecover` (~3k gas). If anyone tries to spend without a fresh, in-scope mandate, the contract reverts.

This is unaudited and testnet-only. Production-grade audited contracts ship in v2 (~10–12 weeks). Same agent code, same `.env` knob — when the audit lands, the upgrade is "deploy a v2 contract and update `WALLET_CONTRACT`".

---

## License

The scaffold itself is MIT — your code, your rules.
The Veto engine is ELv2.
The APPS schema is MIT.

## Links

- Veto landing — https://veto-ai.com
- veto-cli — https://github.com/veto-protocol/veto-cli
- APPS schema — https://github.com/veto-protocol/x402-policy-schema
- viem — https://viem.sh
- Anthropic — https://console.anthropic.com
- Fly.io — https://fly.io
