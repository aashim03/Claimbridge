"""Local text embeddings (fastembed, bge-small, 384-dim). No API key needed."""
from functools import lru_cache

from claimbridge import config


@lru_cache(maxsize=1)
def _model():
    from fastembed import TextEmbedding
    return TextEmbedding(model_name=config.EMBED_MODEL, cache_dir=config.EMBED_CACHE)


def embed(texts: list[str]) -> list[list[float]]:
    return [[float(x) for x in v] for v in _model().embed(texts)]


def embed_one(text: str) -> list[float]:
    return embed([text])[0]
