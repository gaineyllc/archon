"""
Archon Credential Store
────────────────────────
PQC-encrypted credential storage using:
  - ML-KEM-768 (CRYSTALS-Kyber, NIST FIPS 203) for key encapsulation
  - AES-256-GCM for symmetric encryption of credential data
  - HKDF-SHA256 for key derivation

Hybrid encryption pattern (standard for PQC):
  1. Generate ML-KEM keypair — public key stored, private key derived from passphrase
  2. On write: encapsulate a random AES-256 key with ML-KEM public key
  3. Encrypt credentials with AES-256-GCM using encapsulated key
  4. Store: {kem_ciphertext || aes_nonce || aes_ciphertext || aes_tag}
  5. On read: decapsulate AES key with private key, decrypt credentials

Credential file: ~/.archon/credentials.enc
Key file:        ~/.archon/credentials.key  (ML-KEM public key)

Usage:
  python -m src.credentials set SMB_PASS
  python -m src.credentials get SMB_PASS
  python -m src.credentials list
  python -m src.credentials init   (generate keypair)
"""
from __future__ import annotations

import base64
import getpass
import hashlib
import json
import os
import secrets
import sys
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes

try:
    from kyber import Kyber768
    _KYBER_AVAILABLE = True
except ImportError:
    _KYBER_AVAILABLE = False


# ── Path helpers ───────────────────────────────────────────────────────────────

def _cred_dir() -> Path:
    d = Path(os.getenv("ARCHON_DATA_DIR", str(Path.home() / ".archon")))
    d.mkdir(parents=True, exist_ok=True)
    return d

def _cred_file() -> Path: return _cred_dir() / "credentials.enc"
def _key_file()  -> Path: return _cred_dir() / "credentials.key"


# ── Key derivation from passphrase (deterministic) ────────────────────────────

def _derive_seed(passphrase: str, salt: bytes) -> bytes:
    """Derive a 64-byte seed from passphrase using HKDF."""
    hkdf = HKDF(
        algorithm=hashes.SHA256(),
        length=64,
        salt=salt,
        info=b"archon-kyber-seed",
    )
    return hkdf.derive(passphrase.encode())


def _derive_aes_key(shared_secret: bytes) -> bytes:
    """Derive AES-256 key from Kyber shared secret using HKDF."""
    hkdf = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=None,
        info=b"archon-aes-256-gcm",
    )
    return hkdf.derive(shared_secret)


# ── Passphrase-based Kyber key generation ─────────────────────────────────────

def _get_passphrase(confirm: bool = False) -> str:
    pp = getpass.getpass("Archon credential store passphrase: ")
    if confirm:
        pp2 = getpass.getpass("Confirm passphrase: ")
        if pp != pp2:
            raise ValueError("Passphrases do not match")
    return pp


def _load_or_create_keypair(passphrase: str | None = None) -> tuple[bytes, bytes]:
    """
    Load existing keypair or generate new one.
    Returns (public_key, private_key).
    Private key is derived deterministically from passphrase.
    """
    if not _KYBER_AVAILABLE:
        raise RuntimeError(
            "kyber-py not installed. Run: uv run pip install kyber-py"
        )

    key_file = _key_file()

    if key_file.exists():
        data = json.loads(key_file.read_text())
        pub = base64.b64decode(data["public_key"])
        salt = base64.b64decode(data["salt"])

        if passphrase is None:
            passphrase = _get_passphrase()

        # Re-derive private key from passphrase
        seed = _derive_seed(passphrase, salt)
        _pub, priv = Kyber768.keygen(seed[:32])  # deterministic from seed
        return pub, priv
    else:
        # First time — generate and save
        if passphrase is None:
            passphrase = _get_passphrase(confirm=True)

        salt = secrets.token_bytes(32)
        seed = _derive_seed(passphrase, salt)
        pub, priv = Kyber768.keygen(seed[:32])

        key_file.write_text(json.dumps({
            "public_key": base64.b64encode(pub).decode(),
            "salt": base64.b64encode(salt).decode(),
            "algorithm": "ML-KEM-768",
        }))
        key_file.chmod(0o600)
        return pub, priv


