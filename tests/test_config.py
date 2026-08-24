from pathlib import Path

import click
import pytest

from memoryfield_tool import config


def test_default_path(monkeypatch):
    monkeypatch.delenv("MEMORYFIELD_TOOL_CONFIG", raising=False)
    assert config.config_path() == Path("~/.config/memoryfield-tool.toml").expanduser()


def test_env_override(config_env):
    assert config.config_path() == config_env


def test_load_missing_file_returns_empty(config_env):
    cfg = config.load_config()
    assert cfg.fields == {}
    assert cfg.path == config_env


def test_empty_config_roundtrip(config_env):
    cfg = config.load_config()
    config.save_config(cfg)
    cfg2 = config.load_config()
    assert cfg2.fields == {}
    assert config_env.is_file()


def test_add_get_remove(config_env):
    cfg = config.load_config()
    field = config.add_field(cfg, "notes", "/tmp/notes")
    assert field.name == "notes"
    assert field.transport == "local"
    assert field.location == "/tmp/notes"

    cfg = config.with_field(cfg, field)
    config.save_config(cfg)

    reloaded = config.load_config()
    assert config.get_field(reloaded, "notes") == field

    removed = config.remove_field(reloaded, "notes")
    assert "notes" not in removed.fields


def test_saved_config_has_no_metadata(config_env):
    cfg = config.load_config()
    field = config.add_field(cfg, "notes", "/tmp/notes")
    config.save_config(config.with_field(cfg, field))
    text = config_env.read_text(encoding="utf-8")
    assert "transport" in text
    assert "location" in text
    assert "last_used" not in text
    assert "created" not in text


def test_duplicate_name_error(config_env):
    cfg = config.load_config()
    field = config.add_field(cfg, "notes", "/tmp/a")
    config.save_config(config.with_field(cfg, field))
    cfg = config.load_config()
    with pytest.raises(click.ClickException, match="already connected"):
        config.add_field(cfg, "notes", "/tmp/b")


def test_invalid_name_error(config_env):
    cfg = config.load_config()
    with pytest.raises(click.ClickException, match="invalid memoryfield name"):
        config.add_field(cfg, "Bad Name", "/tmp/a")
    with pytest.raises(click.ClickException, match="invalid memoryfield name"):
        config.add_field(cfg, "UPPER", "/tmp/a")
    with pytest.raises(click.ClickException, match="invalid memoryfield name"):
        config.add_field(cfg, "has_underscore", "/tmp/a")


def test_get_unknown_field_errors(config_env):
    cfg = config.load_config()
    with pytest.raises(click.ClickException, match="no memoryfield named"):
        config.get_field(cfg, "missing")


def test_corrupt_toml_raises(config_env):
    config_env.write_text("this is not [valid toml", encoding="utf-8")
    with pytest.raises(click.ClickException, match="invalid TOML"):
        config.load_config()


def test_atomic_write_reload_after_add(config_env):
    cfg = config.load_config()
    field = config.add_field(cfg, "notes", "/tmp/notes")
    cfg = config.with_field(cfg, field)
    config.save_config(cfg)

    reloaded = config.load_config()
    assert config.get_field(reloaded, "notes") == field


def test_legacy_metadata_keys_ignored(config_env):
    config_env.write_text(
        "[memoryfields.notes]\n"
        'transport = "local"\n'
        'location = "/tmp/notes"\n'
        'created = "2026-01-01T00:00:00Z"\n'
        'last_used = "2026-01-01T00:00:00Z"\n',
        encoding="utf-8",
    )
    cfg = config.load_config()
    field = config.get_field(cfg, "notes")
    assert field.transport == "local"
    assert field.location == "/tmp/notes"
    assert not hasattr(field, "created")
    assert not hasattr(field, "last_used")


def test_unknown_top_level_key_ignored(config_env):
    config_env.write_text(
        'future = "some unknown key"\n'
        "[memoryfields.notes]\n"
        'transport = "local"\n'
        'location = "/tmp/notes"\n',
        encoding="utf-8",
    )
    cfg = config.load_config()
    assert "notes" in cfg.fields
