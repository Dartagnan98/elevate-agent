import pytest

from plugins.memory.holographic.embeddings import EmbeddingError, build_embedding_client


def test_local_minilm_rejects_dimension_override():
    with pytest.raises(EmbeddingError, match="384-dimensional"):
        build_embedding_client(
            {
                "embedding_enabled": True,
                "embedding_provider": "local_minilm",
                "embedding_dimensions": "256",
            }
        )
