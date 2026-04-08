"""
Protocol factory — auto-detects the right adapter from a URI or config dict.

URI formats:
  local:///path/to/dir
  smb://[domain\\]user:pass@host/share/subpath
  nfs://host/export/subpath

Or pass a dict:
  {"protocol": "smb", "host": "...", "share": "...", ...}
"""
from __future__ import annotations

import os
from urllib.parse import urlparse, unquote

from .base import NASProtocol
from .local import LocalProtocol
from .smb import SMBProtocol
from .nfs import NFSProtocol


def protocol_factory(source: str | dict) -> tuple[NASProtocol, str]:
    """
    Returns (protocol_instance, root_path).

    root_path is the path within the share/export to start from.
    """
    if isinstance(source, dict):
        return _from_dict(source)
    return _from_uri(source)


def _from_uri(uri: str) -> tuple[NASProtocol, str]:
    parsed = urlparse(uri)
    scheme = parsed.scheme.lower()

    # Windows absolute path: C:\... or C:/...
    if len(scheme) == 1 and scheme.isalpha():
        return LocalProtocol(), uri

    if scheme in ("", "local", "file"):
        path = unquote(parsed.path or parsed.netloc)
        return LocalProtocol(), path

    if scheme == "smb":
        host = parsed.hostname or ""
        parts = parsed.path.lstrip("/").split("/", 1)
        share = parts[0]
        subpath = parts[1] if len(parts) > 1 else ""
        username = unquote(parsed.username or "")
        password = unquote(parsed.password or "")
        domain = ""
        if "\\" in username:
            domain, username = username.split("\\", 1)
        return SMBProtocol(host=host, share=share, username=username,
                           password=password, domain=domain), subpath

    if scheme == "nfs":
        host = parsed.hostname or ""
        parts = parsed.path.split("/", 2)
        # nfs://host/export/subpath → export=/export, subpath=subpath
        export = "/" + (parts[1] if len(parts) > 1 else "")
        subpath = parts[2] if len(parts) > 2 else ""
        return NFSProtocol(host=host, export=export), subpath

    raise ValueError(f"Unknown protocol scheme: {scheme!r}. Supported: local, smb, nfs")


def _from_dict(cfg: dict) -> tuple[NASProtocol, str]:
    proto = cfg.get("protocol", "local").lower()
    subpath = cfg.get("path", "")

    if proto == "local":
        return LocalProtocol(
            follow_symlinks=cfg.get("follow_symlinks", False),
            skip_hidden=cfg.get("skip_hidden", False),
        ), subpath

    if proto == "smb":
        return SMBProtocol(
            host=cfg["host"],
            share=cfg["share"],
            username=cfg.get("username", os.getenv("SMB_USER", "")),
            password=cfg.get("password", os.getenv("SMB_PASS", "")),
            domain=cfg.get("domain", os.getenv("SMB_DOMAIN", "")),
            port=cfg.get("port", 445),
            encrypt=cfg.get("encrypt", False),
        ), subpath

    if proto == "nfs":
        return NFSProtocol(
            host=cfg["host"],
            export=cfg["export"],
            version=cfg.get("version", 3),
            readonly=cfg.get("readonly", True),
        ), subpath

    raise ValueError(f"Unknown protocol: {proto!r}")
