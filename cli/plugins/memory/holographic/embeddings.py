"""Embedding provider adapters for Elevate memory.

The memory store owns facts, entities, trust, and retrieval policy. This module
only turns text into vectors through a swappable backend.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import struct
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Iterable


class EmbeddingError(RuntimeError):
    """Raised when an embedding provider cannot return a vector."""


@dataclass(frozen=True)
class EmbeddingResult:
    provider: str
    model: str
    dimensions: int
    vector: list[float]


def parse_bool(value: object, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on", "enabled"}:
        return True
    if text in {"0", "false", "no", "off", "disabled"}:
        return False
    return default


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def vector_to_blob(vector: Iterable[float]) -> bytes:
    values = [float(v) for v in vector]
    if not values:
        return b""
    return struct.pack("<" + "f" * len(values), *values)


def blob_to_vector(blob: bytes, dimensions: int) -> list[float]:
    if not blob or dimensions <= 0:
        return []
    expected = dimensions * 4
    if len(blob) != expected:
        raise ValueError(f"vector blob is {len(blob)} bytes, expected {expected}")
    return list(struct.unpack("<" + "f" * dimensions, blob))


def cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = 0.0
    norm_a = 0.0
    norm_b = 0.0
    for av, bv in zip(a, b):
        dot += av * bv
        norm_a += av * av
        norm_b += bv * bv
    if norm_a <= 0.0 or norm_b <= 0.0:
        return 0.0
    return dot / (math.sqrt(norm_a) * math.sqrt(norm_b))


class BaseEmbeddingClient:
    provider = "base"

    def __init__(self, model: str, dimensions: int | None = None) -> None:
        self.model = model
        self.dimensions = dimensions

    @property
    def label(self) -> str:
        return f"{self.provider}:{self.model}"

    def embed(self, text: str) -> EmbeddingResult:
        raise NotImplementedError


class OpenAIEmbeddingClient(BaseEmbeddingClient):
    provider = "openai"

    def __init__(
        self,
        model: str = "text-embedding-3-small",
        dimensions: int | None = None,
        api_key_env: str = "OPENAI_API_KEY",
        base_url: str | None = None,
    ) -> None:
        super().__init__(model=model, dimensions=dimensions)
        api_key = os.getenv(api_key_env) or os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise EmbeddingError(
                f"{api_key_env} is not set; add it to ~/.elevate/.env or disable embeddings"
            )
        try:
            from openai import OpenAI
        except Exception as exc:  # pragma: no cover - dependency is core, but stay defensive
            raise EmbeddingError(f"openai package is not available: {exc}") from exc
        kwargs = {"api_key": api_key}
        if base_url:
            kwargs["base_url"] = base_url
            self.provider = "openai_compatible"
        self._client = OpenAI(**kwargs)

    def embed(self, text: str) -> EmbeddingResult:
        payload = {"model": self.model, "input": text, "encoding_format": "float"}
        if self.dimensions:
            payload["dimensions"] = self.dimensions
        response = self._client.embeddings.create(**payload)
        vector = [float(v) for v in response.data[0].embedding]
        return EmbeddingResult(
            provider=self.provider,
            model=self.model,
            dimensions=len(vector),
            vector=vector,
        )


class OllamaEmbeddingClient(BaseEmbeddingClient):
    provider = "ollama"

    def __init__(
        self,
        model: str = "mxbai-embed-large",
        base_url: str = "http://localhost:11434",
    ) -> None:
        super().__init__(model=model)
        self.base_url = base_url.rstrip("/")

    def embed(self, text: str) -> EmbeddingResult:
        data = json.dumps({"model": self.model, "prompt": text}).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}/api/embeddings",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except urllib.error.URLError as exc:
            raise EmbeddingError(f"ollama embeddings request failed: {exc}") from exc
        vector = body.get("embedding") or body.get("embeddings")
        if isinstance(vector, list) and vector and isinstance(vector[0], list):
            vector = vector[0]
        if not isinstance(vector, list):
            raise EmbeddingError("ollama response did not include an embedding vector")
        result = [float(v) for v in vector]
        return EmbeddingResult(
            provider=self.provider,
            model=self.model,
            dimensions=len(result),
            vector=result,
        )


class HashEmbeddingClient(BaseEmbeddingClient):
    """Deterministic local test backend.

    This is not semantically meaningful. It exists so the install harness can
    prove SQLite schema, storage, and search plumbing without any API key.
    """

    provider = "hash"

    def __init__(self, model: str = "hash-test-256", dimensions: int = 256) -> None:
        super().__init__(model=model, dimensions=dimensions)

    def embed(self, text: str) -> EmbeddingResult:
        dim = int(self.dimensions or 256)
        vector = [0.0] * dim
        for token in text.lower().split():
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            idx = int.from_bytes(digest[:4], "little") % dim
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vector[idx] += sign
        norm = math.sqrt(sum(v * v for v in vector)) or 1.0
        vector = [v / norm for v in vector]
        return EmbeddingResult(
            provider=self.provider,
            model=self.model,
            dimensions=dim,
            vector=vector,
        )


def _parse_dimensions(raw: object) -> int | None:
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        dimensions = int(text)
    except (TypeError, ValueError) as exc:
        raise EmbeddingError(
            f"embedding_dimensions must be a positive integer, got {text!r}"
        ) from exc
    if dimensions <= 0:
        raise EmbeddingError(
            f"embedding_dimensions must be a positive integer, got {dimensions}"
        )
    return dimensions


def build_embedding_client(config: dict) -> BaseEmbeddingClient | None:
    if not parse_bool(config.get("embedding_enabled"), default=False):
        return None

    provider = str(config.get("embedding_provider", "openai")).strip().lower()
    model = str(config.get("embedding_model") or "").strip()
    dimensions = _parse_dimensions(config.get("embedding_dimensions", ""))

    if provider == "openai":
        return OpenAIEmbeddingClient(
            model=model or "text-embedding-3-small",
            dimensions=dimensions,
            api_key_env=str(config.get("embedding_api_key_env") or "OPENAI_API_KEY"),
        )
    if provider in {"openai_compatible", "compatible"}:
        return OpenAIEmbeddingClient(
            model=model or "text-embedding-3-small",
            dimensions=dimensions,
            api_key_env=str(config.get("embedding_api_key_env") or "ELEVATE_EMBEDDINGS_API_KEY"),
            base_url=str(config.get("embedding_base_url") or "").strip() or None,
        )
    if provider == "ollama":
        return OllamaEmbeddingClient(
            model=model or "mxbai-embed-large",
            base_url=str(config.get("embedding_base_url") or "http://localhost:11434"),
        )
    if provider == "hash":
        return HashEmbeddingClient(
            model=model or "hash-test-256",
            dimensions=dimensions or 256,
        )
    raise EmbeddingError(f"unknown embedding provider: {provider}")
