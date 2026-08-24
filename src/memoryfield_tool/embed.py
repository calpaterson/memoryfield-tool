import ollama

MODEL_CODE = "nomic-embed-text-v1.5"
OLLAMA_MODEL = "nomic-embed-text"

_EMBED_FAILED = False


def embed_texts(texts: list[str]) -> list[list[float]] | None:
    global _EMBED_FAILED
    if _EMBED_FAILED:
        return None
    try:
        embeddings = ollama.embed(model=OLLAMA_MODEL, input=texts, truncate=True)["embeddings"]
        return list(embeddings)
    except Exception:
        _EMBED_FAILED = True
        return None
