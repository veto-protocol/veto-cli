/**
 * LOCAL WALLET WRAPPER — viem + a private key the user owns.
 *
 * Pattern: define each wallet action explicitly. Wrap with veto.authorize.
 * No third-party wallet vendor (no Coinbase, no Privy) — the key lives in
 * .env on the user's machine.
 *
 * Available actions:
 *   • get_balance  — read native balance (no governance — read-only)
 *   • get_address  — read wallet address (no governance — read-only)
 *   • send_eth     — send native ETH (governed)
 *   • send_usdc    — send USDC on the configured chain (governed)
 *
 * Two enforcement modes:
 *   • Cooperative (default) — the EOA broadcasts directly. Veto's deny halts
 *     the agent before the tx is built. Used when WALLET_CONTRACT is unset.
 *   • Hard-stop (opt-in)   — set WALLET_CONTRACT in .env to the address of a
 *     deployed VetoGuardedAccount that holds the funds. The EOA pays gas; the
 *     contract refuses to release funds without a fresh, in-scope, Veto-signed
 *     mandate. Even a compromised agent can't move funds.
 */

import { createPublicClient, createWalletClient, http, parseEther, parseUnits, formatEther, formatUnits, getContract } from "viem";
import { privateKeyToAccount } from "viem/accounts";
import { base, baseSepolia, mainnet } from "viem/chains";
import type { Tool, ToolResult } from "./index.js";
import { vetoClient, agentId } from "../veto-client.js";

// ── Chain selection ──────────────────────────────────────────────────
const NETWORK = process.env.NETWORK ?? "base-mainnet";
const CHAIN = NETWORK === "base-sepolia" ? baseSepolia
            : NETWORK === "ethereum"     ? mainnet
            : base;

// USDC contract address per chain
const USDC: Record<string, `0x${string}`> = {
  "base-mainnet":  "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
  "base-sepolia":  "0x036CbD53842c5426634e7929541eC2318f3dCF7e",
  "ethereum":      "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
};

// ── Wallet setup ─────────────────────────────────────────────────────
// Factories are cheap; constructing fresh per call keeps TS happy with
// viem's chain-generic types and avoids stale state across config reloads.

function getAccount() {
  const pk = process.env.WALLET_PRIVATE_KEY;
  if (!pk) throw new Error("WALLET_PRIVATE_KEY not set in .env. Run `veto agent configure` to regenerate one.");
  return privateKeyToAccount(pk as `0x${string}`);
}

function getWallet() {
  return createWalletClient({ account: getAccount(), chain: CHAIN, transport: http(process.env.RPC_URL) });
}

function getPublic() {
  return createPublicClient({ chain: CHAIN, transport: http(process.env.RPC_URL) });
}

// ── Hard-stop config ─────────────────────────────────────────────────
// When set, governed actions route through the contract. Unset = direct EOA.
const WALLET_CONTRACT = (process.env.WALLET_CONTRACT ?? "").trim() as `0x${string}` | "";

// VetoGuardedAccount.executeWithMandate ABI fragment.
const VETO_GUARDED_ACCOUNT_ABI = [
  {
    type: "function",
    name: "executeWithMandate",
    stateMutability: "nonpayable",
    inputs: [
      {
        name: "m",
        type: "tuple",
        components: [
          { name: "jti", type: "bytes32" },
          { name: "exp", type: "uint256" },
          { name: "recipient", type: "address" },
          { name: "maxAmount", type: "uint256" },
          { name: "token", type: "address" },
        ],
      },
      { name: "signature", type: "bytes" },
      { name: "amount", type: "uint256" },
    ],
    outputs: [],
  },
] as const;

// ── Helper: run veto.authorize before a governed action ──────────────
import type { OnChainMandate } from "../veto-client.js";

type AuthzOk = {
  ok: true;
  mandate?: string;
  mandate_onchain?: OnChainMandate;
  tx_id: string;
};
type AuthzErr = { ok: false; error: string };

