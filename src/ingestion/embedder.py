"""Small, deterministic embedding service with an optional transformer backend."""

import hashlib
import math
import re
from collections.abc import Iterable


class Embedder:
    """Embed text without requiring a machine-learning runtime by default."""

    DIMENSIONS = 384
    _TOKEN_PATTERN = re.compile(r"[a-z0-9]+")
    _QUERY_EXPANSIONS = {
        "hba1c": "hemoglobin a1c",
        "hb a1c": "hemoglobin a1c",
    }

    def __init__(self, model_name: str = "all-MiniLM-L6-v2", backend: str = "transformer"):
        if backend not in {"hash", "transformer"}:
            raise ValueError(f"Unsupported embedding backend: {backend}")
        self.model_name = model_name
        self.backend = backend
        self._model = None

    def _get_model(self):
        if self._model is None:
            if self.backend != "transformer":
                return None
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self.model_name)
        return self._model

    @classmethod
    def _hash_features(cls, text: str) -> Iterable[str]:
        tokens = cls._TOKEN_PATTERN.findall(text.lower())
        yield from tokens
        yield from (f"{left}_{right}" for left, right in zip(tokens, tokens[1:]))

    @classmethod
    def _hash_embed(cls, text: str) -> list[float]:
        vector = [0.0] * cls.DIMENSIONS
        for feature in cls._hash_features(text):
            digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
            value = int.from_bytes(digest, "big")
            index = value % cls.DIMENSIONS
            sign = 1.0 if value & 1 else -1.0
            vector[index] += sign

        norm = math.sqrt(sum(value * value for value in vector))
        return [value / norm for value in vector] if norm else vector

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
            if len(values) != Embedder.DIMENSIONS:
                raise ValueError(
                    f"Expected {Embedder.DIMENSIONS}-dimensional embedding, got {len(values)}"
                )
            vectors.append(values)
        return vectors

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of texts as 384-dimensional vectors."""
        if not texts:
            return []
        if self.backend == "hash":
            return [self._hash_embed(text) for text in texts]

        encoded = self._get_model().encode(texts, convert_to_numpy=True)
        vectors = self._as_vectors(encoded)
        if len(vectors) != len(texts):
            raise ValueError(
                f"Embedding model returned {len(vectors)} vectors for {len(texts)} texts"
            )
        return vectors

    def embed_query(self, query: str) -> list[float]:
        """Embed a single query text."""
        # Match common clinical abbreviations to their FHIR display names.
        for abbreviation, expansion in self._QUERY_EXPANSIONS.items():
            query = re.sub(
                rf"\b{re.escape(abbreviation)}\b",
                f"{abbreviation} {expansion}",
                query,
                flags=re.IGNORECASE,
            )
        return self.embed_texts([query])[0]
