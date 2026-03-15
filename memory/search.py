from typing import List, Union, cast


class EmbeddingService:
    """Service for converting text to embedding vectors using sentence-transformers."""

    def __init__(self, model_name: str = "all-MiniLM-L6-v2") -> None:
        """Initialize the embedding model.

        Args:
            model_name: The name of the sentence-transformers model to use.
        """
        from sentence_transformers import SentenceTransformer
        self.model = SentenceTransformer(model_name)
        # Get dimension by encoding a dummy string
        self._dimension = self.model.get_sentence_embedding_dimension()

    def encode(self, texts: Union[str, List[str]]) -> Union[List[float], List[List[float]]]:
        """Convert text or list of texts to embeddings.

        Args:
            texts: A single string or a list of strings to encode.

        Returns:
            A list of floats for a single text, or a list of lists of floats for multiple texts.
        """
        embeddings = self.model.encode(texts, convert_to_numpy=True)

        # Type narrowing for mypy
        if isinstance(texts, str):
            return cast(List[float], embeddings.tolist())
        return cast(List[List[float]], embeddings.tolist())

    @property
    def dimension(self) -> int:
        """Return the dimension of the embedding vectors."""
        dim = self._dimension
        return cast(int, dim) if dim is not None else 0