async function authorizeOrFail(opts: {
  action: "payment" | "crypto_transfer" | "tool_execution";
  amount: number | null;
  merchant: string;
  description: string;
  // Set when we want a mandate_onchain back from Veto.
  onchain?: {
    to_address: `0x${string}`;
    amount_wei: string;
    token_contract: `0x${string}`;  // address(0) for native ETH
    chain: string;
  };
}): Promise<AuthzOk | AuthzErr> {
  const req: any = {
    agent_id: agentId(),
    action: opts.action,
    amount: opts.amount,
    merchant: opts.merchant,
    description: opts.description,
  };
  if (opts.onchain && WALLET_CONTRACT) {
    req.wallet_contract = WALLET_CONTRACT;
    req.chain_id = CHAIN.id;
    req.to_address = opts.onchain.to_address;
    req.amount_wei = opts.onchain.amount_wei;
    req.token_contract = opts.onchain.token_contract;
    req.chain = opts.onchain.chain;
  }

  let verdict;
  try {
    verdict = await vetoClient().authorize(req);
  } catch (err: any) {
    return { ok: false, error: `Veto unreachable: ${err?.message ?? String(err)}` };
  }
  if (verdict.status === "denied") {
    return { ok: false, error: `Veto denied. Reason codes: ${(verdict.reason_codes ?? []).join(", ")}.` };
  }
  if (verdict.status === "escalated") {
    return { ok: false, error: `Veto escalated for human approval. tx_id=${verdict.transaction_id}` };
  }
  if (verdict.status !== "approved" && verdict.status !== "executed") {
    return { ok: false, error: `Unexpected Veto status: ${verdict.status}` };
  }
  return {
    ok: true,
    mandate: verdict.mandate,
    mandate_onchain: verdict.mandate_onchain,
    tx_id: verdict.transaction_id,
  };
}

// ── Helper: settle through VetoGuardedAccount ────────────────────────
async function settleViaContract(
  mandate: OnChainMandate,
  amountWei: bigint,
): Promise<`0x${string}`> {
  const wallet = getWallet();
  return wallet.writeContract({
    address: mandate.verifying_contract as `0x${string}`,
    abi: VETO_GUARDED_ACCOUNT_ABI,
    functionName: "executeWithMandate",
    args: [
      {
        jti: mandate.mandate.jti as `0x${string}`,
        exp: BigInt(mandate.mandate.exp),
        recipient: mandate.mandate.recipient as `0x${string}`,
        maxAmount: BigInt(mandate.mandate.maxAmount),
        token: mandate.mandate.token as `0x${string}`,
      },
      mandate.signature as `0x${string}`,
      amountWei,
    ],
    chain: CHAIN,
    account: getAccount(),
  });
}

// ── Action: get_address ──────────────────────────────────────────────
const getAddressTool: Tool = {
  name: "get_address",
  description: "Return the agent's wallet address. Read-only — not governed.",
  input: { type: "object", properties: {} },
  async execute(): Promise<ToolResult> {
    try {
      return { ok: true, output: getAccount().address };
    } catch (err: any) {
      return { ok: false, error: err?.message ?? String(err) };
    }
  },
};

// ── Action: get_balance ──────────────────────────────────────────────
const getBalanceTool: Tool = {
  name: "get_balance",
  description: "Return the agent's native (ETH) and USDC balance on the configured network. Read-only — not governed.",
  input: { type: "object", properties: {} },
  async execute(): Promise<ToolResult> {
    try {
      const account = getAccount();
      const pub = getPublic();
      const ethBalance = await pub.getBalance({ address: account.address });
      const usdcAddr = USDC[NETWORK];
      let usdcBalance = 0n;
      if (usdcAddr) {
        const erc20 = getContract({
          address: usdcAddr,
          abi: [{ name: "balanceOf", type: "function", stateMutability: "view", inputs: [{ type: "address" }], outputs: [{ type: "uint256" }] }],
          client: pub,
        });
        usdcBalance = await erc20.read.balanceOf([account.address]) as bigint;
      }
      return {
        ok: true,
        output:
          `Address: ${account.address}\n` +
          `Network: ${NETWORK} (chain ${CHAIN.id})\n` +
          `ETH:  ${formatEther(ethBalance)} ETH\n` +
          `USDC: ${formatUnits(usdcBalance, 6)} USDC`,
      };
    } catch (err: any) {
      return { ok: false, error: err?.message ?? String(err) };
    }
  },
};

