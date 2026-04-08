#!/usr/bin/env node
/**
 * onyx-agent MCP server launcher
 *
 * Finds the Python interpreter in the uv venv and starts the MCP server
 * in stdio mode (default) or HTTP/SSE mode (--http flag).
 *
 * Usage:
 *   npx onyx-agent                 # stdio — use with Claude Desktop
 *   npx onyx-agent --http          # HTTP/SSE on port 8765
 *   npx onyx-agent --install       # run `uv sync` to set up Python deps
 */

const { spawn } = require("child_process");
const path = require("path");
const fs = require("fs");
const os = require("os");

const ROOT = path.resolve(__dirname, "..");
const IS_WIN = process.platform === "win32";

// Find uv (package manager) — prefers local .venv, falls back to system uv
function findPython() {
  const venvPy = IS_WIN
    ? path.join(ROOT, ".venv", "Scripts", "python.exe")
    : path.join(ROOT, ".venv", "bin", "python");
  if (fs.existsSync(venvPy)) return venvPy;
  return IS_WIN ? "python" : "python3";
}

function findUv() {
  const candidates = [
    path.join(os.homedir(), ".local", "bin", IS_WIN ? "uv.exe" : "uv"),
    "uv",
  ];
  for (const c of candidates) {
    try { fs.accessSync(c, fs.constants.X_OK); return c; } catch {}
  }
  return "uv";
}

const args = process.argv.slice(2);

// --install: run uv sync
if (args.includes("--install")) {
  const uv = findUv();
  console.error("[onyx-agent] Installing Python dependencies via uv sync...");
  const proc = spawn(uv, ["sync"], { cwd: ROOT, stdio: "inherit" });
  proc.on("exit", (code) => process.exit(code ?? 0));
  return;
}

// Default: launch MCP server
const python = findPython();
const mcpArgs = ["-m", "src.mcp_server", ...args];

const proc = spawn(python, mcpArgs, {
  cwd: ROOT,
  stdio: "inherit",
  env: { ...process.env },
});

proc.on("exit", (code) => process.exit(code ?? 0));
proc.on("error", (err) => {
  console.error(`[onyx-agent] Failed to start MCP server: ${err.message}`);
  console.error("Run: npx onyx-agent --install");
  process.exit(1);
});