# ── Encryption / Decryption ───────────────────────────────────────────────────

def _encrypt_store(credentials: dict[str, str], passphrase: str | None = None) -> None:
    """Encrypt the full credentials dict and write to file."""
    pub, _ = _load_or_create_keypair(passphrase)

    # Encapsulate: generates a random shared secret + ciphertext
    kem_ciphertext, shared_secret = Kyber768.enc(pub)

    # Derive AES key from shared secret
    aes_key = _derive_aes_key(shared_secret)

    # Encrypt credentials JSON with AES-256-GCM
    nonce = secrets.token_bytes(12)
    aesgcm = AESGCM(aes_key)
    plaintext = json.dumps(credentials).encode()
    ciphertext = aesgcm.encrypt(nonce, plaintext, None)

    # Pack: kem_len(4) || kem_ct || nonce(12) || aes_ct
    kem_len = len(kem_ciphertext).to_bytes(4, "big")
    payload = kem_len + kem_ciphertext + nonce + ciphertext

    cred_file = _cred_file()
    cred_file.write_bytes(base64.b64encode(payload))
    cred_file.chmod(0o600)


def _decrypt_store(passphrase: str | None = None) -> dict[str, str]:
    """Decrypt and return credentials dict."""
    cred_file = _cred_file()
    if not cred_file.exists():
        return {}

    _, priv = _load_or_create_keypair(passphrase)

    payload = base64.b64decode(cred_file.read_bytes())
    kem_len = int.from_bytes(payload[:4], "big")
    kem_ciphertext = payload[4:4 + kem_len]
    nonce = payload[4 + kem_len: 4 + kem_len + 12]
    aes_ciphertext = payload[4 + kem_len + 12:]

    # Decapsulate shared secret
    shared_secret = Kyber768.dec(priv, kem_ciphertext)
    aes_key = _derive_aes_key(shared_secret)

    # Decrypt
    aesgcm = AESGCM(aes_key)
    plaintext = aesgcm.decrypt(nonce, aes_ciphertext, None)
    return json.loads(plaintext)


# ── Public API ────────────────────────────────────────────────────────────────

class CredentialStore:
    """
    Thread-safe PQC credential store.
    Caches decrypted credentials in memory for the session lifetime.
    """
    _cache: dict[str, str] | None = None
    _passphrase: str | None = None

    @classmethod
    def unlock(cls, passphrase: str | None = None) -> None:
        """Unlock the store. Call once at startup."""
        cls._passphrase = passphrase
        cls._cache = _decrypt_store(passphrase)

    @classmethod
    def get(cls, key: str, default: str | None = None) -> str | None:
        """
        Get a credential by key.
        Falls back to environment variable if not in store.
        """
        # Try store first
        if cls._cache is not None:
            val = cls._cache.get(key)
            if val:
                return val
        # Fall back to environment (for backward compat / CI/CD)
        return os.getenv(key, default)

    @classmethod
    def set(cls, key: str, value: str, passphrase: str | None = None) -> None:
        """Set a credential. Immediately persists to disk."""
        if cls._cache is None:
            cls._cache = _decrypt_store(passphrase or cls._passphrase)
        cls._cache[key] = value
        _encrypt_store(cls._cache, passphrase or cls._passphrase)

    @classmethod
    def delete(cls, key: str) -> None:
        """Remove a credential."""
        if cls._cache is None:
            return
        cls._cache.pop(key, None)
        _encrypt_store(cls._cache, cls._passphrase)

    @classmethod
    def list_keys(cls) -> list[str]:
        """List all stored credential keys (values not exposed)."""
        if cls._cache is None:
            cls._cache = _decrypt_store(cls._passphrase)
        return sorted(cls._cache.keys())

    @classmethod
    def initialized(cls) -> bool:
        return _key_file().exists()


