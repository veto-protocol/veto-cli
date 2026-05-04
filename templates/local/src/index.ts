/**
 * Entry point. Mode-aware:
 *   MODE=chat    → CLI REPL (default for local dev)
 *   MODE=server  → HTTP server (for 24/7 deployment on Fly / Modal / Railway / etc.)
 *
 * To customize what your agent does:
 *   • Persona / system prompt   →  src/persona.ts
 *   • Available tools           →  src/tools/*.ts (and src/tools/index.ts to register)
 *   • Brain / LLM               →  src/brain.ts (default: Anthropic Claude)
 *   • Wallet / x402 settlement  →  src/settler.ts (CDP smart account)
 *
 * To deploy 24/7, see README.md → Deploy section.
 */

import "dotenv/config";

const mode = (process.env.MODE ?? "chat").toLowerCase();

async function main(): Promise<void> {
  if (mode === "server") {
    const { runServer } = await import("./server.js");
    await runServer();
  } else if (mode === "chat") {
    const { runChat } = await import("./chat.js");
    await runChat();
  } else {
    console.error(`Unknown MODE: ${mode}. Set MODE=chat or MODE=server in .env.`);
    process.exit(1);
  }
}

main().catch((err) => {
  console.error("");
  console.error(`  \x1b[1;91m✗ Fatal:\x1b[0m ${err?.message ?? String(err)}`);
  if (err?.stack) console.error(err.stack);
  process.exit(99);
});
