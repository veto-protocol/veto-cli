/**
 * TOOL REGISTRY — what the agent can do.
 *
 * v0.6 (Veto + local viem wallet): the bulk of tools come from `wallet-wrap.ts`
 * — a viem-based wallet (the user owns the private key directly, no third-party
 * vendor) wrapped with Veto's authorize check.
 *
 * Veto-specific tools (like `policy_update` — letting the agent inspect or
 * change its own policy) stay native here.
 *
 * To extend:
 *   • Adding a wallet action  → edit wallet-wrap.ts
 *   • Adding a Veto-native tool → add a file like policy-update.ts and
 *                                  append it to nativeTools below
 *   • Swapping the wallet stack → write a sibling wrap.ts (e.g.,
 *                                  agentkit-wrap.ts for CDP, privy-wrap.ts
 *                                  for Privy embedded wallets)
 */

import { policyUpdateTool } from "./policy-update.js";
import { getWalletTools } from "./wallet-wrap.js";

export type ToolResult =
  | { ok: true; output: string; metadata?: Record<string, unknown> }
  | { ok: false; error: string; metadata?: Record<string, unknown> };

export type Tool = {
  name: string;
  description: string;
  input: Record<string, unknown>; // JSON schema
  execute: (args: Record<string, unknown>) => Promise<ToolResult>;
};

const nativeTools: Tool[] = [policyUpdateTool];

let _toolCache: Tool[] | null = null;

/** All tools the agent can call: Veto-native + wallet (Veto-wrapped). */
export async function getTools(): Promise<Tool[]> {
  if (_toolCache) return _toolCache;
  const walletTools = await getWalletTools();
  _toolCache = [...nativeTools, ...walletTools];
  return _toolCache;
}

export async function getTool(name: string): Promise<Tool | undefined> {
  const tools = await getTools();
  return tools.find((t) => t.name === name);
}

export async function toolsForClaude(): Promise<Array<{
  name: string;
  description: string;
  input_schema: Record<string, unknown>;
}>> {
  const tools = await getTools();
  return tools.map((t) => ({ name: t.name, description: t.description, input_schema: t.input }));
}

export async function toolsForOpenAI(): Promise<Array<{
  type: "function";
  function: { name: string; description: string; parameters: Record<string, unknown> };
}>> {
  const tools = await getTools();
  return tools.map((t) => ({
    type: "function" as const,
    function: { name: t.name, description: t.description, parameters: t.input },
  }));
}
