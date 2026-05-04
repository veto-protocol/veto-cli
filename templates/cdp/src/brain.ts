/**
 * BRAIN — the LLM call + tool-calling loop.
 *
 * One invocation = one user turn. The agent may call multiple tools
 * before producing its final reply. We loop until the model returns text
 * (no more tool calls) or hits a safety limit.
 *
 * Provider switch via LLM_PROVIDER env (anthropic | openai | grok).
 *   - anthropic: native Anthropic SDK, Claude tool-use API
 *   - openai:    OpenAI SDK, function-calling API
 *   - grok:      OpenAI SDK pointed at https://api.x.ai/v1 (xAI's Grok API
 *                is OpenAI-compatible)
 *
 * Tools come from `tools/index.ts` — Veto-native tools (policy_update) +
 * AgentKit actions wrapped with Veto.authorize.
 */

import { config } from "./config.js";
import { systemPrompt } from "./persona.js";
import { memory } from "./memory.js";
import { getTools, getTool, toolsForClaude, toolsForOpenAI, ToolResult } from "./tools/index.js";

const MAX_TOOL_HOPS = 8;
const PROVIDER = (process.env.LLM_PROVIDER ?? "anthropic").toLowerCase();

export async function respond(userMessage: string): Promise<string> {
  memory.push({ role: "user", content: userMessage });

  switch (PROVIDER) {
    case "anthropic":
      return runAnthropic();
    case "openai":
      return runOpenAICompatible({});
    case "grok":
      return runOpenAICompatible({ baseURL: "https://api.x.ai/v1", apiKeyEnv: "XAI_API_KEY", defaultModel: "grok-4-mini" });
    default:
      throw new Error(`Unknown LLM_PROVIDER: ${PROVIDER}. Set to anthropic | openai | grok in .env.`);
  }
}

// ── Anthropic Claude ──────────────────────────────────────────────────

async function runAnthropic(): Promise<string> {
  const Anthropic = (await import("@anthropic-ai/sdk")).default;
  const apiKey = process.env.ANTHROPIC_API_KEY;
  if (!apiKey) throw new Error("ANTHROPIC_API_KEY is not set in .env. Either paste your key or switch LLM_PROVIDER to openai/grok.");

  const client = new Anthropic({ apiKey });
  const claudeTools = await toolsForClaude();
  const messages: any[] = memory.recent().map((m) => ({ role: m.role, content: m.content }));
  let toolHops = 0;

  while (toolHops < MAX_TOOL_HOPS) {
    const response = await client.messages.create({
      model: config.model.anthropic,
      max_tokens: config.maxTokens,
      system: systemPrompt(),
      tools: claudeTools as any,
      messages,
    });

    const hasToolUse = response.content.some((b: any) => b.type === "tool_use");
    if (!hasToolUse) {
      const textBlocks = response.content.filter((b: any) => b.type === "text") as any[];
      const reply = textBlocks.map((b) => b.text).join("\n").trim();
      memory.push({ role: "assistant", content: reply });
      return reply || "(no response)";
    }

    messages.push({ role: "assistant", content: response.content });
    const toolResults: any[] = [];
    for (const block of response.content as any[]) {
      if (block.type !== "tool_use") continue;
      const result = await executeTool(block.name, block.input);
      toolResults.push({
        type: "tool_result",
        tool_use_id: block.id,
        content: result.ok ? result.output : `Tool error: ${result.error}`,
        is_error: !result.ok,
      });
    }
    messages.push({ role: "user", content: toolResults });
    toolHops++;
  }
  return loopExceededFallback();
}

// ── OpenAI / Grok (OpenAI-compatible function calling) ────────────────

async function runOpenAICompatible(opts: {
  baseURL?: string;
  apiKeyEnv?: string;
  defaultModel?: string;
}): Promise<string> {
  const OpenAI = (await import("openai")).default;
  const apiKey = process.env[opts.apiKeyEnv ?? "OPENAI_API_KEY"];
  if (!apiKey) {
    const envName = opts.apiKeyEnv ?? "OPENAI_API_KEY";
    throw new Error(`${envName} is not set in .env. Either paste your key or switch LLM_PROVIDER.`);
  }

  const client = new OpenAI({ apiKey, baseURL: opts.baseURL });
  const model = opts.defaultModel ?? (PROVIDER === "openai" ? config.model.openai : config.model.grok);
  const openaiTools = await toolsForOpenAI();

  const messages: any[] = [
    { role: "system", content: systemPrompt() },
    ...memory.recent().map((m) => ({ role: m.role, content: m.content })),
  ];

  let toolHops = 0;
  while (toolHops < MAX_TOOL_HOPS) {
    const response = await client.chat.completions.create({
      model,
      max_tokens: config.maxTokens,
      messages,
      tools: openaiTools,
    });
    const choice = response.choices[0];
    const msg = choice.message;

    if (!msg.tool_calls || msg.tool_calls.length === 0) {
      const reply = (msg.content ?? "").trim();
      memory.push({ role: "assistant", content: reply });
      return reply || "(no response)";
    }

    messages.push(msg);
    for (const call of msg.tool_calls) {
      let parsed: Record<string, unknown> = {};
      try { parsed = JSON.parse(call.function.arguments); } catch { /* leave as {} */ }
      const result = await executeTool(call.function.name, parsed);
      messages.push({
        role: "tool",
        tool_call_id: call.id,
        content: result.ok ? result.output : `Tool error: ${result.error}`,
      });
    }
    toolHops++;
  }
  return loopExceededFallback();
}

// ── Shared tool executor ─────────────────────────────────────────────

async function executeTool(name: string, input: Record<string, unknown>): Promise<ToolResult> {
  const tool = await getTool(name);
  if (!tool) return { ok: false, error: `Tool '${name}' is not registered.` };
  try {
    return await tool.execute(input);
  } catch (err: any) {
    return { ok: false, error: `Tool threw: ${err?.message ?? String(err)}` };
  }
}

function loopExceededFallback(): string {
  const fallback =
    `I ran out of tool-calling iterations (${MAX_TOOL_HOPS}) before producing a response. ` +
    `Try rephrasing your request more concretely.`;
  memory.push({ role: "assistant", content: fallback });
  return fallback;
}
