from datetime import datetime

import boto3
import click
import pytest
from moto import mock_aws

from memoryfield_tool import transport
from memoryfield_tool.transport import (
    ContainmentError,
    LocalTransport,
    ObjectNotFound,
    S3Transport,
    TransportError,
    parse_s3_uri,
)


def test_local_list_flat_and_recursive(tmp_path):
    root = tmp_path / "field"
    root.mkdir()
    (root / "alpha.md").write_text("a\n", encoding="utf-8")
    (root / "zebra.txt").write_text("z\n", encoding="utf-8")
    (root / "sub").mkdir()
    (root / "sub" / "img.png").write_bytes(b"\x89PNG")

    t = LocalTransport(root)
    flat = t.list_objects()
    assert [o.key for o in flat] == ["alpha.md", "zebra.txt"]
    rec = t.list_objects(recursive=True)
    assert [o.key for o in rec] == ["alpha.md", "sub/img.png", "zebra.txt"]
    assert flat[0].size == len("a\n")
    assert isinstance(flat[0].last_modified, datetime)


def test_local_read_write_append_delete_stat_exists(tmp_path):
    root = tmp_path / "field"
    root.mkdir()
    t = LocalTransport(root)

    t.write_object("note.md", b"first\n")
    assert (root / "note.md").read_bytes() == b"first\n"
    t.write_object("note.md", b"second\n", append=True)
    assert (root / "note.md").read_bytes() == b"first\nsecond\n"

    info = t.stat_object("note.md")
    assert info is not None
    assert info.key == "note.md"
    assert info.size == len(b"first\nsecond\n")
    assert t.exists("note.md") is True
    assert t.stat_object("missing.md") is None
    assert t.exists("missing.md") is False

    t.write_object("sub/deep.md", b"x")
    assert (root / "sub" / "deep.md").read_bytes() == b"x"

    t.delete_object("note.md")
    assert not (root / "note.md").exists()
    with pytest.raises(ObjectNotFound):
        t.delete_object("note.md")
    with pytest.raises(ObjectNotFound):
        t.read_object("note.md")


def test_local_read_roundtrip(tmp_path):
    root = tmp_path / "field"
    root.mkdir()
    (root / "alpha.md").write_text("hello", encoding="utf-8")
    t = LocalTransport(root)
    assert t.read_object("alpha.md") == b"hello"


def test_local_escape_read_and_exists(tmp_path):
    root = tmp_path / "field"
    root.mkdir()
    (tmp_path / "outside.md").write_text("secret", encoding="utf-8")
    t = LocalTransport(root)
    assert t.exists("../outside.md") is False
    assert t.exists("/etc/passwd") is False
    with pytest.raises(ContainmentError):
        t.read_object("../outside.md")
    with pytest.raises(ContainmentError):
        t.read_object("/etc/passwd")


def test_local_write_escape(tmp_path):
    root = tmp_path / "field"
    root.mkdir()
    t = LocalTransport(root)
    with pytest.raises(ContainmentError):
        t.write_object("../x.md", b"x")
    with pytest.raises(ContainmentError):
        t.write_object("/etc/x.md", b"x")


def test_local_symlink_escape(tmp_path):
    root = tmp_path / "field"
    root.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    try:
        (root / "evil.md").symlink_to(outside)
    except OSError, NotImplementedError:
        pytest.skip("symlinks not supported on this platform")
    t = LocalTransport(root)
    with pytest.raises(ContainmentError):
        t.read_object("evil.md")
    assert t.exists("evil.md") is False


def test_local_probe_missing_dir(tmp_path):
    t = LocalTransport(tmp_path / "nope")
    with pytest.raises(TransportError):
        t.probe()


@pytest.mark.parametrize(
    ("location", "bucket", "prefix"),
    [
        ("s3://bucket", "bucket", ""),
        ("s3://bucket/prefix/", "bucket", "prefix"),
        ("s3://bkt/a/b", "bkt", "a/b"),
    ],
)
def test_parse_s3_uri_valid(location, bucket, prefix):
    assert parse_s3_uri(location) == (bucket, prefix)


@pytest.mark.parametrize(
    "location",
    ["bucket", "s3:///x", "s3://UPPER/x", "s3://bu", "s3://b", "s3://"],
)
def test_parse_s3_uri_invalid(location):
    with pytest.raises(click.ClickException, match="invalid s3 location"):
        parse_s3_uri(location)


@mock_aws
def test_s3_transport_roundtrip():
    conn = boto3.client("s3", region_name="us-east-1")
    conn.create_bucket(Bucket="testbucket")
    conn.put_object(Bucket="testbucket", Key="alpha.md", Body=b"hello")
    conn.put_object(Bucket="testbucket", Key="sub/img.png", Body=b"\x89PNG")

    t = S3Transport("testbucket", "")

    flat = t.list_objects()
    assert [o.key for o in flat] == ["alpha.md"]
    assert flat[0].size == 5
    assert isinstance(flat[0].last_modified, datetime)

    rec = t.list_objects(recursive=True)
    assert [o.key for o in rec] == ["alpha.md", "sub/img.png"]

    assert t.read_object("alpha.md") == b"hello"
    assert t.stat_object("alpha.md").size == 5
    assert t.stat_object("missing.md") is None
    assert t.exists("alpha.md") is True
    assert t.exists("missing.md") is False

    t.write_object("beta.md", b"first\n")
    t.write_object("beta.md", b"second\n", append=True)
    assert t.read_object("beta.md") == b"first\nsecond\n"

    t.delete_object("alpha.md")
    assert t.exists("alpha.md") is False
    with pytest.raises(ObjectNotFound):
        t.read_object("alpha.md")

    t.probe()


@mock_aws
def test_s3_transport_prefix():
    conn = boto3.client("s3", region_name="us-east-1")
    conn.create_bucket(Bucket="testbucket")
    conn.put_object(Bucket="testbucket", Key="prefix/alpha.md", Body=b"a")
    conn.put_object(Bucket="testbucket", Key="prefix/sub/img.png", Body=b"\x89PNG")
    conn.put_object(Bucket="testbucket", Key="other/file.md", Body=b"x")

    t = S3Transport("testbucket", "prefix")
    assert [o.key for o in t.list_objects()] == ["alpha.md"]
    assert [o.key for o in t.list_objects(recursive=True)] == ["alpha.md", "sub/img.png"]
    assert t.read_object("alpha.md") == b"a"
    assert t.exists("other/file.md") is False


def test_local_factory(tmp_path):
    t = transport.local(tmp_path)
    assert isinstance(t, LocalTransport)
    assert t.root == (tmp_path).resolve()
