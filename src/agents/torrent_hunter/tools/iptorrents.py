"""
IPTorrents scraping tools + Synology Download Station API tools.

Credentials loaded from environment:
  IPTORRENTS_USER      — IPTorrents username
  IPTORRENTS_PASS      — IPTorrents password
  IPTORRENTS_COOKIE    — Optional: pre-auth cookie (skips login)
  SYNOLOGY_HOST        — e.g. http://192.168.1.x:5000
  SYNOLOGY_USER        — Download Station username
  SYNOLOGY_PASS        — Download Station password
  DS_DOWNLOAD_DIR_TV   — e.g. /volume1/downloads/tv
  DS_DOWNLOAD_DIR_MOVIES — e.g. /volume1/downloads/movies
"""
from __future__ import annotations

import os
from typing import Any

import httpx
from bs4 import BeautifulSoup
from langchain_core.tools import tool

# ── IPTorrents ─────────────────────────────────────────────────────────────────

IPT_BASE = "https://iptorrents.com"
_session_cookies: dict[str, str] = {}


def _get_session() -> dict[str, str]:
    """Return authenticated cookie dict, logging in if needed."""
    global _session_cookies
    if _session_cookies:
        return _session_cookies

    cookie_str = os.getenv("IPTORRENTS_COOKIE", "")
    if cookie_str:
        # Accept raw cookie string: "uid=xxx; pass=yyy"
        _session_cookies = dict(
            item.strip().split("=", 1)
            for item in cookie_str.split(";")
            if "=" in item
        )
        return _session_cookies

    user = os.environ["IPTORRENTS_USER"]
    password = os.environ["IPTORRENTS_PASS"]

    with httpx.Client(follow_redirects=True, timeout=30) as client:
        resp = client.post(
            f"{IPT_BASE}/take_login.php",
            data={"username": user, "password": password, "login": "submit"},
        )
        resp.raise_for_status()
        _session_cookies = dict(resp.cookies)
    return _session_cookies


@tool
def search_iptorrents(query: str, category: str = "all") -> list[dict[str, Any]]:
    """
    Search IPTorrents for a title.
    category: 'movies', 'tv', or 'all'
    Returns a list of torrent results sorted by seeders (descending).
    """
    cat_map = {"movies": "73", "tv": "78", "all": ""}
    cat_id = cat_map.get(category, "")
    params: dict[str, str] = {"q": query, "o": "seeders"}
    if cat_id:
        params["cat"] = cat_id

    cookies = _get_session()
    with httpx.Client(follow_redirects=True, timeout=30, cookies=cookies) as client:
        resp = client.get(f"{IPT_BASE}/t", params=params)
        resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")
    results = []
    for row in soup.select("table#torrents tr.t-row"):
        try:
            name_tag = row.select_one("td.t_name a")
            size_tag = row.select_one("td.t_size")
            seed_tag = row.select_one("td.t_seed")
            leech_tag = row.select_one("td.t_leech")
            dl_tag = row.select_one("td.t_dl a")
            if not name_tag:
                continue
            results.append({
                "name": name_tag.get_text(strip=True),
                "size": size_tag.get_text(strip=True) if size_tag else "?",
                "seeders": int(seed_tag.get_text(strip=True) or 0) if seed_tag else 0,
                "leechers": int(leech_tag.get_text(strip=True) or 0) if leech_tag else 0,
                "download_url": IPT_BASE + dl_tag["href"] if dl_tag else None,
                "detail_url": IPT_BASE + name_tag["href"] if name_tag.get("href") else None,
            })
        except (AttributeError, KeyError, ValueError):
            continue

    return sorted(results, key=lambda x: x["seeders"], reverse=True)


@tool
def get_torrent_file(download_url: str) -> dict[str, Any]:
    """
    Download the .torrent file bytes from IPTorrents.
    Returns base64-encoded content for passing to Download Station.
    """
    import base64
    cookies = _get_session()
    with httpx.Client(follow_redirects=True, timeout=30, cookies=cookies) as client:
        resp = client.get(download_url)
        resp.raise_for_status()
    return {
        "content_b64": base64.b64encode(resp.content).decode(),
        "size_bytes": len(resp.content),
        "content_type": resp.headers.get("content-type", ""),
    }


# ── Synology Download Station ──────────────────────────────────────────────────

def _ds_sid() -> str:
    """Authenticate with Synology DSM and return session ID (sid)."""
    host = os.environ["SYNOLOGY_HOST"].rstrip("/")
    user = os.environ["SYNOLOGY_USER"]
    password = os.environ["SYNOLOGY_PASS"]

    resp = httpx.get(
        f"{host}/webapi/auth.cgi",
        params={
            "api": "SYNO.API.Auth",
            "version": "3",
            "method": "login",
            "account": user,
            "passwd": password,
            "session": "DownloadStation",
            "format": "cookie",
        },
        timeout=15,
    )
    data = resp.json()
    if not data.get("success"):
        raise RuntimeError(f"Synology auth failed: {data}")
    return data["data"]["sid"]


@tool
def add_download_job(torrent_b64: str, destination_folder: str) -> dict[str, Any]:
    """
    Add a torrent to Synology Download Station.
    torrent_b64: base64-encoded .torrent file content
    destination_folder: e.g. '/volume1/downloads/movies'
    """
    import base64
    import tempfile

    host = os.environ["SYNOLOGY_HOST"].rstrip("/")
    sid = _ds_sid()

    torrent_bytes = base64.b64decode(torrent_b64)
    with tempfile.NamedTemporaryFile(suffix=".torrent", delete=False) as tmp:
        tmp.write(torrent_bytes)
        tmp_path = tmp.name

    with open(tmp_path, "rb") as f:
        resp = httpx.post(
            f"{host}/webapi/DownloadStation/task.cgi",
            data={
                "api": "SYNO.DownloadStation.Task",
                "version": "1",
                "method": "create",
                "destination": destination_folder,
                "_sid": sid,
            },
            files={"file": ("task.torrent", f, "application/x-bittorrent")},
            timeout=30,
        )

    os.unlink(tmp_path)
    data = resp.json()
    return {"success": data.get("success"), "raw": data}


@tool
def list_download_jobs() -> list[dict[str, Any]]:
    """List current Download Station tasks (name, status, progress)."""
    host = os.environ["SYNOLOGY_HOST"].rstrip("/")
    sid = _ds_sid()
    resp = httpx.get(
        f"{host}/webapi/DownloadStation/task.cgi",
        params={
            "api": "SYNO.DownloadStation.Task",
            "version": "1",
            "method": "list",
            "additional": "transfer",
            "_sid": sid,
        },
        timeout=15,
    )
    data = resp.json()
    if not data.get("success"):
        return [{"error": str(data)}]
    return [
        {
            "id": t["id"],
            "title": t["title"],
            "status": t["status"],
            "size_bytes": t.get("size", 0),
        }
        for t in data["data"].get("tasks", [])
    ]


def get_tools() -> list:
    return [search_iptorrents, get_torrent_file, add_download_job, list_download_jobs]
