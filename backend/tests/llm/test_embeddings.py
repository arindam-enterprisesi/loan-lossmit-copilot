from typing import Any

import pytest

from app.llm.config import EmbeddingConfig, load_llm_config
from app.llm.embeddings import Embedder, EmbeddingError


class FakeEmbeddings:
    def __init__(self, dimension: int) -> None:
        self.dimension = dimension

    async def aembed_documents(self, texts: list[str]) -> list[list[float]]:
        return [[0.1] * self.dimension for _ in texts]

    async def aembed_query(self, text: str) -> list[float]:
        return [0.2] * self.dimension


def embedder(dimension: int, expected: int | None = 4) -> Embedder:
    config = EmbeddingConfig(provider="fake", model="fake-embed", dimensions=expected)
    factories: dict[str, Any] = {"fake": lambda cfg: FakeEmbeddings(dimension)}
    return Embedder(config, factories)


async def test_results_record_model_and_dimension() -> None:
    docs = await embedder(4).embed_documents(["a", "b"])
    assert (docs.provider, docs.model, docs.dimension) == ("fake", "fake-embed", 4)
    assert len(docs.vectors) == 2

    query = await embedder(4).embed_query("q")
    assert query.dimension == 4
    assert len(query.vectors) == 1


async def test_dimension_mismatch_is_an_error() -> None:
    with pytest.raises(EmbeddingError, match="expects 4"):
        await embedder(8).embed_query("q")
    # Without an expected dimension the actual one is recorded.
    assert (await embedder(8, expected=None).embed_query("q")).dimension == 8


def test_provider_without_embeddings_is_rejected() -> None:
    with pytest.raises(EmbeddingError, match="no embeddings adapter"):
        Embedder(EmbeddingConfig(provider="anthropic", model="x"))


def test_repo_config_embedding_provider_has_adapter() -> None:
    config = load_llm_config().embeddings
    assert config is not None
    Embedder(config)  # constructing does not call the provider
