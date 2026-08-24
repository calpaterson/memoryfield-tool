import zipfile

import click
import pytest

from memoryfield_tool import config, export


def _field(field_dir):
    return config.Field(
        name="notes", transport="local", location=str(field_dir), created="", last_used=""
    )


def test_export_contents(field_dir, tmp_path):
    (field_dir / "image.png").write_bytes(b"\x89PNG\r\n")
    (field_dir / "nomic-embed-text-v1.5.sqlite3.lock").write_text("", encoding="utf-8")
    (field_dir / "editor~").write_text("debris", encoding="utf-8")
    (field_dir / ".DS_Store").write_text("junk", encoding="utf-8")

    out = tmp_path / "notes.memoryfield.zip"
    result = export.export_field(_field(field_dir), out)

    assert result == out
    assert out.is_file()
    with zipfile.ZipFile(out) as zf:
        names = zf.namelist()
    assert "alpha.md" in names
    assert "beta.md" in names
    assert "gamma.md" in names
    assert "index.md" in names
    assert "image.png" in names
    assert "editor~" not in names
    assert ".DS_Store" not in names
    assert not any(n.endswith(".lock") for n in names)


def test_export_extension(field_dir, tmp_path):
    out = tmp_path / "custom"
    result = export.export_field(_field(field_dir), out)
    assert result.name == "custom"


def test_export_rejects_inside_field(field_dir):
    with pytest.raises(click.ClickException, match="inside the field"):
        export.export_field(_field(field_dir), field_dir / "out.zip")
