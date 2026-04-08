"""
Archon Interactive Onboarding
──────────────────────────────
One command to go from nothing to a running, configured agent:

  python -m src.onboarding

Covers:
  1. PQC credential store initialization
  2. File share discovery + credential setup (SMB/NFS/local)
  3. Synology NAS detection + Download Station config
  4. Ollama connectivity check
  5. Neo4j / Docker check
  6. First index run (optional)
  7. Writes .env with non-sensitive config only
"""
from __future__ import annotations

import getpass
import json
import os
import platform
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

# ── Terminal helpers ──────────────────────────────────────────────────────────

RESET  = "\033[0m"
BOLD   = "\033[1m"
GREEN  = "\033[32m"
YELLOW = "\033[33m"
RED    = "\033[31m"
CYAN   = "\033[36m"
DIM    = "\033[2m"

def ok(msg):    print(f"  {GREEN}✅{RESET} {msg}")
def warn(msg):  print(f"  {YELLOW}⚠️ {RESET} {msg}")
def err(msg):   print(f"  {RED}✗{RESET} {msg}")
def info(msg):  print(f"  {CYAN}ℹ{RESET}  {msg}")
def header(msg): print(f"\n{BOLD}{CYAN}{msg}{RESET}\n{'─' * len(msg)}")
def dim(msg):   print(f"  {DIM}{msg}{RESET}")

