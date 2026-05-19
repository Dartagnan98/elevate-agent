import threading

import pytest

from plugins.memory.holographic.embeddings import (
    EmbeddingError,
    HashEmbeddingClient,
    build_embedding_client,
)


def _counting(client):
    """Wrap _embed_uncached so the test can count real (uncached) computes."""
    calls = {"n": 0}
    orig = client._embed_uncached

    def counted(text):
        calls["n"] += 1
        return orig(text)

    client._embed_uncached = counted
    return calls


def test_embed_memoizes_identical_input():
    """Recall embeds the same query string in multiple lanes per turn; the
    cache must collapse those to one compute with an identical result."""
    c = HashEmbeddingClient()
    calls = _counting(c)

    a1 = c.embed("hello world")
    a2 = c.embed("hello world")
    b1 = c.embed("different text")

    assert a1 is a2, "identical input must return the memoized object"
    assert b1.vector != a1.vector, "distinct input must still compute distinctly"
    assert calls["n"] == 2, "one compute per distinct string, not per call"


def test_embed_many_reuses_cache_for_repeats():
    c = HashEmbeddingClient()
    calls = _counting(c)

    res = c.embed_many(["x", "x", "y"])

    assert len(res) == 3
    assert res[0].vector == res[1].vector
    assert calls["n"] == 2, "repeated text in a batch hits the cache"


def test_embed_cache_is_bounded():
    c = HashEmbeddingClient()
    c._embed_cache_max = 8
    for i in range(50):
        c.embed(f"q{i}")
    assert len(c._embed_cache) <= 8


def test_embed_cache_is_thread_safe():
    """The background prefetch thread and the request thread both call
    embed(); concurrent access must not raise or corrupt the cache."""
    c = HashEmbeddingClient()
    errs: list[Exception] = []

    def worker(k: int) -> None:
        try:
            for _ in range(100):
                c.embed(f"key{k % 5}")
        except Exception as exc:  # pragma: no cover - failure path
            errs.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errs, f"thread errors: {errs}"


def test_local_minilm_rejects_dimension_override():
    with pytest.raises(EmbeddingError, match="384-dimensional"):
        build_embedding_client(
            {
                "embedding_enabled": True,
                "embedding_provider": "local_minilm",
                "embedding_dimensions": "256",
            }
        )
