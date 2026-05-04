/**
 * CONFIG — small runtime knobs.
 *
 * Most agent customization happens in:
 *   • src/persona.ts  (system prompt — who the agent is, how it behaves)
 *   • src/tools/      (which tools are available, what they do)
 *
 * This file is for runtime knobs that don't fit in either place.
 */

export const config = {
  /** Display name for logs. Substituted from `--name` flag at scaffold time. */
  agentName: "{{AGENT_NAME}}",

  /** Default model per provider. The brain (src/brain.ts) reads LLM_PROVIDER
   *  env and picks the corresponding model here. Override per-provider as
   *  you like — e.g., upgrade to Claude Opus, downgrade to GPT-4o-mini for
   *  cost, etc. */
  model: {
    anthropic: "claude-sonnet-4-5",   // good balance of capability + cost
    openai:    "gpt-4o-mini",          // fast + cheap; upgrade to gpt-4o for harder tasks
    grok:      "grok-4-mini",          // xAI's small model; upgrade to grok-4 for complex reasoning
  },

  /** Max tokens per response. Smaller = faster + cheaper. */
  maxTokens: 1024,

  /** How many turns of conversation history to include in each LLM call.
   *  Higher = more context, more $ per call. Lower = forgetful but cheaper. */
  contextTurns: 8,
};