def ask(prompt: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    val = input(f"  {BOLD}{prompt}{suffix}: {RESET}").strip()
    return val if val else default

def ask_secret(prompt: str) -> str:
    return getpass.getpass(f"  {BOLD}{prompt}: {RESET}")

def ask_bool(prompt: str, default: bool = True) -> bool:
    suffix = "[Y/n]" if default else "[y/N]"
    val = input(f"  {BOLD}{prompt} {suffix}: {RESET}").strip().lower()
    if not val:
        return default
    return val in ("y", "yes", "1", "true")

def separator():
    print(f"\n{DIM}{'─' * 50}{RESET}")


# ── Network helpers ───────────────────────────────────────────────────────────

def scan_smb_hosts(subnet: str = "") -> list[str]:
    """Quick scan for SMB hosts on the local network."""
    found = []
    try:
        if not subnet:
            # Get local subnet from hostname
            local_ip = socket.gethostbyname(socket.gethostname())
            parts = local_ip.split(".")
            subnet = ".".join(parts[:3])

        for i in range(1, 255):
            host = f"{subnet}.{i}"
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(0.1)
            result = sock.connect_ex((host, 445))
            sock.close()
            if result == 0:
                try:
                    hostname = socket.gethostbyaddr(host)[0]
                except Exception:
                    hostname = host
                found.append(f"{host} ({hostname})")
    except Exception:
        pass
    return found


def check_port(host: str, port: int, timeout: float = 2.0) -> bool:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    result = sock.connect_ex((host, port))
    sock.close()
    return result == 0


def detect_synology(ip: str) -> dict | None:
    """Try to detect a Synology DSM at the given IP."""
    try:
        import httpx
        for port in (5000, 5001, 80, 443):
            try:
                scheme = "https" if port in (5001, 443) else "http"
                r = httpx.get(
                    f"{scheme}://{ip}:{port}/webapi/auth.cgi?api=SYNO.API.Info&version=1&method=query",
                    timeout=3, verify=False
                )
                if r.status_code == 200 and "SYNO" in r.text:
                    return {"host": ip, "port": port, "scheme": scheme,
                            "url": f"{scheme}://{ip}:{port}"}
            except Exception:
                continue
    except ImportError:
        pass
    return None


# ── Onboarding steps ──────────────────────────────────────────────────────────

def step_credentials() -> bool:
    """Initialize PQC credential store."""
    header("Step 1: Secure Credential Store")
    info("Archon stores all sensitive credentials encrypted with ML-KEM-768 (NIST PQC).")
    info("Your credentials are never stored in plain text.\n")

    try:
        from src.credentials import CredentialStore, _key_file
        if CredentialStore.initialized():
            ok("Credential store already initialized")
            if ask_bool("Re-initialize (this will erase stored credentials)?", False):
                _key_file().unlink(missing_ok=True)
                from src.credentials import _cred_file
                _cred_file().unlink(missing_ok=True)
            else:
                return True

        print("  Creating ML-KEM-768 keypair. Choose a strong passphrase.")
        print("  You'll need this passphrase to access credentials.\n")
        from src.credentials import _load_or_create_keypair
        _load_or_create_keypair()
        ok("Credential store initialized")
        return True
    except Exception as e:
        err(f"Failed: {e}")
        return False


def step_file_shares(cred_store) -> list[dict]:
    """Discover and configure file shares."""
    header("Step 2: File Shares")
    shares = []

    print("  How do you want to access your files?\n")
    print("    1. Local path (folder on this machine)")
    print("    2. SMB/CIFS share (Synology, Windows, Samba)")
    print("    3. NFS export")
    print("    4. Skip for now\n")

    choice = ask("Choose", "2")

    if choice == "1":
        path = ask("Local folder path", str(Path.home()))
        if Path(path).exists():
            shares.append({"type": "local", "uri": path, "label": Path(path).name})
            ok(f"Local path: {path}")
        else:
            err(f"Path not found: {path}")

    elif choice == "2":
        print("\n  Scanning local network for SMB hosts (takes ~5 seconds)...")
        hosts = scan_smb_hosts()

        if hosts:
            print(f"\n  Found {len(hosts)} SMB host(s):")
            for i, h in enumerate(hosts, 1):
                print(f"    {i}. {h}")
            print(f"    {len(hosts)+1}. Enter manually\n")
            sel = ask("Select host", "1")
            if sel.isdigit() and 1 <= int(sel) <= len(hosts):
                host = hosts[int(sel)-1].split(" ")[0]
            else:
                host = ask("SMB host IP or hostname")
        else:
            warn("No SMB hosts found on local network")
            host = ask("SMB host IP or hostname")

        if host:
            share = ask("Share name", "media")
            subpath = ask("Sub-path within share (optional)", "")
            user = ask("Username")
            password = ask_secret("Password")
            domain = ask("Domain (leave blank for local accounts)", "")

            uri = f"smb://{user}:{password}@{host}/{share}"
            if subpath:
                uri += f"/{subpath.lstrip('/')}"

            # Validate connection
            print(f"\n  Testing connection to {host}...")
            try:
                import smbclient
                smbclient.register_session(
                    host,
                    username=f"{domain}\\{user}" if domain else user,
                    password=password,
                    port=445,
                )
                ok(f"Connected to {host}")
                smbclient.delete_session(host)
            except Exception as e:
                warn(f"Could not verify connection: {e}")
                if not ask_bool("Continue anyway?", True):
                    return shares

            # Store credentials encrypted
            cred_store.set("SMB_HOST", host)
            cred_store.set("SMB_SHARE", share)
            cred_store.set("SMB_USER", user)
            cred_store.set("SMB_PASS", password)
            if domain:
                cred_store.set("SMB_DOMAIN", domain)

            # Store URI without credentials for config
            safe_uri = f"smb://{user}@{host}/{share}"
            if subpath:
                safe_uri += f"/{subpath.lstrip('/')}"

            shares.append({
                "type": "smb", "uri": safe_uri,
                "label": f"{host}/{share}", "host": host
            })
            ok(f"SMB share configured: {host}/{share}")

    elif choice == "3":
        host = ask("NFS server IP or hostname")
        export = ask("Export path", "/volume1/media")
        version = ask("NFS version", "3")

        uri = f"nfs://{host}{export}"
        cred_store.set("NFS_HOST", host)
        cred_store.set("NFS_EXPORT", export)

        shares.append({
            "type": "nfs", "uri": uri,
            "label": f"{host}{export}", "host": host
        })
        ok(f"NFS export configured: {host}{export}")

    return shares


def step_synology(cred_store, smb_hosts: list[str]) -> dict | None:
    """Detect and configure Synology Download Station."""
    header("Step 3: Synology Download Station (optional)")
    print("  This enables the torrent hunter agent to send downloads to your NAS.\n")

    if not ask_bool("Configure Synology Download Station?", True):
        info("Skipped")
        return None

    # Try to auto-detect from known SMB hosts
    synology = None
    if smb_hosts:
        print("  Scanning for Synology DSM...")
        for host_str in smb_hosts:
            ip = host_str.split(" ")[0]
            result = detect_synology(ip)
            if result:
                ok(f"Found Synology DSM at {result['url']}")
                synology = result
                break

    if not synology:
        ip = ask("Synology IP or hostname")
        port = ask("DSM port", "5000")
        scheme = "https" if port == "5001" else "http"
        synology = {"host": ip, "port": int(port), "scheme": scheme,
                    "url": f"{scheme}://{ip}:{port}"}

    dsm_user = ask("DSM username", "admin")
    dsm_pass = ask_secret("DSM password")

    # Test DSM auth
    print(f"\n  Testing DSM authentication...")
    try:
        import httpx
        r = httpx.get(
            f"{synology['url']}/webapi/auth.cgi",
            params={
                "api": "SYNO.API.Auth", "version": "3",
                "method": "login", "account": dsm_user,
                "passwd": dsm_pass, "session": "test", "format": "cookie"
            },
            timeout=5, verify=False
        )
        data = r.json()
        if data.get("success"):
            ok("DSM authentication successful")
        else:
            warn(f"Auth failed: {data.get('error', {}).get('code', 'unknown')}")
            if not ask_bool("Continue anyway?", True):
                return None
    except Exception as e:
        warn(f"Could not test connection: {e}")

    tv_dir  = ask("TV downloads folder", "/volume1/downloads/tv")
    mov_dir = ask("Movie downloads folder", "/volume1/downloads/movies")

    cred_store.set("SYNOLOGY_HOST", synology["url"])
    cred_store.set("SYNOLOGY_USER", dsm_user)
    cred_store.set("SYNOLOGY_PASS", dsm_pass)
    cred_store.set("DS_DOWNLOAD_DIR_TV", tv_dir)
    cred_store.set("DS_DOWNLOAD_DIR_MOVIES", mov_dir)

    ok("Synology Download Station configured")
    return synology


def step_ollama() -> bool:
    """Check Ollama connectivity and models."""
    header("Step 4: Local AI Models (Ollama)")
    print("  Checking Ollama...\n")

    ollama_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

    try:
        import httpx
        r = httpx.get(f"{ollama_url}/api/tags", timeout=5)
        if r.status_code != 200:
            raise Exception("non-200 response")
        models = [m["name"] for m in r.json().get("models", [])]
        ok(f"Ollama running at {ollama_url}")
    except Exception:
        err("Ollama not running or not reachable at " + ollama_url)
        warn("Start Ollama and re-run, or install from https://ollama.ai")
        return False

    required = {
        "llama3.2": "General tasks (fast)",
        "llava": "Image/video analysis",
        "qwen2.5-coder:32b": "Code analysis",
        "deepseek-r1:32b": "Reasoning",
    }

    ollama_cmd = shutil.which("ollama")
    if not ollama_cmd:
        _OS = platform.system()
        candidates = {
            "Windows": Path(os.getenv("LOCALAPPDATA","")) / "Programs/Ollama/ollama.exe",
            "Darwin":  Path("/usr/local/bin/ollama"),
            "Linux":   Path("/usr/bin/ollama"),
        }
        c = candidates.get(_OS)
        if c and c.exists():
            ollama_cmd = str(c)

    for model, desc in required.items():
        short = model.split(":")[0]
        has_model = any(short in m for m in models)
        if has_model:
            ok(f"{model} — {desc}")
        else:
            warn(f"{model} not found — {desc}")
            if ollama_cmd and ask_bool(f"  Pull {model} now? (~10-20GB)", True):
                print(f"  Pulling {model}...")
                subprocess.run([ollama_cmd, "pull", model], check=False)
            else:
                info(f"  Run later: ollama pull {model}")

    return True


def step_graph_db() -> bool:
    """Check Neo4j / Docker."""
    header("Step 5: Knowledge Graph Database (Neo4j)")
    print("  Archon uses Neo4j to store the file knowledge graph.\n")

    # Check if Neo4j is already running
    if check_port("localhost", 7687):
        ok("Neo4j is running (port 7687)")
        info("Browser UI: http://localhost:7474  (neo4j / archon-local)")
        return True

    # Check Docker
    docker = shutil.which("docker")
    if not docker:
        err("Docker not found — install Docker Desktop from https://docker.com")
        return False

    # Check Docker daemon
    result = subprocess.run(
        [docker, "info"], capture_output=True, timeout=5
    )
    if result.returncode != 0:
        err("Docker daemon not running — start Docker Desktop")
        return False

    ok("Docker is running")

    if ask_bool("Start Neo4j now?", True):
        archon_data = os.getenv("ARCHON_DATA_DIR", str(Path.home() / ".archon"))
        env = {**os.environ, "ARCHON_DATA_DIR": archon_data}
        here = Path(__file__).parent.parent
        result = subprocess.run(
            [docker, "compose", "up", "-d"],
            cwd=str(here), env=env, capture_output=True, text=True
        )
        if result.returncode == 0:
            ok("Neo4j started")
            info("Waiting for Neo4j to be ready...")
            for _ in range(20):
                if check_port("localhost", 7687):
                    ok("Neo4j ready — http://localhost:7474")
                    info("Login: neo4j / archon-local")
                    return True
                time.sleep(2)
            warn("Neo4j starting slowly — check http://localhost:7474")
        else:
            err(f"docker compose failed: {result.stderr[:200]}")

    return False


def step_first_index(shares: list[dict]) -> None:
    """Offer to run first index."""
    header("Step 6: First Index Run")

    if not shares:
        info("No file shares configured — skipping index")
        return

    print("  Ready to start indexing your files into the knowledge graph.")
    print("  This can take a while for large libraries but is resumable.\n")

    for i, share in enumerate(shares, 1):
        print(f"    {i}. {share['label']} ({share['type']})")

    if not ask_bool("\n  Start first index run now?", False):
        info("Skipped. Run later: python -m src.onboarding --index")
        info("Or via MCP: graph_index_source(source=...)")
        return

    sel = ask("Which share to index first", "1")
    if not sel.isdigit() or not (1 <= int(sel) <= len(shares)):
        return

    share = shares[int(sel) - 1]
    dry = ask_bool("Dry run first (no writes)?", True)

    print(f"\n  Starting {'dry run' if dry else 'index'} of {share['label']}...")
    print("  Press Ctrl+C to interrupt — progress is saved and resumable.\n")

    try:
        from src.pipeline.indexer import ArchonIndexer
        indexer = ArchonIndexer(
            enrich_llm=False,    # Skip LLM on first pass for speed
            enrich_vision=False,
            enrich_faces=False,
            enrich_api=True,
            dry_run=dry,
            on_progress=lambda r: print(
                f"  {'✅' if r.success else '✗'} {Path(r.path).name[:50]} "
                f"({r.duration_ms}ms)",
                end="\r"
            ),
        )
        stats = indexer.index(share["uri"])
        print()
        ok(f"Indexed {stats['files_indexed']:,} files in {stats['duration_secs']}s "
           f"({stats['files_per_second']:.0f} files/sec)")
        if stats.get("errors"):
            warn(f"{stats['errors']} errors — run status to see details")
    except KeyboardInterrupt:
        print()
        ok("Interrupted — progress saved. Resume with: python -m src.onboarding --resume")


def step_write_env(shares: list[dict], synology: dict | None) -> None:
    """Write non-sensitive config to .env."""
    here = Path(__file__).parent.parent
    env_file = here / ".env"

    lines = [
        "# Archon configuration (non-sensitive)\n",
        "# Sensitive credentials are stored in ~/.archon/credentials.enc\n\n",
        f"ARCHON_DATA_DIR={Path.home() / '.archon'}\n",
        "GRAPH_BACKEND=neo4j\n",
        "NEO4J_URI=bolt://localhost:7687\n",
        "NEO4J_USER=neo4j\n",
        "# NEO4J_PASSWORD is in credential store\n\n",
        "OLLAMA_BASE_URL=http://localhost:11434\n",
        "OLLAMA_SUMMARY_MODEL=llama3.2\n",
        "OLLAMA_VISION_MODEL=llava\n",
        "OLLAMA_CODE_MODEL=qwen2.5-coder:32b\n",
        "OLLAMA_REASON_MODEL=deepseek-r1:32b\n\n",
        "NAS_DRY_RUN=true\n",
    ]

    if shares:
        first = shares[0]
        lines.append(f"\n# Primary file share\n")
        # Store URI without password
        uri = first["uri"]
        lines.append(f"NAS_ROOT={uri}\n")

    if synology:
        lines.append(f"\n# Synology (credentials in secure store)\n")
        lines.append(f"SYNOLOGY_HOST={synology['url']}\n")

    with open(env_file, "w") as f:
        f.writelines(lines)

    ok(f".env written (non-sensitive config only): {env_file}")
    info("Sensitive credentials are in ~/.archon/credentials.enc (PQC encrypted)")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Archon onboarding")
    parser.add_argument("--index", action="store_true",
                        help="Run indexer directly (skip onboarding steps)")
    parser.add_argument("--resume", action="store_true",
                        help="Resume a previous index run")
    parser.add_argument("--status", action="store_true",
                        help="Show index status")
    args = parser.parse_args()

    if args.status:
        from src.pipeline.indexer import ArchonIndexer
        status = ArchonIndexer().status()
        print(json.dumps(status, indent=2))
        return

    if args.resume:
        from src.pipeline.indexer import ArchonIndexer
        print("Resuming previous index run...")
        stats = ArchonIndexer().resume("default")
        print(json.dumps(stats, indent=2))
        return

    print(f"\n{BOLD}{CYAN}╔══════════════════════════════════╗")
    print(f"║   🔧 Archon Setup & Onboarding  ║")
    print(f"╚══════════════════════════════════╝{RESET}\n")
    print(f"  Platform: {platform.system()} {platform.machine()}")
    print(f"  Python:   {sys.version.split()[0]}")
    print(f"  Data dir: {Path.home() / '.archon'}\n")

    # Run steps
    step_credentials()

    from src.credentials import CredentialStore
    CredentialStore.unlock()

    smb_hosts: list[str] = []
    shares = step_file_shares(CredentialStore)
    if shares:
        smb_hosts = [s.get("host", "") for s in shares if s.get("host")]

    synology = step_synology(CredentialStore, smb_hosts)
    step_ollama()
    graph_ok = step_graph_db()

    if graph_ok:
        step_first_index(shares)

    step_write_env(shares, synology)

    separator()
    print(f"\n{BOLD}{GREEN}✅ Archon setup complete!{RESET}\n")
    print(f"  Start MCP server: {CYAN}uv run python -m src.mcp_server{RESET}")
    print(f"  Start REST API:   {CYAN}uv run uvicorn src.api.main:app --reload{RESET}")
    print(f"  Check status:     {CYAN}python -m src.onboarding --status{RESET}")
    print(f"  Resume index:     {CYAN}python -m src.onboarding --resume{RESET}")
    print(f"  Neo4j browser:    {CYAN}http://localhost:7474{RESET}\n")


if __name__ == "__main__":
    main()
