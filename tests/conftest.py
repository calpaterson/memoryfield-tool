import hashlib
import urllib.request
from pathlib import Path

import pytest
from click.testing import CliRunner


def ollama_available() -> bool:
    try:
        with urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=1) as resp:
            return resp.status == 200
    except Exception:
        return False


def _fake_embed_texts(texts: list[str]) -> list[list[float]]:
    out: list[list[float]] = []
    for t in texts:
        digest = hashlib.shake_256(t.encode()).digest(768)
        out.append([b / 255.0 for b in digest])
    return out


@pytest.fixture
def config_env(tmp_path, monkeypatch):
    cfg_path = tmp_path / "config.toml"
    monkeypatch.setenv("MEMORYFIELD_TOOL_CONFIG", str(cfg_path))
    return cfg_path


@pytest.fixture
def fake_embed(monkeypatch):
    monkeypatch.setattr("memoryfield_tool.embed.embed_texts", _fake_embed_texts)
    return _fake_embed_texts


def _write_page(path: Path, title: str, summary: str, body: str) -> None:
    path.write_text(
        "---\n"
        f"title: {title}\n"
        f"summary: {summary}\n"
        "created: '2026-01-01T09:00:00Z'\n"
        "updated: '2026-01-02T09:00:00Z'\n"
        f"uuid: {_uuid_for(path.name)}\n"
        "---\n"
        f"\n{body}\n",
        encoding="utf-8",
    )


def _uuid_for(name: str) -> str:
    digest = hashlib.shake_256(name.encode()).digest(16)
    h = digest.hex()
    return f"{h[0:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:32]}"


@pytest.fixture
def field_dir(tmp_path):
    field = tmp_path / "field"
    field.mkdir()
    (field / "index.md").write_text(
        "# Notes\n\nFree-form intro, not a catalogue.\n", encoding="utf-8"
    )
    _write_page(
        field / "alpha.md",
        "Alpha Notes",
        "Notes about alpha things.",
        "Alpha is the first letter.\n",
    )
    _write_page(
        field / "beta.md",
        "Beta Notes",
        "Notes about beta things.",
        "Beta is the second letter.\n",
    )
    _write_page(
        field / "gamma.md",
        "Gamma Notes",
        "Notes about gamma things.",
        "Gamma is the third letter.\n",
    )
    return field


@pytest.fixture
def connected(config_env, field_dir):
    config_env.write_text(
        f"[memoryfields.notes]\n"
        f'transport = "local"\n'
        f'location = "{field_dir}"\n'
        f'created = "2026-01-01T00:00:00Z"\n'
        f'last_used = "2026-01-01T00:00:00Z"\n',
        encoding="utf-8",
    )
    return config_env, field_dir


@pytest.fixture
def cli_runner():
    return CliRunner()
