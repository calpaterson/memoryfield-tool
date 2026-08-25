import click
import pytest

from memoryfield_tool import config, fields, index
from memoryfield_tool.transport import LocalTransport, S3Transport


def _cfg_with(*names: str, config_env):
    cfg = config.load_config()
    for n in names:
        cfg = config.with_field(cfg, config.add_field(cfg, n, f"/tmp/{n}"))
    return cfg


def test_field_root_expands_and_resolves(config_env, tmp_path):
    field = config.add_field(config.load_config(), "notes", str(tmp_path / "notes"))
    assert fields.field_root(field) == (tmp_path / "notes").resolve()


def test_connected_fields_all_sorted(config_env):
    cfg = _cfg_with("zeta", "alpha", "middle", config_env=config_env)
    names = [f.name for f in fields.connected_fields(cfg, None)]
    assert names == ["alpha", "middle", "zeta"]


def test_connected_fields_by_name(config_env):
    cfg = _cfg_with("alpha", "zeta", config_env=config_env)
    result = fields.connected_fields(cfg, "zeta")
    assert [f.name for f in result] == ["zeta"]


def test_connected_fields_unknown_name_errors(config_env):
    cfg = _cfg_with("alpha", config_env=config_env)
    with pytest.raises(click.ClickException, match="no memoryfield named"):
        fields.connected_fields(cfg, "nope")


def test_read_write_field_explicit(config_env):
    cfg = _cfg_with("alpha", "zeta", config_env=config_env)
    assert fields.read_write_field(cfg, "alpha").name == "alpha"


def test_read_write_field_zero(config_env):
    cfg = config.load_config()
    with pytest.raises(click.ClickException, match="no memoryfields connected"):
        fields.read_write_field(cfg, None)


def test_read_write_field_one(config_env):
    cfg = _cfg_with("only", config_env=config_env)
    assert fields.read_write_field(cfg, None).name == "only"


def test_read_write_field_multiple(config_env):
    cfg = _cfg_with("alpha", "zeta", config_env=config_env)
    with pytest.raises(click.ClickException, match="specify --field"):
        fields.read_write_field(cfg, None)


def test_index_location_local(field_dir, config_env):
    field = config.Field(name="notes", transport="local", location=str(field_dir))
    assert fields.index_location(field) == field_dir / index.index_filename()


def test_index_location_s3_cache(tmp_path, config_env, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    field = config.Field(name="notes", transport="s3", location="s3://bucket/prefix")
    expected = tmp_path / "cache" / "memoryfield-tool" / "indexes" / "notes.sqlite3"
    assert fields.index_location(field) == expected


def test_get_transport_local(field_dir, config_env):
    field = config.Field(name="notes", transport="local", location=str(field_dir))
    t = fields.get_transport(field)
    assert isinstance(t, LocalTransport)
    assert t.root == field_dir.resolve()


def test_get_transport_s3(config_env):
    field = config.Field(name="cadentia", transport="s3", location="s3://cadentia-bucket/cadentia")
    t = fields.get_transport(field)
    assert isinstance(t, S3Transport)
    assert t.bucket == "cadentia-bucket"
    assert t.prefix == "cadentia"


def test_get_transport_s3_forwards_credentials(config_env):
    cfg = config.load_config()
    field = config.add_field(
        cfg,
        "notes",
        "s3://bucket/prefix",
        transport="s3",
        aws_access_key_id="AKIAEXAMPLE",
        aws_secret_access_key="secret",
        aws_session_token="token",
    )
    t = fields.get_transport(field)
    assert isinstance(t, S3Transport)
    assert t.bucket == "bucket"
    assert t.prefix == "prefix"
    assert t.aws_access_key_id == "AKIAEXAMPLE"
    assert t.aws_secret_access_key == "secret"
    assert t.aws_session_token == "token"


def test_get_transport_unknown_errors(config_env):
    field = config.Field(name="remote", transport="http", location="https://example.com")
    with pytest.raises(click.ClickException, match="unknown transport"):
        fields.get_transport(field)


def test_field_summary_from_index(tmp_path, config_env):
    d = tmp_path / "notes"
    d.mkdir()
    (d / "index.md").write_text(
        "---\ntitle: Notes\nsummary: Notes about X\n---\n\n# Notes\n", encoding="utf-8"
    )
    field = config.Field(name="notes", transport="local", location=str(d))
    assert fields.field_summary(field) == "Notes about X"

    (d / "index.md").unlink()
    assert fields.field_summary(field) == ""

    (d / "index.md").write_text("---\ntitle: Notes\n---\n\n# Notes\n", encoding="utf-8")
    assert fields.field_summary(field) == ""


def test_region_for_gcs_default(config_env):
    field = config.Field(
        name="notes",
        transport="s3",
        location="s3://b/x",
        endpoint_url="https://storage.googleapis.com",
    )
    assert fields._region_for(field) == "auto"


def test_region_for_explicit_override(config_env):
    field = config.Field(
        name="notes",
        transport="s3",
        location="s3://b/x",
        endpoint_url="https://storage.googleapis.com",
        region="us-central1",
    )
    assert fields._region_for(field) == "us-central1"


def test_region_for_non_gcs_none(config_env):
    field = config.Field(name="notes", transport="s3", location="s3://b/x")
    assert fields._region_for(field) is None
