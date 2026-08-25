from unittest.mock import Mock, patch

from src.ingestion.embedder import Embedder


def _vector(value: float) -> list[float]:
    return [value] * 384


def test_embedder_loads_model_lazily_and_embeds_batch():
    model = Mock()
    model.encode.return_value = [_vector(0.1), _vector(0.2)]

    with patch("sentence_transformers.SentenceTransformer", return_value=model) as constructor:
        embedder = Embedder()
        constructor.assert_not_called()

        vectors = embedder.embed_texts(["HbA1c is 7.2%", "Patient takes Metformin"])

        constructor.assert_called_once_with("all-MiniLM-L6-v2")
        model.encode.assert_called_once_with(
            ["HbA1c is 7.2%", "Patient takes Metformin"], convert_to_numpy=True
        )
        assert len(vectors) == 2
        assert all(len(vector) == 384 for vector in vectors)
        assert all(isinstance(value, float) for value in vectors[0])


def test_embed_query_uses_same_model_and_returns_one_384_dimensional_vector():
    model = Mock()
    model.encode.return_value = [_vector(0.3)]

    with patch("sentence_transformers.SentenceTransformer", return_value=model):
        embedder = Embedder("test-model")
        vector = embedder.embed_query("What is the latest HbA1c?")
        second_vector = embedder.embed_query("What medication is active?")

    assert len(vector) == 384
    assert vector[0] == 0.3
    assert len(second_vector) == 384
    assert model.encode.call_count == 2


def test_empty_batch_does_not_load_model():
    with patch("sentence_transformers.SentenceTransformer") as constructor:
        assert Embedder().embed_texts([]) == []
        constructor.assert_not_called()

