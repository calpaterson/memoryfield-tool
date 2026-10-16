import os

import ollama

DEFAULT_MODEL_CODE = "nomic-embed-text-v1.5"
DEFAULT_OLLAMA_MODEL = "nomic-embed-text"


def _configured_model() -> tuple[str, str]:
    """Return the (model_code, ollama_model) pair to use.

    The default is nomic-embed-text-v1.5.  Another ollama embedding model can
    be selected via the MEMORYFIELD_EMBED_MODEL environment variable.  The
    model code (which names the vector index file) then defaults to the ollama
    model name (this follows the spec, which says a provider's shorthand may
    omit the version, eg: ollama's "nomic-embed-text" for
    "nomic-embed-text-v1.5") and can be pinned explicitly via
    MEMORYFIELD_EMBED_MODEL_CODE.
    """
    ollama_model = os.environ.get("MEMORYFIELD_EMBED_MODEL")
    if ollama_model is None:
        return DEFAULT_MODEL_CODE, DEFAULT_OLLAMA_MODEL
    model_code = os.environ.get("MEMORYFIELD_EMBED_MODEL_CODE", ollama_model)
    return model_code, ollama_model


MODEL_CODE, OLLAMA_MODEL = _configured_model()

_EMBED_FAILED = False


def embed_texts(texts: list[str]) -> list[list[float]] | None:
    global _EMBED_FAILED
    if _EMBED_FAILED:
        return None
    try:
        embeddings = ollama.embed(model=OLLAMA_MODEL, input=texts, truncate=True)["embeddings"]
        return list(embeddings)
    except Exception as e:
        print(f"embedding failed: {e}")
        _EMBED_FAILED = True
        return None
