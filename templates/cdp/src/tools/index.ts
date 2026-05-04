/**
 * TOOL REGISTRY — what the agent can do.
 *
 * v0.6 (Veto + AgentKit): the bulk of tools come from AgentKit (wallet ops,
 * ERC-20 transfers, x402 calls, swaps, etc.) — each wrapped with Veto's
 * authorize check. The wrapper layer lives in `agentkit-wrap.ts`.
 *
 * Veto-specific tools (like `policy_update` — letting the agent inspect
 * or change its own policy) stay native here.
 *
 * To extend:
 *   • Adding a new AgentKit action provider → edit agentkit-wrap.ts
 *   • Adding a Veto-native tool             → add a file like policy-update.ts
 *                                              and append it to nativeTools below
 *   • Swapping AgentKit for another stack   → write a sibling wrap.ts file
 *                                              (langchain-wrap.ts, privy-wrap.ts)
 *                                              and have the brain pick which to load
 */

import { policyUpdateTool } from "./policy-update.js";
import { getAgentKitTools } from "./agentkit-wrap.js";

export type ToolResult =
  | { ok: true; output: string; metadata?: Record<string, unknown> }
  | { ok: false; error: string; metadata?: Record<string, unknown> };

export type Tool = {
  name: string;
  description: string;
  input: Record<string, unknown>; // JSON schema
  execute: (args: Record<string, unknown>) => Promise<ToolResult>;
};

// ── Veto-native tools (always available) ─────────────────────────────
const nativeTools: Tool[] = [
  policyUpdateTool,
];

// ── Cache of resolved tool list (AgentKit init is async; cache once) ──
let _toolCache: Tool[] | null = null;

/** All tools the agent can call: Veto-native + AgentKit (Veto-wrapped). */
export async function getTools(): Promise<Tool[]> {
  if (_toolCache) return _toolCache;
  const agentkitTools = await getAgentKitTools();
  _toolCache = [...nativeTools, ...agentkitTools];
  return _toolCache;
}

export async function getTool(name: string): Promise<Tool | undefined> {
  const tools = await getTools();
  return tools.find((t) => t.name === name);
}

/** Convert tools to Claude's tool-definition format. */
export async function toolsForClaude(): Promise<Array<{
  name: string;
  description: string;
  input_schema: Record<string, unknown>;
}>> {
  const tools = await getTools();
  return tools.map((t) => ({
    name: t.name,
    description: t.description,
    input_schema: t.input,
  }));
}

/** Convert tools to OpenAI / Grok function-calling format. */
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
