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
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Iterable


class EmbeddingError(RuntimeError):
    """Raised when an embedding provider cannot return a vector."""


def _load_env_file_if_needed(var_name: str) -> None:
    """Load simple KEY=VALUE entries from local env files without printing secrets."""
    if os.getenv(var_name) or os.getenv("OPENAI_API_KEY"):
        return
    candidates = [
        os.path.expanduser("~/.elevate/.env"),
    ]
    for path in candidates:
        try:
            with open(path, "r", encoding="utf-8") as fh:
                for line in fh:
                    raw = line.strip()
                    if not raw or raw.startswith("#") or "=" not in raw:
                        continue
                    key, value = raw.split("=", 1)
                    key = key.strip()
                    value = value.strip().strip("'\"")
                    if key and value and key not in os.environ:
                        os.environ[key] = value
        except FileNotFoundError:
            continue
        except Exception:
            continue
        if os.getenv(var_name) or os.getenv("OPENAI_API_KEY"):
            return


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

    # Bounded per-process memoization. Recall embeds the *same* query string
    # multiple times within a single turn (fact lane + document lane +
    # verifier), each previously a separate network round-trip on the
    # request thread. Memoizing the identical-input -> identical-vector
    # mapping collapses those to one call with zero behavior change.
    _embed_cache_max = 256

    def __init__(self, model: str, dimensions: int | None = None) -> None:
        self.model = model
        self.dimensions = dimensions
        self._embed_cache: dict[str, EmbeddingResult] = {}
        self._embed_cache_lock = threading.Lock()

    @property
    def label(self) -> str:
        return f"{self.provider}:{self.model}"

    def _embed_uncached(self, text: str) -> EmbeddingResult:
        raise NotImplementedError

    def embed(self, text: str) -> EmbeddingResult:
        key = text
        lock = getattr(self, "_embed_cache_lock", None)
        if lock is None:
            # Defensive: subclass that bypassed BaseEmbeddingClient.__init__.
            return self._embed_uncached(text)
        with lock:
            hit = self._embed_cache.get(key)
        if hit is not None:
            return hit
        # Network/compute happens OUTSIDE the lock so the background
        # prefetch thread and the request thread never serialize on it.
        result = self._embed_uncached(text)
        with lock:
            self._embed_cache[key] = result
            if len(self._embed_cache) > self._embed_cache_max:
                # dict preserves insertion order — drop the oldest entries.
                for stale in list(self._embed_cache)[: -self._embed_cache_max]:
                    self._embed_cache.pop(stale, None)
        return result

    def embed_many(self, texts: list[str]) -> list[EmbeddingResult]:
        return [self.embed(text) for text in texts]


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
        _load_env_file_if_needed(api_key_env)
        api_key = os.getenv(api_key_env) or os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise EmbeddingError(
                f"{api_key_env} is not set; add it to ~/.elevate/.env or disable embeddings"
            )
        try:
            from openai import OpenAI
        except Exception as exc:  # pragma: no cover - dependency is core, but stay defensive
            raise EmbeddingError(f"openai package is not available: {exc}") from exc
        # Bounded timeout + no SDK retries: this client runs on the per-turn
        # memory-prefetch hot path. The SDK default (600s, 2 retries) could
        # hang a whole turn if OpenAI is slow/unreachable. Fail fast instead;
        # the prefetch call site treats embedding failure as non-fatal.
        kwargs = {"api_key": api_key, "timeout": 10.0, "max_retries": 0}
        if base_url:
            kwargs["base_url"] = base_url
            self.provider = "openai_compatible"
        self._client = OpenAI(**kwargs)

    def _embed_uncached(self, text: str) -> EmbeddingResult:
        return self.embed_many([text])[0]

    def embed_many(self, texts: list[str]) -> list[EmbeddingResult]:
        if not texts:
            return []
        payload = {"model": self.model, "input": texts, "encoding_format": "float"}
        if self.dimensions:
            payload["dimensions"] = self.dimensions
        response = self._client.embeddings.create(**payload)
        results: list[EmbeddingResult] = []
        for item in sorted(response.data, key=lambda d: d.index):
            vector = [float(v) for v in item.embedding]
            results.append(EmbeddingResult(
                provider=self.provider,
                model=self.model,
                dimensions=len(vector),
                vector=vector,
            ))
        return results


class OllamaEmbeddingClient(BaseEmbeddingClient):
    provider = "ollama"

    def __init__(
        self,
        model: str = "mxbai-embed-large",
        base_url: str = "http://localhost:11434",
    ) -> None:
        super().__init__(model=model)
        self.base_url = base_url.rstrip("/")

    def _embed_uncached(self, text: str) -> EmbeddingResult:
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

    def _embed_uncached(self, text: str) -> EmbeddingResult:
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


class LocalMiniLMEmbeddingClient(BaseEmbeddingClient):
    """Optional local semantic backend using sentence-transformers MiniLM.

    This keeps the installer light: no model is downloaded unless the user
    explicitly selects ``embedding_provider: local_minilm`` and has the optional
    sentence-transformers dependency available.
    """

    provider = "local_minilm"

    def __init__(
        self,
        model: str = "sentence-transformers/all-MiniLM-L6-v2",
        cache_dir: str | None = None,
    ) -> None:
        super().__init__(model=model, dimensions=384)
        try:
            from sentence_transformers import SentenceTransformer
        except Exception as exc:
            raise EmbeddingError(
                "local_minilm requires the optional sentence-transformers package; "
                "install it or use embedding_provider: openai, ollama, or openai_compatible"
            ) from exc

        kwargs = {}
        if cache_dir:
            kwargs["cache_folder"] = os.path.expanduser(cache_dir)
        try:
            self._model = SentenceTransformer(model, **kwargs)
        except Exception as exc:
            raise EmbeddingError(f"local MiniLM model load failed: {exc}") from exc

    def _embed_uncached(self, text: str) -> EmbeddingResult:
        try:
            vector_obj = self._model.encode(
                text,
                normalize_embeddings=True,
                convert_to_numpy=False,
            )
        except Exception as exc:
            raise EmbeddingError(f"local MiniLM embedding failed: {exc}") from exc
        if hasattr(vector_obj, "tolist"):
            vector_obj = vector_obj.tolist()
        vector = [float(v) for v in vector_obj]
        return EmbeddingResult(
            provider=self.provider,
            model=self.model,
            dimensions=len(vector),
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
    if provider in {"local_minilm", "local-minilm", "minilm", "local"}:
        if dimensions not in (None, 384):
            raise EmbeddingError("local_minilm uses fixed 384-dimensional vectors")
        return LocalMiniLMEmbeddingClient(
            model=model or "sentence-transformers/all-MiniLM-L6-v2",
            cache_dir=str(config.get("embedding_cache_dir") or "").strip() or None,
        )
    if provider == "hash":
        return HashEmbeddingClient(
            model=model or "hash-test-256",
            dimensions=dimensions or 256,
        )
    raise EmbeddingError(f"unknown embedding provider: {provider}")
