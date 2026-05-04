/**
 * SERVER MODE — HTTP server for 24/7 deployments.
 *
 * Exposes:
 *   POST /chat           { message: string }  →  { reply: string }
 *   GET  /health                              →  { ok: true, agent, history_size }
 *
 * Use this when the agent runs on Fly.io / Modal / Replit / your VPS / etc.
 * The user sends messages via curl, a web UI, a Slack/Telegram webhook, or
 * any HTTP client. The agent reasons + calls tools + responds.
 *
 * v0.6: no auth on /chat. For production, add an API key check OR put this
 * behind your own auth proxy. Anyone who can hit your /chat endpoint can
 * spend up to your Veto policy caps.
 */

import express from "express";
import { config } from "./config.js";
import { respond } from "./brain.js";
import { memory } from "./memory.js";

export async function runServer(): Promise<void> {
  const app = express();
  app.use(express.json({ limit: "1mb" }));

  const port = parseInt(process.env.PORT ?? "8080", 10);

  app.get("/health", (_req, res) => {
    res.json({
      ok: true,
      agent: config.agentName,
      history_size: memory.size(),
      uptime_s: Math.round(process.uptime()),
    });
  });

  app.post("/chat", async (req, res) => {
    const message = String(req.body?.message ?? "").trim();
    if (!message) {
      res.status(400).json({ error: "Missing 'message' string in body" });
      return;
    }
    try {
      const reply = await respond(message);
      res.json({ reply });
    } catch (err: any) {
      console.error(`/chat error: ${err?.message ?? err}`);
      res.status(500).json({ error: err?.message ?? "internal" });
    }
  });

  app.listen(port, () => {
    console.log("");
    console.log(`  \x1b[1;96m${config.agentName}\x1b[0m \x1b[2m— governed by Veto, listening on port ${port}\x1b[0m`);
    console.log(`  \x1b[2mEndpoints: POST /chat   GET /health\x1b[0m`);
    console.log("");
  });
}
