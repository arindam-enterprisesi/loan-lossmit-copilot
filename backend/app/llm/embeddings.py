"""Embeddings behind the same provider switch as chat (``embeddings`` in llm.yaml).

Every result records the provider, model and vector dimension, because vectors
from two models can never be mixed in one index. If config names an expected
dimension, a vector of any other length is an error.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from app.llm.config import EmbeddingConfig, load_llm_config

embed_log = logging.getLogger("app.llm.embeddings")

EmbeddingsFactory = Callable[[EmbeddingConfig], Any]


class EmbeddingError(Exception):
    pass


@dataclass(frozen=True)
class EmbeddingResult:
    vectors: list[list[float]]
    provider: str
    model: str
    dimension: int


def _openai(cfg: EmbeddingConfig) -> Any:
    from langchain_openai import OpenAIEmbeddings

    return OpenAIEmbeddings(model=cfg.model, dimensions=cfg.dimensions)  # OPENAI_API_KEY


def _gemini(cfg: EmbeddingConfig) -> Any:
    from langchain_google_genai import GoogleGenerativeAIEmbeddings

    kwargs: dict[str, Any] = {"model": cfg.model}
    if cfg.dimensions:
        kwargs["output_dimensionality"] = cfg.dimensions
    return GoogleGenerativeAIEmbeddings(**kwargs)  # GOOGLE_API_KEY


def _bedrock(cfg: EmbeddingConfig) -> Any:
    import os

    from langchain_aws import BedrockEmbeddings

    region = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION")
    return BedrockEmbeddings(model_id=cfg.model, region_name=region)


FACTORIES: dict[str, EmbeddingsFactory] = {
    "openai": _openai,
    "gemini": _gemini,
    "bedrock": _bedrock,  # e.g. amazon.titan-embed-text-v2:0
}


class Embedder:
    def __init__(
        self,
        config: EmbeddingConfig,
        factories: dict[str, EmbeddingsFactory] | None = None,
    ) -> None:
        available = factories if factories is not None else FACTORIES
        factory = available.get(config.provider)
        if factory is None:
            raise EmbeddingError(
                f"provider '{config.provider}' has no embeddings adapter; "
                f"choose one of {sorted(available)}"
            )
        self.config = config
        self._factory = factory
        self._client: Any | None = None

    def _get_client(self) -> Any:
        if self._client is None:
            self._client = self._factory(self.config)
        return self._client

    def _result(self, vectors: list[list[float]], started: float, op: str) -> EmbeddingResult:
        lengths = {len(v) for v in vectors}
        if len(lengths) > 1:
            raise EmbeddingError(f"mixed vector lengths {sorted(lengths)} from one call")
        dimension = lengths.pop() if lengths else (self.config.dimensions or 0)
        if self.config.dimensions and vectors and dimension != self.config.dimensions:
            raise EmbeddingError(
                f"{self.config.model} returned {dimension} dimensions; "
                f"config expects {self.config.dimensions}"
            )
        fields = {
            "op": op,
            "provider": self.config.provider,
            "model": self.config.model,
            "count": len(vectors),
            "dimension": dimension,
            "latency_ms": round((time.perf_counter() - started) * 1000),
        }
        embed_log.info(json.dumps(fields, sort_keys=True))
        return EmbeddingResult(vectors, self.config.provider, self.config.model, dimension)

    async def embed_documents(self, texts: Sequence[str]) -> EmbeddingResult:
        started = time.perf_counter()
        if not texts:
            return self._result([], started, "embed_documents")
        vectors = await self._get_client().aembed_documents(list(texts))
        return self._result([list(map(float, v)) for v in vectors], started, "embed_documents")

    async def embed_query(self, text: str) -> EmbeddingResult:
        started = time.perf_counter()
        vector = await self._get_client().aembed_query(text)
        return self._result([list(map(float, vector))], started, "embed_query")


def default_embedder() -> Embedder:
    config = load_llm_config()
    if config.embeddings is None:
        raise EmbeddingError("llm.yaml has no 'embeddings' section")
    return Embedder(config.embeddings)
