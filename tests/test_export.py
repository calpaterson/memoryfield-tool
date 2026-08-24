import io
import zipfile

import boto3
import click
import pytest
from moto import mock_aws

from memoryfield_tool import config, export


def _field(field_dir):
    return config.Field(name="notes", transport="local", location=str(field_dir))


def _zip_names(zf_bytes: bytes) -> list[str]:
    with zipfile.ZipFile(io.BytesIO(zf_bytes)) as zf:
        return zf.namelist()


def test_export_contents(field_dir, tmp_path):
    (field_dir / "image.png").write_bytes(b"\x89PNG\r\n")
    (field_dir / "nomic-embed-text-v1.5.sqlite3.lock").write_text("", encoding="utf-8")

    out = tmp_path / "notes.memoryfield.zip"
    export.export_field(_field(field_dir), out)

    assert out.is_file()
    names = _zip_names(out.read_bytes())
    assert "alpha.md" in names
    assert "beta.md" in names
    assert "gamma.md" in names
    assert "index.md" in names
    assert "image.png" in names
    assert "nomic-embed-text-v1.5.sqlite3.lock" in names


def test_export_extension(field_dir, tmp_path):
    out = tmp_path / "custom"
    export.export_field(_field(field_dir), out)
    assert out.is_file()


def test_export_rejects_inside_field(field_dir):
    with pytest.raises(click.ClickException, match="inside the field"):
        export.export_field(_field(field_dir), field_dir / "out.zip")


def test_export_bytesio_matches_path(field_dir, tmp_path):
    (field_dir / "image.png").write_bytes(b"\x89PNG\r\n")

    out_path = tmp_path / "notes.memoryfield.zip"
    export.export_field(_field(field_dir), out_path)

    buf = io.BytesIO()
    export.export_field(_field(field_dir), buf)

    assert buf.getvalue() == out_path.read_bytes()


def test_export_bytesio_valid_zip(field_dir):
    buf = io.BytesIO()
    export.export_field(_field(field_dir), buf)
    names = _zip_names(buf.getvalue())
    assert "alpha.md" in names
    assert "index.md" in names


@mock_aws
def test_export_s3_field():
    conn = boto3.client("s3", region_name="us-east-1")
    conn.create_bucket(Bucket="testbucket")
    conn.put_object(Bucket="testbucket", Key="prefix/index.md", Body=b"# Index\n")
    conn.put_object(Bucket="testbucket", Key="prefix/alpha.md", Body=b"# Alpha\n")
    conn.put_object(Bucket="testbucket", Key="prefix/assets/logo.png", Body=b"\x89PNG")

    field = config.Field(name="notes", transport="s3", location="s3://testbucket/prefix")
    buf = io.BytesIO()
    export.export_field(field, buf)

    with zipfile.ZipFile(io.BytesIO(buf.getvalue())) as zf:
        names = zf.namelist()
        assert names == ["alpha.md", "assets/logo.png", "index.md"]
        assert zf.read("alpha.md") == b"# Alpha\n"
        assert zf.read("assets/logo.png") == b"\x89PNG"
