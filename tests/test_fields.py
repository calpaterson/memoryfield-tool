import click
import pytest

from memoryfield_tool import config, fields


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


def test_require_local_ok(config_env):
    field = config.add_field(config.load_config(), "notes", "/tmp/notes")
    fields.require_local(field)


def test_require_local_rejects_other(config_env):
    field = config.Field(
        name="remote",
        transport="http",
        location="https://example.com",
        created="",
        last_used="",
    )
    with pytest.raises(click.ClickException, match="only local"):
        fields.require_local(field)


def test_resolve_page_normal(connected):
    _cfg_path, field_path = connected
    cfg = config.load_config()
    field = config.get_field(cfg, "notes")
    assert fields.resolve_page(field, "alpha.md") == (field_path / "alpha.md").resolve()


def test_resolve_page_rejects_escape(connected):
    _cfg_path, field_path = connected
    cfg = config.load_config()
    field = config.get_field(cfg, "notes")
    with pytest.raises(click.ClickException, match="escapes"):
        fields.resolve_page(field, "../outside.md")
    with pytest.raises(click.ClickException, match="escapes"):
        fields.resolve_page(field, "/etc/passwd")
