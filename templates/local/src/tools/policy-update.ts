/**
 * policy_update — agent updates its own Veto policy.
 *
 * Powerful but dangerous. The agent reads its own current policy, the user
 * tells it how to change (in natural language), the agent translates that
 * to YAML, then pushes the new policy to Veto.
 *
 * This tool is the meta-action: the agent reasoning about its own
 * constraints. The user is still the operator — they tell the agent
 * what to do, the agent just turns natural language into YAML.
 *
 * Important caveat: changing policy via this tool changes the rules
 * that govern the SAME agent. Make sure your Veto policy doesn't allow
 * the agent to e.g. raise its own daily cap to infinity. Lock the
 * `policy_update` action behind escalation in your policy if you want a
 * human in the loop for policy changes.
 */

import { fetch } from "undici";
import type { Tool, ToolResult } from "./index.js";

const VETO_BASE_URL = process.env.VETO_BASE_URL ?? "https://veto-ai.com";
const VETO_API_KEY = process.env.VETO_API_KEY ?? "";

export const policyUpdateTool: Tool = {
  name: "policy_update",
  description:
    "Read the agent's current Veto policy and (optionally) push an updated version. " +
    "Use to inspect or change spending caps, merchant allowlists, escalation triggers. " +
    "Pass 'mode: read' to just see the current policy, or 'mode: write' with a YAML body to update. " +
    "Note: Veto governs this action too — depending on policy, write mode may require human approval.",
  input: {
    type: "object",
    required: ["mode"],
    properties: {
      mode: {
        type: "string",
        enum: ["read", "write"],
        description: "'read' returns the active policy; 'write' pushes a new version.",
      },
      yaml: {
        type: "string",
        description:
          "(write only) The new policy as a YAML string. Must include policy_version, agent.id, " +
          "and at least one of: spend_caps, allowed_merchants, denied_merchants, velocity_limits, require_approval.",
      },
    },
  },
  async execute(args): Promise<ToolResult> {
    const mode = String(args.mode);

    if (mode === "read") {
      try {
        const res = await fetch(`${VETO_BASE_URL}/api/v1/policies/active/`, {
          headers: { "X-Veto-Api-Key": VETO_API_KEY },
        });
        if (!res.ok) return { ok: false, error: `Veto returned HTTP ${res.status}` };
        const data = await res.text();
        return { ok: true, output: `Current active policy:\n${data}` };
      } catch (err: any) {
        return { ok: false, error: `Failed to fetch policy: ${err.message}` };
      }
    }

    if (mode === "write") {
      const yaml = String(args.yaml ?? "");
      if (!yaml.trim()) return { ok: false, error: "yaml argument is required for write mode." };
      try {
        const res = await fetch(`${VETO_BASE_URL}/api/v1/policies/`, {
          method: "POST",
          headers: {
            "X-Veto-Api-Key": VETO_API_KEY,
            "Content-Type": "application/x-yaml",
          },
          body: yaml,
        });
        if (!res.ok) {
          const errText = await res.text();
          return { ok: false, error: `Veto rejected the policy: HTTP ${res.status}: ${errText.slice(0, 300)}` };
        }
        const result: any = await res.json();
        return {
          ok: true,
          output:
            `Policy updated. New version v${result.version_number} (${result.name}) is now active. ` +
            `policy_id: ${result.policy_id}, hash: ${result.policy_hash}`,
        };
      } catch (err: any) {
        return { ok: false, error: `Policy push failed: ${err.message}` };
      }
    }

    return { ok: false, error: `Unknown mode: ${mode}` };
  },
};
