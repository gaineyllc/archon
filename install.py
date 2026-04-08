#!/usr/bin/env python3
"""
Archon cross-platform setup script.
Run once after cloning: python install.py

Does:
  1. Creates ~/.archon directory structure
  2. Copies .env.example → .env (if not exists)
  3. Pulls required Ollama models
  4. Starts Neo4j via Docker (if Docker is running)
  5. Prints next steps
"""
from __future__ import annotations
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

_OS = platform.system()
_HERE = Path(__file__).parent


def run(cmd: list[str], check: bool = True, **kwargs) -> subprocess.CompletedProcess:
    print(f"  $ {' '.join(cmd)}")
    return subprocess.run(cmd, check=check, **kwargs)


def data_dir() -> Path:
    env = os.getenv("ARCHON_DATA_DIR")
    return Path(env) if env else Path.home() / ".archon"


def main():
    print("\n🔧 Archon Setup\n" + "─" * 40)
    print(f"Platform : {_OS} ({platform.machine()})")
    print(f"Python   : {sys.version.split()[0]}")
    print(f"Data dir : {data_dir()}\n")

    # ── 1. Data directories ────────────────────────────────────────────────
    print("1. Creating data directories...")
    dirs = [
        data_dir() / "graph" / "neo4j" / "data",
        data_dir() / "graph" / "neo4j" / "logs",
        data_dir() / "graph" / "neo4j" / "plugins",
        data_dir() / "graph" / "kuzu",
        data_dir() / "models" / "face",
        data_dir() / "voice-transcripts",
    ]
    for d in dirs:
        d.mkdir(parents=True, exist_ok=True)
    print("   ✅ Done\n")

    # ── 2. .env file ───────────────────────────────────────────────────────
    print("2. Setting up .env...")
    env_file = _HERE / ".env"
    env_example = _HERE / ".env.example"
    if not env_file.exists() and env_example.exists():
        shutil.copy(env_example, env_file)
        print("   ✅ Copied .env.example → .env — edit it with your credentials\n")
    else:
        print("   ✅ .env already exists\n")

    # ── 3. Python deps ─────────────────────────────────────────────────────
    print("3. Installing Python dependencies...")
    uv = shutil.which("uv")
    if uv:
        run([uv, "sync"], cwd=str(_HERE))
    else:
        print("   ⚠️  uv not found — install from https://astral.sh/uv")
        print("      Falling back to pip...")
        run([sys.executable, "-m", "pip", "install", "-e", "."], cwd=str(_HERE))
    print("   ✅ Done\n")

    # ── 4. Ollama models ───────────────────────────────────────────────────
    print("4. Pulling Ollama models...")
    ollama = shutil.which("ollama")
    if not ollama:
        # Check common install locations
        candidates = {
            "Windows": [
                Path(os.getenv("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe"
            ],
            "Darwin":  [Path("/usr/local/bin/ollama"), Path("/opt/homebrew/bin/ollama")],
            "Linux":   [Path("/usr/bin/ollama"), Path("/usr/local/bin/ollama")],
        }.get(_OS, [])
        for c in candidates:
            if c.exists():
                ollama = str(c)
                break

    if ollama:
        models = ["llama3.2", "llava", "qwen2.5-coder:32b", "deepseek-r1:32b"]
        for model in models:
            print(f"   Pulling {model}...")
            run([ollama, "pull", model], check=False)
        print("   ✅ Done\n")
    else:
        print("   ⚠️  Ollama not found — install from https://ollama.ai\n"
              "       Then run: ollama pull llama3.2 llava qwen2.5-coder:32b deepseek-r1:32b\n")

    # ── 5. Neo4j via Docker ────────────────────────────────────────────────
    print("5. Starting Neo4j (Docker)...")
    docker = shutil.which("docker")
    if docker:
        env = {**os.environ, "ARCHON_DATA_DIR": str(data_dir())}
        result = run(
            [docker, "compose", "up", "-d"],
            cwd=str(_HERE), check=False, env=env
        )
        if result.returncode == 0:
            print("   ✅ Neo4j started — browser at http://localhost:7474")
            print("      Login: neo4j / archon-local\n")
        else:
            print("   ⚠️  Docker compose failed — start Docker Desktop and re-run\n")
    else:
        print("   ⚠️  Docker not found — install Docker Desktop\n"
              "       Then run: docker compose up -d\n")

    # ── 6. Platform-specific notes ─────────────────────────────────────────
    print("6. Platform notes:")
    if _OS == "Windows":
        print("   • NFS requires 'Services for NFS' Windows feature")
        print("     Enable: Settings → Apps → Optional Features → NFS Client")
        print("   • CUDA Toolkit recommended for GPU acceleration")
        print("     Download: https://developer.nvidia.com/cuda-downloads")
    elif _OS == "Darwin":
        print("   • InsightFace runs on CPU (Metal/MPS not supported by ONNX)")
        print("   • Ollama uses Metal GPU acceleration natively")
        print("   • NFS: mount -t nfs (requires root)")
    elif _OS == "Linux":
        print("   • Install nfs-common for NFS support: sudo apt install nfs-common")
        print("   • CUDA: install nvidia-driver + cuda-toolkit for GPU acceleration")
        print("   • NVIDIA Container Toolkit needed for GPU in Docker")

    print("\n✅ Setup complete!")
    print("\nNext steps:")
    print("  1. Edit .env with your NAS/IPTorrents/Synology credentials")
    print("  2. Start MCP server: uv run python -m src.mcp_server")
    print("  3. Or start REST API: uv run uvicorn src.api.main:app --reload")
    print(f"\nData stored in: {data_dir()}")
    print("Neo4j browser: http://localhost:7474\n")


if __name__ == "__main__":
    main()
