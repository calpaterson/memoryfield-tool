import subprocess
import sys
import time

import pysqlite3 as sqlite3
import pytest
from conftest import ollama_available

from memoryfield_tool import config, fields, reindex


@pytest.fixture
def _log_tmp(monkeypatch, tmp_path):
    monkeypatch.setattr(reindex, "_LOG_DIR", tmp_path / "cache")
    monkeypatch.setattr(reindex, "LOG_PATH", tmp_path / "cache" / "reindex.log")
    return reindex.LOG_PATH


def test_spawn_argv_and_flags(connected, monkeypatch, _log_tmp):
    _cfg_path, _field_path = connected
    calls = []

    class FakePopen:
        def __init__(self, argv, **kwargs):
            calls.append((argv, kwargs))

    monkeypatch.setattr(reindex.subprocess, "Popen", FakePopen)
    reindex.spawn_background_index("notes")

    assert len(calls) == 1
    argv, kwargs = calls[0]
    assert argv == [sys.executable, "-m", "memoryfield_tool", "index", "--field", "notes"]
    assert kwargs["stdin"] is subprocess.DEVNULL
    assert kwargs["stdout"] is subprocess.DEVNULL
    assert kwargs["start_new_session"] is True
    assert kwargs["stderr"].name == str(_log_tmp)


def test_spawn_failure_swallowed(connected, monkeypatch, _log_tmp):
    _cfg_path, _field_path = connected

    def boom(argv, **kwargs):
        raise OSError("boom")

    monkeypatch.setattr(reindex.subprocess, "Popen", boom)
    reindex.spawn_background_index("notes")
    assert _log_tmp.read_bytes().startswith(b"failed to spawn background index for notes:")


def test_spawn_skipped_for_empty_unknown_field(monkeypatch, config_env, tmp_path, _log_tmp):
    config_env.write_text(
        f"[memoryfields.empty]\n"
        f'transport = "local"\n'
        f'location = "{tmp_path / "emptydir"}"\n'
        f'created = "2026-01-01T00:00:00Z"\n'
        f'last_used = "2026-01-01T00:00:00Z"\n',
        encoding="utf-8",
    )
    emptydir = tmp_path / "emptydir"
    emptydir.mkdir()

    calls = []

    class FakePopen:
        def __init__(self, argv, **kwargs):
            calls.append(argv)

    monkeypatch.setattr(reindex.subprocess, "Popen", FakePopen)
    reindex.spawn_background_index("empty")
    assert calls == []


@pytest.mark.skipif(not ollama_available(), reason="needs local ollama")
def test_background_reindex_e2e(cli_runner, config_env, tmp_path, monkeypatch):
    from memoryfield_tool import cli

    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    loc = tmp_path / "e2e"
    result = cli_runner.invoke(cli.cli, ["create", "e2e", "--location", str(loc)])
    assert result.exit_code == 0

    result = cli_runner.invoke(
        cli.cli,
        ["write", "--field", "e2e", "note.md"],
        input="---\ntitle: E2E Note\nsummary: End to end test note\n---\n\n"
        "Searchable content here.\n",
    )
    assert result.exit_code == 0

    field = config.get_field(config.load_config(), "e2e")
    index_path = fields.index_location(field)
    assert index_path == loc / "nomic-embed-text-v1.5.sqlite3"
    deadline = time.time() + 30
    indexed = False
    while time.time() < deadline and not indexed:
        if index_path.is_file():
            db = sqlite3.connect(str(index_path))
            names = {r[0] for r in db.execute("SELECT filename FROM pages")}
            db.close()
            indexed = "note.md" in names
        if not indexed:
            time.sleep(0.5)
    assert indexed, "background index never indexed note.md"

    result = cli_runner.invoke(cli.cli, ["search", "--field", "e2e", "e2e"])
    assert result.exit_code == 0
    assert "note.md" in result.output