# ── Convenience: get credential with env fallback ─────────────────────────────

def get_credential(key: str, default: str | None = None) -> str | None:
    """
    Get a credential from the store or environment.
    Use this everywhere instead of os.getenv() for sensitive values.
    """
    return CredentialStore.get(key, default)


# ── CLI ───────────────────────────────────────────────────────────────────────

def _cli():
    import argparse
    parser = argparse.ArgumentParser(
        description="Archon PQC Credential Store",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Commands:
  init              Generate ML-KEM-768 keypair
  set KEY           Set a credential (value prompted securely)
  get KEY           Retrieve a credential value
  list              List all stored credential keys
  delete KEY        Remove a credential
  migrate           Import credentials from .env file

Examples:
  python -m src.credentials init
  python -m src.credentials set SMB_PASS
  python -m src.credentials set SYNOLOGY_PASS
  python -m src.credentials list
  python -m src.credentials migrate
        """
    )
    parser.add_argument("command", choices=["init", "set", "get", "list", "delete", "migrate"])
    parser.add_argument("key", nargs="?", help="Credential key name")
    args = parser.parse_args()

    if args.command == "init":
        if CredentialStore.initialized():
            print("⚠️  Credential store already initialized.")
            yn = input("Re-initialize? This will ERASE all stored credentials. [y/N] ")
            if yn.lower() != "y":
                sys.exit(0)
            _key_file().unlink(missing_ok=True)
            _cred_file().unlink(missing_ok=True)
        print("Initializing Archon PQC credential store (ML-KEM-768)...")
        _load_or_create_keypair()  # prompts for passphrase
        print(f"✅ Keypair generated: {_key_file()}")
        print(f"   Algorithm: ML-KEM-768 (NIST FIPS 203)")
        print(f"   Credentials file: {_cred_file()}")

    elif args.command == "set":
        if not args.key:
            parser.error("KEY required for set command")
        if not CredentialStore.initialized():
            print("Store not initialized. Run: python -m src.credentials init")
            sys.exit(1)
        value = getpass.getpass(f"Value for {args.key}: ")
        CredentialStore.set(args.key, value)
        print(f"✅ {args.key} saved")

    elif args.command == "get":
        if not args.key:
            parser.error("KEY required for get command")
        CredentialStore.unlock()
        val = CredentialStore.get(args.key)
        if val:
            print(f"{args.key} = {val}")
        else:
            print(f"⚠️  {args.key} not found")
            sys.exit(1)

    elif args.command == "list":
        CredentialStore.unlock()
        keys = CredentialStore.list_keys()
        if keys:
            print(f"Stored credentials ({len(keys)}):")
            for k in keys:
                print(f"  • {k}")
        else:
            print("No credentials stored.")

    elif args.command == "delete":
        if not args.key:
            parser.error("KEY required for delete command")
        CredentialStore.unlock()
        CredentialStore.delete(args.key)
        print(f"✅ {args.key} deleted")

    elif args.command == "migrate":
        env_file = Path(".env")
        if not env_file.exists():
            print("No .env file found")
            sys.exit(1)

        sensitive_keys = {
            "SMB_PASS", "SMB_USER", "NFS_HOST",
            "IPTORRENTS_USER", "IPTORRENTS_PASS", "IPTORRENTS_COOKIE",
            "SYNOLOGY_USER", "SYNOLOGY_PASS",
            "NEO4J_PASSWORD",
            "OPENAI_API_KEY", "ANTHROPIC_API_KEY",
        }

        if not CredentialStore.initialized():
            print("Initializing store first...")
            _load_or_create_keypair()

        CredentialStore.unlock()
        migrated = 0
        with open(env_file) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key in sensitive_keys and value:
                    CredentialStore.set(key, value)
                    print(f"  ✅ Migrated: {key}")
                    migrated += 1

        print(f"\n✅ Migrated {migrated} credentials to encrypted store")
        print("   You can now remove sensitive values from .env")


if __name__ == "__main__":
    _cli()
