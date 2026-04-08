"""
Archon configuration — cross-platform path resolution.

All paths resolve through ARCHON_DATA_DIR (default: ~/.archon).
Override with environment variable: ARCHON_DATA_DIR=/path/to/data

Platform defaults:
  Windows: C:\\Users\\<user>\\.archon
  macOS:   /Users/<user>/.archon
  Linux:   /home/<user>/.archon
"""
from __future__ import annotations

import os
import platform
from pathlib import Path

_OS = platform.system()  # "Windows", "Linux", "Darwin"


def data_dir() -> Path:
    """Root data directory for Archon (graph DB, face models, etc.)"""
    env = os.getenv("ARCHON_DATA_DIR")
    if env:
        return Path(env)
    return Path.home() / ".archon"


def graph_dir() -> Path:
    return data_dir() / "graph"


def neo4j_data_dir() -> Path:
    return graph_dir() / "neo4j" / "data"


def neo4j_logs_dir() -> Path:
    return graph_dir() / "neo4j" / "logs"


def neo4j_plugins_dir() -> Path:
    return graph_dir() / "neo4j" / "plugins"


def kuzu_db_dir() -> Path:
    return graph_dir() / "kuzu"


def face_models_dir() -> Path:
    return data_dir() / "models" / "face"


def voice_transcripts_dir() -> Path:
    return data_dir() / "voice-transcripts"


def ensure_dirs() -> None:
    """Create all required data directories."""
    for d in [
        data_dir(), graph_dir(),
        neo4j_data_dir(), neo4j_logs_dir(), neo4j_plugins_dir(),
        kuzu_db_dir(), face_models_dir(), voice_transcripts_dir(),
    ]:
        d.mkdir(parents=True, exist_ok=True)


def is_windows() -> bool: return _OS == "Windows"
def is_macos()   -> bool: return _OS == "Darwin"
def is_linux()   -> bool: return _OS == "Linux"


# Env var overrides with cross-platform defaults
NEO4J_URI      = os.getenv("NEO4J_URI",      "bolt://localhost:7687")
NEO4J_USER     = os.getenv("NEO4J_USER",     "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "archon-local")
GRAPH_BACKEND  = os.getenv("GRAPH_BACKEND",  "neo4j")

OLLAMA_BASE_URL        = os.getenv("OLLAMA_BASE_URL",        "http://localhost:11434")
OLLAMA_SUMMARY_MODEL   = os.getenv("OLLAMA_SUMMARY_MODEL",   "llama3.2")
OLLAMA_VISION_MODEL    = os.getenv("OLLAMA_VISION_MODEL",    "llava")
OLLAMA_CODE_MODEL      = os.getenv("OLLAMA_CODE_MODEL",      "qwen2.5-coder:32b")
OLLAMA_REASON_MODEL    = os.getenv("OLLAMA_REASON_MODEL",    "deepseek-r1:32b")

NAS_DRY_RUN = os.getenv("NAS_DRY_RUN", "true").lower() == "true"
