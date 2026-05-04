/**
 * Veto HTTP client — minimal inline SDK.
 *
 * Why inline? v0.6 ships the agent template self-contained — no separate
 * @veto/sdk npm package required. Once the API stabilizes, we extract this
 * file into a real package and the template just imports it.
 *
 * Design:
 *   - Stateless. Every call is independent.
 *   - No retry / backoff (caller decides).
 *   - Singleton-style accessors (vetoClient(), agentId()) for tools that
 *     don't want to thread the client/id through every signature.
 */

import { fetch } from "undici";

export type AuthorizeRequest = {
  agent_id: string;
  action: "payment" | "crypto_transfer" | "tool_execution";
  amount: number | null;
  merchant: string;
  description?: string;
  context?: string;
  decision_only?: boolean;
  /** When set (along with chain_id), Veto returns a `mandate_onchain` field
   *  with a secp256k1 EIP-712 signature that VetoGuardedAccount-style
   *  contracts can verify via `ecrecover`. Plus `to_address`/`amount_wei`/
   *  `token_contract` must be set for crypto_transfer. */
  wallet_contract?: string;
  chain_id?: number;
  to_address?: string;
  token_contract?: string;
  amount_wei?: string;
  chain?: string;
};

/** On-chain mandate — the secp256k1 EIP-712 sibling of the off-chain JWT.
 *  Issued only when the request opts in via `wallet_contract` + `chain_id`. */
export type OnChainMandate = {
  mandate: {
    jti: string;          // 0x-hex bytes32
    exp: number;
    recipient: string;    // 0x address
    maxAmount: string;    // uint256 as decimal string
    token: string;        // 0x address; address(0) for native ETH
  };
  signature: string;      // 0x… 65-byte secp256k1
  signer_address: string; // checksummed address
  chain_id: number;
  verifying_contract: string;
};

export type AuthorizeResponse = {
  transaction_id: string;
  status: "approved" | "denied" | "escalated" | "executed" | "failed";
  risk_score: number;
  reason_codes?: string[];
  reason?: string;
  receipt?: string;
  /** Ed25519-signed mandate JWT — for off-chain consumers. */
  mandate?: string;
  /** secp256k1 EIP-712 mandate — for on-chain consumers (VetoGuardedAccount). */
  mandate_onchain?: OnChainMandate;
};

export class VetoClient {
  private baseUrl: string;
  private apiKey: string;

  constructor(opts: { baseUrl?: string; apiKey: string }) {
    this.baseUrl = (opts.baseUrl ?? "https://veto-ai.com").replace(/\/$/, "");
    this.apiKey = opts.apiKey;
  }

  async authorize(req: AuthorizeRequest): Promise<AuthorizeResponse> {
    const res = await fetch(`${this.baseUrl}/api/v1/authorize/`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Veto-Api-Key": this.apiKey,
        "User-Agent": "veto-agent-scaffold/0.6",
      },
      body: JSON.stringify(req),
    });
    const text = await res.text();
    let body: any;
    try { body = JSON.parse(text); }
    catch { throw new VetoError(`Veto returned non-JSON ${res.status}: ${text.slice(0, 200)}`, res.status); }

    if (res.ok) return body as AuthorizeResponse;
    if (body && typeof body.status === "string" &&
        ["approved", "denied", "escalated", "executed", "failed"].includes(body.status)) {
      return body as AuthorizeResponse;
    }
    throw new VetoError(body?.error ?? `Veto API error ${res.status}`, res.status, body);
  }
}

export class VetoError extends Error {
  constructor(message: string, public statusCode?: number, public body?: any) {
    super(message);
    this.name = "VetoError";
  }
}

// ── Singleton accessors ─────────────────────────────────────────────
// Tools call these instead of importing env directly, so swapping the
// Veto endpoint or rotating the key only happens in one place.

let _client: VetoClient | null = null;

export function vetoClient(): VetoClient {
  if (_client) return _client;
  const apiKey = process.env.VETO_API_KEY;
  if (!apiKey) throw new Error("VETO_API_KEY is not set. Run `veto register` and add the key to .env.");
  _client = new VetoClient({
    baseUrl: process.env.VETO_BASE_URL,
    apiKey,
  });
  return _client;
}

export function agentId(): string {
  const id = process.env.VETO_AGENT_ID;
  if (!id) throw new Error("VETO_AGENT_ID is not set. Add it to .env after running `veto register`.");
  return id;
}
