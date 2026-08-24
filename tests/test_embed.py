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
