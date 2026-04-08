"""Tests for the protocol layer — local protocol + factory (no network required)."""
import os
from pathlib import Path

from src.agents.nas_cataloger.protocols.base import FileInfo
from src.agents.nas_cataloger.protocols.local import LocalProtocol
from src.agents.nas_cataloger.protocols.factory import protocol_factory


# ── LocalProtocol ──────────────────────────────────────────────────────────────

def test_local_walk_yields_files(tmp_path):
    (tmp_path / "a.txt").write_text("hello")
    (tmp_path / "b.mp4").write_bytes(b"\x00" * 100)
    sub = tmp_path / "subdir"
    sub.mkdir()
    (sub / "c.jpg").write_bytes(b"\xff" * 50)

    proto = LocalProtocol()
    results = list(proto.walk(str(tmp_path), recursive=True))
    names = {r.name for r in results}
    assert "a.txt" in names
    assert "b.mp4" in names
    assert "c.jpg" in names
    assert "subdir" in names


def test_local_walk_non_recursive(tmp_path):
    (tmp_path / "top.txt").write_text("x")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "deep.txt").write_text("y")

    proto = LocalProtocol()
    results = list(proto.walk(str(tmp_path), recursive=False))
    names = {r.name for r in results}
    assert "top.txt" in names
    assert "deep.txt" not in names


def test_local_fileinfo_metadata(tmp_path):
    f = tmp_path / "test.py"
    f.write_text("print('hello')")
    proto = LocalProtocol()
    entries = proto.list_dir(str(tmp_path))
    entry = next(e for e in entries if e.name == "test.py")
    assert entry.suffix == ".py"
    assert entry.size_bytes > 0
    assert entry.protocol == "local"
    assert not entry.is_dir


def test_local_read_bytes(tmp_path):
    f = tmp_path / "data.bin"
    f.write_bytes(b"ABCDEFGH")
    proto = LocalProtocol()
    assert proto.read_bytes(str(f), max_bytes=4) == b"ABCD"


def test_local_read_bytes_at(tmp_path):
    f = tmp_path / "seek.bin"
    f.write_bytes(b"0123456789")
    proto = LocalProtocol()
    assert proto.read_bytes_at(str(f), offset=3, length=4) == b"3456"


def test_local_compute_hash_deterministic(tmp_path):
    f = tmp_path / "hash.bin"
    f.write_bytes(b"deadbeef" * 1000)
    proto = LocalProtocol()
    h1 = proto.compute_hash(str(f))
    h2 = proto.compute_hash(str(f))
    assert h1 == h2
    assert len(h1) == 64


def test_local_move_dry_run_not_needed(tmp_path):
    """move() on LocalProtocol always executes — dry_run is enforced at tool layer."""
    src = tmp_path / "src.txt"
    dst = tmp_path / "subdir" / "dst.txt"
    src.write_text("data")
    proto = LocalProtocol()
    proto.move(str(src), str(dst))
    assert dst.exists()
    assert not src.exists()


def test_local_delete(tmp_path):
    f = tmp_path / "todelete.txt"
    f.write_text("bye")
    proto = LocalProtocol()
    proto.delete(str(f))
    assert not f.exists()


def test_local_mkdir(tmp_path):
    target = tmp_path / "a" / "b" / "c"
    proto = LocalProtocol()
    proto.mkdir(str(target))
    assert target.is_dir()


# ── Factory ────────────────────────────────────────────────────────────────────

def test_factory_local_path(tmp_path):
    proto, path = protocol_factory(str(tmp_path))
    assert isinstance(proto, LocalProtocol)
    assert path == str(tmp_path)


def test_factory_local_uri(tmp_path):
    proto, path = protocol_factory(f"local://{tmp_path}")
    assert isinstance(proto, LocalProtocol)


def test_factory_smb_uri():
    from src.agents.nas_cataloger.protocols.smb import SMBProtocol
    proto, path = protocol_factory("smb://user:pass@192.168.1.1/media/movies")
    assert isinstance(proto, SMBProtocol)
    assert proto.host == "192.168.1.1"
    assert proto.share == "media"
    assert path == "movies"


def test_factory_nfs_uri():
    from src.agents.nas_cataloger.protocols.nfs import NFSProtocol
    proto, path = protocol_factory("nfs://192.168.1.1/volume1/media")
    assert isinstance(proto, NFSProtocol)
    assert proto.host == "192.168.1.1"
    assert proto.export == "/volume1"
    assert path == "media"


def test_factory_dict_smb():
    from src.agents.nas_cataloger.protocols.smb import SMBProtocol
    proto, path = protocol_factory({
        "protocol": "smb",
        "host": "mynas",
        "share": "backup",
        "username": "admin",
        "password": "secret",
        "path": "photos/2024",
    })
    assert isinstance(proto, SMBProtocol)
    assert proto.share == "backup"
    assert path == "photos/2024"


def test_factory_unknown_scheme():
    import pytest
    with pytest.raises(ValueError, match="Unknown protocol"):
        protocol_factory("ftp://host/share")
