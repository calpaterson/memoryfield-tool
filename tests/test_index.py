import json
import os
import re
import time
from datetime import UTC, datetime

from memoryfield_tool import index, transport


def test_full_build(field_dir, fake_embed):
    indexed, removed, embed_ok = index.build_index(
        transport.local(field_dir), index.index_path(field_dir), progress=False
    )
    assert indexed == 4
    assert removed == 0
    assert embed_ok is True

    db_path = index.index_path(field_dir)
    assert db_path.is_file()
    assert db_path.name == "nomic-embed-text-v1.5.sqlite3"

    db = index._open_index(db_path)
    rows = db.execute("SELECT filename FROM pages ORDER BY filename").fetchall()
    db.close()
    assert [r[0] for r in rows] == ["alpha.md", "beta.md", "gamma.md", "index.md"]


def test_frontmatter_column_stores_json(field_dir, fake_embed):
    index.build_index(transport.local(field_dir), index.index_path(field_dir), progress=False)
    db = index._open_index(index.index_path(field_dir))
    (fm,) = db.execute("SELECT frontmatter FROM pages WHERE filename = 'alpha.md'").fetchone()
    db.close()
    parsed = json.loads(fm)
    assert parsed["title"] == "Alpha Notes"
    assert parsed["summary"] == "Notes about alpha things."


def test_last_modified_stored_as_utc_z(field_dir, fake_embed):
    index.build_index(transport.local(field_dir), index.index_path(field_dir), progress=False)
    db = index._open_index(index.index_path(field_dir))
    (lm,) = db.execute("SELECT last_modified FROM pages WHERE filename = 'alpha.md'").fetchone()
    db.close()
    assert re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$", lm)


def test_rebuild_with_no_changes_reembeds_nothing(field_dir, fake_embed, monkeypatch):
    index.build_index(transport.local(field_dir), index.index_path(field_dir), progress=False)
    calls = {"n": 0}

    def counting(texts):
        calls["n"] += 1
        return fake_embed(texts)

    monkeypatch.setattr("memoryfield_tool.index.embed.embed_texts", counting)
    indexed, removed, embed_ok = index.build_index(
        transport.local(field_dir), index.index_path(field_dir), progress=False
    )
    assert (indexed, removed) == (0, 0)
    assert embed_ok is True
    assert calls["n"] == 0


def test_add_modify_delete(field_dir, fake_embed):
    index.build_index(transport.local(field_dir), index.index_path(field_dir), progress=False)

    (field_dir / "delta.md").write_text(
        "---\ntitle: Delta\n---\n\nbrand new page\n", encoding="utf-8"
    )
    (field_dir / "beta.md").write_text(
        "---\ntitle: Beta 2\n---\n\nmodified body\n", encoding="utf-8"
    )
    future = time.time() + 100
    os.utime(field_dir / "beta.md", (future, future))
    (field_dir / "gamma.md").unlink()

    indexed, removed, embed_ok = index.build_index(
        transport.local(field_dir), index.index_path(field_dir), progress=False
    )
    assert indexed == 2
    assert removed == 1
    assert embed_ok is True

    db = index._open_index(index.index_path(field_dir))
    names = {r[0] for r in db.execute("SELECT filename FROM pages")}
    db.close()
    assert names == {"alpha.md", "beta.md", "delta.md", "index.md"}


def test_embedding_input_includes_frontmatter(field_dir, fake_embed, monkeypatch):
    captured: list[str] = []

    def capture(texts):
        captured.extend(texts)
        return fake_embed(texts)

    monkeypatch.setattr("memoryfield_tool.index.embed.embed_texts", capture)
    index.build_index(transport.local(field_dir), index.index_path(field_dir), progress=False)

    text = (field_dir / "alpha.md").read_text(encoding="utf-8")
    assert f"search_document: {text}" in captured
    assert all(t.startswith("search_document: ") for t in captured)


def test_oversized_page_truncated(field_dir, fake_embed, monkeypatch):
    (field_dir / "big.md").write_text("---\ntitle: Big\n---\n\n" + "x" * 10000, encoding="utf-8")
    captured: list[str] = []

    def capture(texts):
        captured.extend(texts)
        return fake_embed(texts)

    monkeypatch.setattr("memoryfield_tool.index.embed.embed_texts", capture)
    index.build_index(transport.local(field_dir), index.index_path(field_dir), progress=False)

    big_input = next(t for t in captured if "Big" in t)
    assert len(big_input) == len("search_document: ") + 8192


def test_embed_none_returns_flag(field_dir, monkeypatch):
    monkeypatch.setattr("memoryfield_tool.index.embed.embed_texts", lambda texts: None)
    indexed, removed, embed_ok = index.build_index(
        transport.local(field_dir), index.index_path(field_dir), progress=False
    )
    assert (indexed, removed) == (0, 0)
    assert embed_ok is False


def test_noop_rebuild_returns_ok(field_dir, fake_embed):
    index.build_index(transport.local(field_dir), index.index_path(field_dir), progress=False)
    indexed, removed, embed_ok = index.build_index(
        transport.local(field_dir), index.index_path(field_dir), progress=False
    )
    assert (indexed, removed) == (0, 0)
    assert embed_ok is True