// ── Action: send_eth (governed) ──────────────────────────────────────
const sendEthTool: Tool = {
  name: "send_eth",
  description: "Send native ETH from the agent's wallet to a recipient address. Veto authorizes the spend before the tx is broadcast.",
  input: {
    type: "object",
    required: ["to", "amount_eth"],
    properties: {
      to: { type: "string", description: "Recipient address (0x-prefixed)." },
      amount_eth: { type: "string", description: "Amount in ETH (string, e.g. '0.001')." },
      memo: { type: "string", description: "Optional context for Veto's intent verification." },
    },
  },
  async execute(args): Promise<ToolResult> {
    const to = String(args.to) as `0x${string}`;
    const amountEth = String(args.amount_eth);
    const memo = String(args.memo ?? "");
    const amountWei = parseEther(amountEth);

    // Cheap rough USD estimate for Veto cap-check (assumes ~$3000/ETH; user's
    // Veto policy should be stated in USD so we estimate. For accuracy in
    // production, fetch the live ETH/USD price before authorize.)
    const estUsd = parseFloat(amountEth) * 3000;

    const authz = await authorizeOrFail({
      action: "crypto_transfer",
      amount: estUsd,
      merchant: to,
      description: `Send ${amountEth} ETH to ${to}. ${memo}`,
      onchain: {
        to_address: to,
        amount_wei: amountWei.toString(),
        token_contract: "0x0000000000000000000000000000000000000000" as `0x${string}`,
        chain: NETWORK,
      },
    });
    if (!authz.ok) return authz;

    try {
      let txHash: `0x${string}`;
      let mode: "eoa" | "contract";
      if (WALLET_CONTRACT && authz.mandate_onchain) {
        mode = "contract";
        txHash = await settleViaContract(authz.mandate_onchain, amountWei);
      } else {
        mode = "eoa";
        const wallet = getWallet();
        txHash = await wallet.sendTransaction({
          to,
          value: amountWei,
          chain: CHAIN,
          account: getAccount(),
        } as any);
      }
      return {
        ok: true,
        output: `Sent ${amountEth} ETH to ${to} via ${mode}. tx: ${txHash}, veto_tx_id: ${authz.tx_id}`,
        metadata: { tx_hash: txHash, veto_transaction_id: authz.tx_id, mode },
      };
    } catch (err: any) {
      return { ok: false, error: `Veto approved but tx failed: ${err?.message ?? String(err)}` };
    }
  },
};

// ── Action: send_usdc (governed) ─────────────────────────────────────
const sendUsdcTool: Tool = {
  name: "send_usdc",
  description: "Send USDC from the agent's wallet to a recipient address on the configured chain. Veto authorizes the spend before broadcast.",
  input: {
    type: "object",
    required: ["to", "amount_usd"],
    properties: {
      to: { type: "string", description: "Recipient address (0x-prefixed)." },
      amount_usd: { type: "number", description: "Amount in USD (USDC is 1:1 with USD)." },
      memo: { type: "string", description: "Optional context for Veto's intent verification." },
    },
  },
  async execute(args): Promise<ToolResult> {
    const to = String(args.to) as `0x${string}`;
    const amountUsd = Number(args.amount_usd);
    const memo = String(args.memo ?? "");
    const usdcAddr = USDC[NETWORK];
    if (!usdcAddr) return { ok: false, error: `USDC not configured for network ${NETWORK}. Edit src/tools/wallet-wrap.ts to add it.` };

    const amountUsdcUnits = parseUnits(amountUsd.toString(), 6);

    const authz = await authorizeOrFail({
      action: "crypto_transfer",
      amount: amountUsd,
      merchant: to,
      description: `Send ${amountUsd} USDC to ${to}. ${memo}`,
      onchain: {
        to_address: to,
        amount_wei: amountUsdcUnits.toString(),
        token_contract: usdcAddr,
        chain: NETWORK,
      },
    });
    if (!authz.ok) return authz;

    try {
      let txHash: `0x${string}`;
      let mode: "eoa" | "contract";
      if (WALLET_CONTRACT && authz.mandate_onchain) {
        mode = "contract";
        txHash = await settleViaContract(authz.mandate_onchain, amountUsdcUnits);
      } else {
        mode = "eoa";
        const wallet = getWallet();
        txHash = await wallet.writeContract({
          address: usdcAddr,
          abi: [{ name: "transfer", type: "function", stateMutability: "nonpayable", inputs: [{ name: "to", type: "address" }, { name: "amount", type: "uint256" }], outputs: [{ type: "bool" }] }],
          functionName: "transfer",
          args: [to, amountUsdcUnits],
          chain: CHAIN,
          account: getAccount(),
        });
      }
      return {
        ok: true,
        output: `Sent ${amountUsd} USDC to ${to} via ${mode}. tx: ${txHash}, veto_tx_id: ${authz.tx_id}`,
        metadata: { tx_hash: txHash, veto_transaction_id: authz.tx_id, mode },
      };
    } catch (err: any) {
      return { ok: false, error: `Veto approved but tx failed: ${err?.message ?? String(err)}` };
    }
  },
};

// ── Public export — the tools registered for the LLM brain ───────────
export async function getWalletTools(): Promise<Tool[]> {
  return [getAddressTool, getBalanceTool, sendEthTool, sendUsdcTool];
}
