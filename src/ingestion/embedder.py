"""Lazy sentence-transformers embedding service."""


class Embedder:
    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        self.model_name = model_name
        self._model = None

    def _get_model(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self.model_name)
        return self._model

    @staticmethod
    def _as_vectors(encoded) -> list[list[float]]:
        if hasattr(encoded, "tolist"):
            encoded = encoded.tolist()
        if not encoded:
            return []
        if isinstance(encoded[0], (int, float)):
            encoded = [encoded]

        vectors: list[list[float]] = []
        for vector in encoded:
            if hasattr(vector, "tolist"):
                vector = vector.tolist()
            values = [float(value) for value in vector]
            if len(values) != 384:
                raise ValueError(f"Expected 384-dimensional embedding, got {len(values)}")
            vectors.append(values)
        return vectors

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of texts. Returns list of 384-dim vectors."""
        if not texts:
            return []
        encoded = self._get_model().encode(texts, convert_to_numpy=True)
        vectors = self._as_vectors(encoded)
        if len(vectors) != len(texts):
            raise ValueError(
                f"Embedding model returned {len(vectors)} vectors for {len(texts)} texts"
            )
        return vectors

    def embed_query(self, query: str) -> list[float]:
        """Embed a single query text."""
        vectors = self.embed_texts([query])
        return vectors[0]

