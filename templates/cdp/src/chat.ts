/**
 * CHAT MODE — CLI REPL.
 *
 * Used for local development and any user who wants to talk to their agent
 * directly from the terminal. Reads stdin, sends to brain, prints reply.
 */

import { createInterface } from "node:readline/promises";
import { stdin as input, stdout as output } from "node:process";
import { config } from "./config.js";
import { respond } from "./brain.js";

const C = {
  cyan: "\x1b[96m",
  green: "\x1b[1;92m",
  dim: "\x1b[2m",
  bold: "\x1b[1m",
  reset: "\x1b[0m",
};

export async function runChat(): Promise<void> {
  const rl = createInterface({ input, output });

  console.log("");
  console.log(`  ${C.bold}${C.cyan}${config.agentName}${C.reset} ${C.dim}— governed by Veto${C.reset}`);
  console.log(`  ${C.dim}Type a message to talk. Ctrl+C to exit.${C.reset}`);
  console.log("");

  while (true) {
    let userMessage: string;
    try {
      userMessage = (await rl.question(`${C.cyan}> ${C.reset}`)).trim();
    } catch {
      // SIGINT / EOF
      break;
    }
    if (!userMessage) continue;
    if (userMessage === "/exit" || userMessage === "/quit") break;

    process.stdout.write(`${C.dim}thinking…${C.reset}\r`);
    let reply: string;
    try {
      reply = await respond(userMessage);
    } catch (err: any) {
      reply = `${C.dim}[error]${C.reset} ${err?.message ?? String(err)}`;
    }
    // Clear the "thinking..." line
    process.stdout.write("\x1b[2K\r");

    console.log("");
    console.log(reply);
    console.log("");
  }

  rl.close();
  console.log("");
  console.log(`  ${C.dim}Goodbye.${C.reset}`);
}