def test_unquoted_datetime_frontmatter_tolerated(field_dir, fake_embed):
    (field_dir / "datepage.md").write_text(
        "---\ntitle: Date Page\ncreated: 2026-03-01\nupdated: 2026-03-02 14:30:00\n---\n\nbody\n",
        encoding="utf-8",
    )
    indexed, removed, embed_ok = index.build_index(
        transport.local(field_dir), index.index_path(field_dir), progress=False
    )
    assert indexed == 5
    assert removed == 0
    assert embed_ok is True

    db = index._open_index(index.index_path(field_dir))
    (fm,) = db.execute("SELECT frontmatter FROM pages WHERE filename = 'datepage.md'").fetchone()
    db.close()
    parsed = json.loads(fm)
    assert parsed["created"] == "2026-03-01"
    assert isinstance(parsed["created"], str)
    assert parsed["updated"] == "2026-03-02 14:30:00"


def test_delete_page_removes_row(field_dir, fake_embed):
    index.build_index(transport.local(field_dir), index.index_path(field_dir), progress=False)
    index.delete_page(index.index_path(field_dir), "alpha.md")

    db = index._open_index(index.index_path(field_dir))
    names = {r[0] for r in db.execute("SELECT filename FROM pages")}
    db.close()
    assert names == {"beta.md", "gamma.md", "index.md"}


def test_delete_page_absent_index_noop(field_dir):
    index.delete_page(index.index_path(field_dir), "alpha.md")
    assert not index.index_path(field_dir).exists()


def test_delete_page_missing_row_noop(field_dir, fake_embed):
    index.build_index(transport.local(field_dir), index.index_path(field_dir), progress=False)
    index.delete_page(index.index_path(field_dir), "nope.md")

    db = index._open_index(index.index_path(field_dir))
    names = {r[0] for r in db.execute("SELECT filename FROM pages")}
    db.close()
    assert names == {"alpha.md", "beta.md", "gamma.md", "index.md"}


def test_partial_build_commits_progress(field_dir, fake_embed, monkeypatch):
    calls = {"n": 0}

    def failing(texts):
        calls["n"] += 1
        if calls["n"] <= 2:
            return fake_embed(texts)
        return None

    monkeypatch.setattr("memoryfield_tool.index.embed.embed_texts", failing)
    indexed, removed, embed_ok = index.build_index(
        transport.local(field_dir), index.index_path(field_dir), progress=False
    )
    assert (indexed, removed, embed_ok) == (2, 0, False)

    db = index._open_index(index.index_path(field_dir))
    count = db.execute("SELECT COUNT(*) FROM pages").fetchone()[0]
    db.close()
    assert count == 2

    monkeypatch.setattr("memoryfield_tool.index.embed.embed_texts", fake_embed)
    indexed, removed, embed_ok = index.build_index(
        transport.local(field_dir), index.index_path(field_dir), progress=False
    )
    assert (indexed, removed, embed_ok) == (2, 0, True)

    db = index._open_index(index.index_path(field_dir))
    count = db.execute("SELECT COUNT(*) FROM pages").fetchone()[0]
    db.close()
    assert count == 4


def test_lock_lives_in_cache_not_field_root(field_dir, fake_embed, monkeypatch, tmp_path):
    cache = tmp_path / "cache"
    monkeypatch.setenv("XDG_CACHE_HOME", str(cache))
    index.build_index(transport.local(field_dir), index.index_path(field_dir), progress=False)
    assert list(field_dir.glob("*.lock")) == []
    locks = list((cache / "memoryfield-tool" / "locks").glob("*.lock"))
    assert len(locks) == 1


def test_unchanged_rebuild_reads_nothing(field_dir, fake_embed, monkeypatch):
    index.build_index(transport.local(field_dir), index.index_path(field_dir), progress=False)

    def raise_boom(key):
        raise AssertionError("read_object should not run on an unchanged rebuild")

    monkeypatch.setattr(transport.LocalTransport, "read_object", raise_boom)
    indexed, removed, embed_ok = index.build_index(
        transport.local(field_dir), index.index_path(field_dir), progress=False
    )
    assert (indexed, removed) == (0, 0)
    assert embed_ok is True


def test_mtime_only_change_updates_mtime_no_embed(field_dir, fake_embed, monkeypatch):
    index.build_index(transport.local(field_dir), index.index_path(field_dir), progress=False)

    future = time.time() + 100
    os.utime(field_dir / "alpha.md", (future, future))
    calls = {"n": 0}

    def counting(texts):
        calls["n"] += 1
        return fake_embed(texts)

    monkeypatch.setattr("memoryfield_tool.index.embed.embed_texts", counting)
    indexed, removed, embed_ok = index.build_index(
        transport.local(field_dir), index.index_path(field_dir), progress=False
    )
    assert (indexed, removed) == (0, 0)
    assert embed_ok is True
    assert calls["n"] == 0

    db = index._open_index(index.index_path(field_dir))
    (lm,) = db.execute("SELECT last_modified FROM pages WHERE filename = 'alpha.md'").fetchone()
    db.close()
    assert lm == index._dt_iso(datetime.fromtimestamp(future, tz=UTC))
