import pytest

from memoryfield_tool import embed


@pytest.fixture(autouse=True)
def _reset_embed_failed():
    embed._EMBED_FAILED = False
    yield
    embed._EMBED_FAILED = False


def test_embed_success(monkeypatch):
    monkeypatch.setattr(
        embed.ollama,
        "embed",
        lambda model, input, truncate: {"embeddings": [[0.1, 0.2], [0.3, 0.4]]},
    )
    result = embed.embed_texts(["hello", "world"])
    assert result == [[0.1, 0.2], [0.3, 0.4]]


def test_embed_failure_short_circuits(monkeypatch):
    calls = {"n": 0}

    def boom(model, input, truncate):
        calls["n"] += 1
        raise RuntimeError("ollama down")

    monkeypatch.setattr(embed.ollama, "embed", boom)

    assert embed.embed_texts(["a"]) is None
    assert embed.embed_texts(["b"]) is None
    assert calls["n"] == 1


def test_embed_model_constants():
    assert embed.MODEL_CODE == "nomic-embed-text-v1.5"
    assert embed.OLLAMA_MODEL == "nomic-embed-text"


def test_embed_model_env_override(monkeypatch):
    monkeypatch.setenv("MEMORYFIELD_EMBED_MODEL", "bge-m3")
    code, ollama_model = embed._configured_model()
    assert code == "bge-m3"
    assert ollama_model == "bge-m3"


def test_embed_model_env_override_with_explicit_code(monkeypatch):
    monkeypatch.setenv("MEMORYFIELD_EMBED_MODEL", "bge-m3")
    monkeypatch.setenv("MEMORYFIELD_EMBED_MODEL_CODE", "bge-m3-1.0")
    code, ollama_model = embed._configured_model()
    assert code == "bge-m3-1.0"
    assert ollama_model == "bge-m3"


def test_embed_model_no_env(monkeypatch):
    monkeypatch.delenv("MEMORYFIELD_EMBED_MODEL", raising=False)
    monkeypatch.delenv("MEMORYFIELD_EMBED_MODEL_CODE", raising=False)
    code, ollama_model = embed._configured_model()
    assert code == "nomic-embed-text-v1.5"
    assert ollama_model == "nomic-embed-text"
