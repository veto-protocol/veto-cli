/**
 * MEMORY — in-memory conversation history.
 *
 * Stores the running list of messages between user and agent. Used by
 * `brain.ts` to build the LLM context window on each turn.
 *
 * v0.6: in-memory only (lost on restart).
 * Future: SQLite for durable history; vector store for semantic recall.
 */

import { config } from "./config.js";

export type Message = {
  role: "user" | "assistant";
  content: string;
  ts: number;
};

class ConversationMemory {
  private history: Message[] = [];

  push(m: Omit<Message, "ts">): void {
    this.history.push({ ...m, ts: Date.now() });
  }

  /** Return the last N user/assistant turns for the LLM context window. */
  recent(): Message[] {
    const turns = config.contextTurns;
    return this.history.slice(-turns * 2);
  }

  all(): Message[] {
    return [...this.history];
  }

  size(): number {
    return this.history.length;
  }
}

export const memory = new ConversationMemory();
