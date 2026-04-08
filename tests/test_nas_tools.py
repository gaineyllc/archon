"""Updated smoke tests for the NAS tools — uses 'source' param to match new API."""
from src.agents.nas_cataloger.tools.filesystem import (
    list_directory, get_file_info, compute_file_hash,
    find_duplicates, move_file, delete_file, get_tools,
)


def setup_module():
    get_tools(dry_run=True)


def test_list_directory(tmp_path):
    (tmp_path / "a.txt").write_text("hello")
    (tmp_path / "b.txt").write_text("world")
    result = list_directory.invoke({"source": str(tmp_path)})
    names = [r["name"] for r in result]
    assert "a.txt" in names
    assert "b.txt" in names


def test_get_file_info(tmp_path):
    f = tmp_path / "test.txt"
    f.write_text("content")
    info = get_file_info.invoke({"source": str(f)})
    assert info["name"] == "test.txt"
    assert info["size_bytes"] == 7


def test_compute_hash_deterministic(tmp_path):
    f = tmp_path / "file.bin"
    f.write_bytes(b"deadbeef" * 100)
    r1 = compute_file_hash.invoke({"source": str(f)})
    r2 = compute_file_hash.invoke({"source": str(f)})
    assert r1["sha256"] == r2["sha256"]
    assert len(r1["sha256"]) == 64


def test_find_duplicates(tmp_path):
    content = b"duplicate content"
    (tmp_path / "dup1.bin").write_bytes(content)
    (tmp_path / "dup2.bin").write_bytes(content)
    (tmp_path / "unique.bin").write_bytes(b"something else entirely")
    dupes = find_duplicates.invoke({"source": str(tmp_path)})
    assert len(dupes) == 1
    assert dupes[0]["count"] == 2


def test_move_file_dry_run(tmp_path):
    src = tmp_path / "src.txt"
    src.write_text("data")
    dst = tmp_path / "dst.txt"
    result = move_file.invoke({"source": str(src), "destination": str(dst)})
    assert result["status"] == "dry_run"
    assert src.exists()


def test_delete_file_dry_run(tmp_path):
    f = tmp_path / "todelete.txt"
    f.write_text("data")
    result = delete_file.invoke({"source": str(f)})
    assert result["status"] == "dry_run"
    assert f.exists()
