/**
 * AGENTKIT WRAPPER — every AgentKit action, prefixed with veto.authorize().
 *
 * AgentKit (Coinbase) handles wallet provisioning, x402 settlement, ERC-20
 * transfers, swaps, contract calls — all the on-chain plumbing. We don't
 * reimplement any of that. Veto's job is the policy decision that runs
 * BEFORE every action: approve / deny / escalate, plus the signed mandate
 * that the smart-account contract will require to actually settle.
 *
 * The pattern:
 *   1. Initialize AgentKit with the user's CDP wallet
 *   2. Take every action AgentKit exposes
 *   3. Wrap each one with a Veto.authorize() check
 *   4. Pass wrapped actions to the LLM brain as the tool list
 *
 * Future: when we add `--type langchain` / `--type privy` / etc., each
 * gets its own wrapper file. The brain consumes whichever the user picked.
 */

import {
  AgentKit,
  CdpWalletProvider,
  walletActionProvider,
  erc20ActionProvider,
} from "@coinbase/agentkit";
import type { Tool, ToolResult } from "./index.js";
import { vetoClient, agentId } from "../veto-client.js";

let _agentkit: AgentKit | null = null;

async function getAgentKit(): Promise<AgentKit> {
  if (_agentkit) return _agentkit;

  const apiKeyId = process.env.CDP_API_KEY_ID;
  const apiKeySecret = process.env.CDP_API_KEY_SECRET;
  if (!apiKeyId || !apiKeySecret) {
    throw new Error(
      "CDP_API_KEY_ID and CDP_API_KEY_SECRET must be set. Get them at " +
      "https://portal.cdp.coinbase.com/projects/api-keys, then run `veto agent configure`.",
    );
  }

  const walletProvider = await CdpWalletProvider.configureWithWallet({
    apiKeyId,
    apiKeySecret,
    walletSecret: process.env.CDP_WALLET_SECRET,
    walletId: process.env.CDP_WALLET_ID,
    networkId: process.env.NETWORK ?? "base-mainnet",
  });

  _agentkit = await AgentKit.from({
    walletProvider,
    actionProviders: [
      walletActionProvider(),    // basic wallet ops: balance, address, transfer
      erc20ActionProvider(),     // ERC-20: USDC transfers, approvals, etc.
      // Add more here as we extend: x402ActionProvider(), swapActionProvider(), etc.
    ],
  });
  return _agentkit;
}

/** Map an AgentKit action name → the Veto action category for policy.
 *  Most blockchain actions are crypto_transfer; some are tool_execution. */
function vetoActionFor(name: string): "payment" | "crypto_transfer" | "tool_execution" {
  const n = name.toLowerCase();
  if (n.includes("transfer") || n.includes("send") || n.includes("swap")) return "crypto_transfer";
  if (n.includes("payment") || n.includes("pay") || n.includes("x402")) return "payment";
  return "tool_execution";
}

/** Best-effort extraction of amount + merchant from AgentKit args.
 *  Different actions use different field names; we try the common ones. */
function extractAmount(args: Record<string, unknown>): number | null {
  for (const k of ["amount", "amountUsd", "value", "wei"]) {
    const v = args[k];
    if (typeof v === "number") return v;
    if (typeof v === "string" && !Number.isNaN(parseFloat(v))) return parseFloat(v);
  }
  return null;
}

function extractMerchant(args: Record<string, unknown>, actionName: string): string {
  for (const k of ["to", "recipient", "merchant", "destination", "address", "url"]) {
    const v = args[k];
    if (typeof v === "string" && v.length > 0) return v;
  }
  return actionName;
}

/** Get all AgentKit actions, wrapped with Veto governance. */
export async function getAgentKitTools(): Promise<Tool[]> {
  const agentkit = await getAgentKit();
  const actions = agentkit.getActions();

  return actions.map((action: any): Tool => ({
    name: action.name,
    description:
      `[Governed by Veto] ${action.description ?? action.name} — ` +
      `Veto checks policy before this runs; smart-account contract requires Veto's signed mandate to settle.`,
    input: action.schema ?? action.input ?? { type: "object", properties: {} },

    async execute(args: Record<string, unknown>): Promise<ToolResult> {
      // ── 1. Veto.authorize ────────────────────────────────────────
      let verdict;
      try {
        verdict = await vetoClient().authorize({
          agent_id: agentId(),
          action: vetoActionFor(action.name),
          amount: extractAmount(args),
          merchant: extractMerchant(args, action.name),
          description: `${action.name} via AgentKit`,
        });
      } catch (err: any) {
        return { ok: false, error: `Veto unreachable: ${err?.message ?? String(err)}` };
      }

      if (verdict.status === "denied") {
        return {
          ok: false,
          error: `Veto denied. Reason codes: ${(verdict.reason_codes ?? []).join(", ")}. ${verdict.reason ?? ""}`.trim(),
          metadata: { verdict },
        };
      }
      if (verdict.status === "escalated") {
        return {
          ok: false,
          error: `Veto escalated for human approval. tx_id=${verdict.transaction_id}`,
          metadata: { verdict },
        };
      }
      if (verdict.status !== "approved" && verdict.status !== "executed") {
        return { ok: false, error: `Unexpected Veto status: ${verdict.status}`, metadata: { verdict } };
      }

      // ── 2. AgentKit invokes the action ───────────────────────────
      // The smart-account contract enforces the mandate at the chain level
      // when the userOp is built. AgentKit's wallet provider is configured
      // (or will be in the smart-account-hard-stop step of v0.6) to attach
      // the mandate JWT automatically. For now the mandate flows through
      // metadata so future wallet integrations can pick it up.
      try {
        const result = await action.invoke({ ...args, _vetoMandate: verdict.mandate });
        const output =
          typeof result === "string" ? result :
          result == null ? "(no output)" :
          JSON.stringify(result, null, 2);
        return {
          ok: true,
          output,
          metadata: { verdict, mandate_present: !!verdict.mandate },
        };
      } catch (err: any) {
        return {
          ok: false,
          error: `AgentKit action failed: ${err?.message ?? String(err)}`,
          metadata: { verdict },
        };
      }
    },
  }));
}
