from src.ingestion.embedder import Embedder


def test_hash_embedder_is_lightweight_deterministic_and_384_dimensional():
    embedder = Embedder(backend="hash")

    vectors = embedder.embed_texts(["HbA1c is 7.2%", "HbA1c is 7.2%"])

    assert len(vectors) == 2
    assert vectors[0] == vectors[1]
    assert len(vectors[0]) == 384
    assert all(isinstance(value, float) for value in vectors[0])


def test_hash_embedder_does_not_load_transformer_model():
    embedder = Embedder(backend="hash")

    assert embedder._model is None
    assert len(embedder.embed_query("What is the latest HbA1c?")) == 384
    assert embedder._model is None


def test_empty_batch_does_not_create_vectors():
    assert Embedder(backend="hash").embed_texts([]) == []


def test_default_backend_matches_the_configured_default():
    # A bare Embedder() must not silently fall back to hash vectors while the
    # corpus is embedded with the transformer.
    from src.config import Settings

    assert Embedder().backend == Settings().embedding_backend == "transformer"
