import os

import boto3
from moto import mock_aws

from memoryfield_tool import index, search, transport
from memoryfield_tool.db import sqlite3
from memoryfield_tool.transport import S3Transport


def _bucket_conn():
    conn = boto3.client("s3", region_name="us-east-1")
    conn.create_bucket(Bucket="testbucket")
    return conn


def _seed_page(conn, prefix, name, title, summary, body):
    conn.put_object(
        Bucket="testbucket",
        Key=f"{prefix}/{name}",
        Body=(
            f"---\ntitle: {title}\nsummary: {summary}\n"
            "created: '2026-01-01T09:00:00Z'\nupdated: '2026-01-02T09:00:00Z'\n"
            "uuid: '00000000-0000-0000-0000-000000000001'\n"
            f"---\n\n{body}\n"
        ).encode(),
    )


def _s3_field(conn, prefix="prefix"):
    _seed_page(conn, prefix, "alpha.md", "Alpha", "Notes about alpha things.", "Alpha body")
    _seed_page(conn, prefix, "beta.md", "Beta", "Notes about beta things.", "Beta body")
    return S3Transport("testbucket", prefix, client=conn)


@mock_aws
def test_pull_downloads_when_remote_newer(tmp_path):
    conn = _bucket_conn()
    t = _s3_field(conn)
    t.write_object(index.index_filename(), b"remote-index-bytes")

    loc = tmp_path / "cache" / "idx.sqlite3"
    index.pull_index(t, loc)

    assert loc.is_file()
    assert loc.read_bytes() == b"remote-index-bytes"
    remote_mtime = t.stat_object(index.index_filename()).last_modified.timestamp()
    assert abs(loc.stat().st_mtime - remote_mtime) < 1


@mock_aws
def test_pull_skips_when_local_newer(tmp_path):
    conn = _bucket_conn()
    t = _s3_field(conn)
    t.write_object(index.index_filename(), b"remote-index-bytes")

    loc = tmp_path / "idx.sqlite3"
    loc.write_bytes(b"local-index-bytes")
    future = os.stat(loc).st_mtime + 3600
    os.utime(loc, (future, future))

    index.pull_index(t, loc)
    assert loc.read_bytes() == b"local-index-bytes"


@mock_aws
def test_pull_skips_when_equal(tmp_path, monkeypatch):
    conn = _bucket_conn()
    t = _s3_field(conn)
    t.write_object(index.index_filename(), b"remote-index-bytes")

    loc = tmp_path / "idx.sqlite3"
    index.pull_index(t, loc)

    def boom(key):
        raise AssertionError("read_object should not be called on an up-to-date pull")

    monkeypatch.setattr(S3Transport, "read_object", boom)
    index.pull_index(t, loc)


@mock_aws
def test_push_uploads_when_local_newer(tmp_path):
    conn = _bucket_conn()
    t = _s3_field(conn)

    loc = tmp_path / "idx.sqlite3"
    loc.write_bytes(b"local-index-bytes")

    index.push_index(t, loc)
    assert t.stat_object(index.index_filename()).size == len(b"local-index-bytes")
    assert t.read_object(index.index_filename()) == b"local-index-bytes"


@mock_aws
def test_push_skips_when_remote_at_least_as_new(tmp_path, monkeypatch):
    conn = _bucket_conn()
    t = _s3_field(conn)
    t.write_object(index.index_filename(), b"remote-index-bytes")

    loc = tmp_path / "idx.sqlite3"
    loc.write_bytes(b"local-index-bytes")
    past = os.stat(loc).st_mtime - 3600
    os.utime(loc, (past, past))

    def boom(key, data, *, append=False):
        raise AssertionError("write_object should not be called when remote is newer")

    monkeypatch.setattr(S3Transport, "write_object", boom)
    index.push_index(t, loc)


@mock_aws
def test_build_index_s3_pushes_once(tmp_path, fake_embed, monkeypatch):
    conn = _bucket_conn()
    t = _s3_field(conn)

    cache = tmp_path / "cache" / "idx.sqlite3"
    index.build_index(t, cache, progress=False)
    assert t.exists(index.index_filename())

    calls = {"n": 0}
    real_write = S3Transport.write_object

    def counting(self, key, data, *, append=False):
        calls["n"] += 1
        return real_write(self, key, data, append=append)

    monkeypatch.setattr(S3Transport, "write_object", counting)
    index.build_index(t, cache, progress=False)
    assert calls["n"] == 0


@mock_aws
def test_delete_page_s3_syncs(tmp_path, fake_embed):
    conn = _bucket_conn()
    t = _s3_field(conn)

    cache = tmp_path / "cache" / "idx.sqlite3"
    index.build_index(t, cache, progress=False)
    index.delete_page(t, cache, "alpha.md")

    data = t.read_object(index.index_filename())
    copied = tmp_path / "copied.sqlite3"
    copied.write_bytes(data)
    db = sqlite3.connect(str(copied))
    names = {r[0] for r in db.execute("SELECT filename FROM pages")}
    db.close()
    assert "alpha.md" not in names
    assert "beta.md" in names


@mock_aws
def test_search_pulls_fresh_index(tmp_path, field_dir, fake_embed):
    conn = _bucket_conn()
    t = _s3_field(conn)

    index.build_index(transport.local(field_dir), index.index_path(field_dir), progress=False)
    t.write_object(index.index_filename(), index.index_path(field_dir).read_bytes())

    cache = tmp_path / "cacheB" / "idx.sqlite3"
    results = search.search_field(t, cache, "alpha")

    assert cache.is_file()
    assert results
    assert results[0].filename == "alpha.md"


@mock_aws
def test_sync_errors_swallowed(tmp_path, monkeypatch):
    conn = _bucket_conn()
    t = _s3_field(conn)

    def boom(self, key):
        raise transport.TransportError("bucket unreachable")

    monkeypatch.setattr(S3Transport, "stat_object", boom)

    loc = tmp_path / "idx.sqlite3"
    index.pull_index(t, loc)
    loc.write_bytes(b"bytes")
    index.push_index(t, loc)
