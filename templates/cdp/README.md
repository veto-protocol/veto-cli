# {{AGENT_NAME}}

A conversational, tool-using AI agent governed by Veto.
Scaffolded by `veto agent init --type cdp`.

---

## What this is

An autonomous agent that:

- **Talks** — you message it in natural language, it replies
- **Reasons** — Anthropic Claude (or OpenAI / Grok — your choice via `LLM_PROVIDER`)
- **Acts** — every blockchain capability from [Coinbase AgentKit](https://github.com/coinbase/agentkit): wallet ops, ERC-20 transfers, x402 calls, swaps, contract interactions
- **Is governed** — every AgentKit action runs through Veto's policy engine first. If Veto says deny, the action does not happen. Plus a Veto-signed mandate is required at the chain level for any paid action to settle.

You run this on infrastructure you choose: your laptop, a Fly.io VM, Modal, Replit Deployments, your VPS — anywhere Node.js runs. Veto never hosts the agent.

---

## How it works

```
                YOU ──── message ────►  AGENT (this code)
                                          │
                                          ▼ LLM (Claude/GPT/Grok) reads your message + persona
                                          │
                                          ▼ decides which tool to call
                                          │
                                          ▼
                   ┌──────────────────────────────────────────┐
                   │  Every tool is Veto-wrapped              │
                   │                                          │
                   │  1. veto.authorize() ──► engine          │
                   │     verdict: approve / deny / escalate   │
                   │     + signed mandate (if approved)       │
                   │                                          │
                   │  2. If approved → AgentKit invokes       │
                   │     wallet op / x402 call / transfer     │
                   │     (mandate attached to userOp)         │
                   │                                          │
                   │  3. Smart-account contract verifies      │
                   │     mandate against Veto's JWKS          │
                   │     • valid mandate → tx settles         │
                   │     • no mandate    → contract reverts   │
                   └──────────────────────────────────────────┘
                                          │
                                          ▼ agent replies to you
```

**Hard-stop at the chain level.** For paid actions, the smart-account contract requires the Veto-signed mandate to settle. Without it the contract reverts and the transaction never broadcasts. The agent can't bypass it even if it tried.

**The architecture in one line:** Veto governs · AgentKit acts · CDP holds the wallet · the contract enforces.

---

## Setup

### 1. Get your API keys

You need three:

| Key | Where to get it |
|---|---|
| **Veto** (`VETO_API_KEY` + `VETO_AGENT_ID`) | Run `veto register --preset inference --email you@example.com` |
| **Anthropic** (`ANTHROPIC_API_KEY`) | https://console.anthropic.com → API keys |
| **Coinbase CDP** (`CDP_API_KEY_ID` + `CDP_API_KEY_SECRET`) | https://portal.cdp.coinbase.com → projects → API keys |

You'll also need a CDP smart-account wallet. The next version of `veto agent init` will provision this for you automatically; for now create one manually in the CDP portal and paste `CDP_WALLET_ADDRESS` + `CDP_WALLET_ID` into `.env`.

### 2. Fill in `.env`

The scaffolder copied `.env.example` to `.env` for you. Open it, paste in the values from step 1.

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

Talk to it. Try: *"who are you?"*, *"pay $0.05 to api.openai.com for a test"*, *"what's my current daily cap?"*

---

## Deploy 24/7

Local mode is great for development but your laptop sleeps. For an always-on agent, deploy somewhere that runs Node.js processes 24/7. The scaffold ships with multiple options:

### Option A — Fly.io (free tier, fastest 24/7 path)

```bash
# One-time setup
brew install flyctl
fly auth signup

# Deploy
fly launch --no-deploy --copy-config        # uses the included fly.toml
fly secrets set VETO_API_KEY=… VETO_AGENT_ID=… ANTHROPIC_API_KEY=… \
                CDP_API_KEY_ID=… CDP_API_KEY_SECRET=… \
                CDP_WALLET_ADDRESS=… CDP_WALLET_ID=…
fly deploy

# Your agent is live:
curl https://{{AGENT_NAME}}.fly.dev/chat -X POST \
  -H "Content-Type: application/json" \
  -d '{"message":"hi who are you"}'
```

Fly's free tier covers small agents indefinitely. Auto-sleeps when idle, wakes on request.

### Option B — Railway / Render (Heroku-style)

Connect your repo, push to deploy. Both auto-detect the Dockerfile.

```bash
# Railway
railway login
railway init
railway up

# Render
# 1. Push to GitHub
# 2. New → Web Service → connect repo
# 3. Add env vars from your .env
# 4. Deploy
```

### Option C — Replit Deployments (click-to-deploy from browser)

1. Import the project to Replit
2. Add the secrets in the Secrets pane
3. Hit "Deploy" → Reserved VM
4. Your agent is live at `https://{{AGENT_NAME}}.replit.app/chat`

### Option D — Your own VPS / Mac with launchd / Modal

The scaffold is just a Node.js project with a Dockerfile. Run `docker run` anywhere that runs containers. Or run `npm start` under pm2/launchd/systemd on a server you own.

```bash
# Generic Docker
docker build -t {{AGENT_NAME}} .
docker run --env-file .env -p 8080:8080 {{AGENT_NAME}}
```

---

## Customize

| What | File | When to edit |
|---|---|---|
| **Persona / system prompt** | `src/persona.ts` | Change who the agent is, how it behaves, what it says when denied. Takes effect on next message. |
| **Available tools** | `src/tools/*.ts` + `src/tools/index.ts` | Add new tools (just write a file matching the `Tool` interface), remove tools you don't want, swap implementations (e.g., Tavily instead of Exa for search). |
| **LLM provider** | `.env` (`LLM_PROVIDER=anthropic\|openai\|grok`) | Switch between Anthropic Claude / OpenAI GPT / xAI Grok by setting one env var + the matching API key. The brain (`src/brain.ts`) handles the rest — same persona, same tools, same behavior across providers. |
| **Model per provider** | `src/config.ts` | Pick which Claude/GPT/Grok model to use (e.g., upgrade to gpt-4o for harder tasks, downgrade to gpt-4o-mini for cost). |
| **LLM brain (deeper)** | `src/brain.ts` | Add a new provider (Mistral, Cohere, local llama.cpp, Vercel AI SDK). Keep the `respond(message) → string` interface and chat/server still work. |
| **Memory** | `src/memory.ts` | v0.6 is in-memory only (lost on restart). Swap to SQLite / Redis / Postgres for durable history. |
| **Wallet integration** | `src/settler.ts` | Wire `@coinbase/cdp-sdk` + `@coinbase/x402-client` to make payments actually settle on chain. v0.6 ships a stub. |

### Outside the code: your Veto policy

Your spending caps, allowlists, and escalation triggers live in your Veto policy, not in this code. To inspect or change:

```bash
veto policy show           # current active policy as YAML
veto policy export inference > my-policy.yaml
$EDITOR my-policy.yaml
veto policy push my-policy.yaml
```

The agent itself can also call the `policy_update` tool to read or update its policy in conversation. (Be thoughtful — that means the agent can in principle relax its own constraints. Lock `policy_update` behind escalation in your policy if you don't want that.)

---

## Verifying receipts

Every Veto verdict ships with a cryptographically signed receipt. To verify offline:

```bash
veto verify <receipt-jws>
```

Or the agent can produce them in chat: ask *"show me the receipt for my last payment"* and it can return the JWS for you to verify.

---

## Modes

| MODE env | What it does | When to use |
|---|---|---|
| `chat` (default) | CLI REPL — type messages, see replies | Local dev, power users |
| `server` | HTTP server on `PORT` (default 8080), exposes `POST /chat` and `GET /health` | 24/7 deployments (Fly, Modal, Replit, etc.) |

`Dockerfile` defaults to `MODE=server`. `fly.toml` sets it explicitly.

---

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| `VETO_API_KEY is not set` | Run `veto register` then paste the key into `.env` |
| `ANTHROPIC_API_KEY` errors | Get one at https://console.anthropic.com |
| Tool says "Veto denied" with `MERCHANT_NOT_ALLOWLISTED` | The merchant isn't in your policy allowlist. Either change the merchant or `veto policy push` an updated policy |
| Tool says "Veto denied" with `AMOUNT_CAP_EXCEEDED` | Amount above your per-tx, daily, or monthly cap. Lower the amount or update policy |
| Agent loops calling the same tool | Could be a buggy tool always erroring. Check `MAX_TOOL_HOPS` in `brain.ts` (default 8) |
| Smart-account settlement fails | v0.6 ships the settler as a stub. Wire `@coinbase/cdp-sdk` in `src/settler.ts` to make payments actually broadcast |

---

## License

The scaffold itself is MIT — you own this code, do whatever you want with it.
The Veto engine you're calling is ELv2.
The APPS schema your policy uses is MIT.

## Links

- Veto landing — https://veto-ai.com
- veto-cli (engine + CLI) — https://github.com/veto-protocol/veto-cli
- APPS schema (open spec) — https://github.com/veto-protocol/x402-policy-schema
- Coinbase CDP — https://portal.cdp.coinbase.com
- Anthropic — https://console.anthropic.com
- Fly.io — https://fly.io
