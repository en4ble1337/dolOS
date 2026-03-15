from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from memory.search import EmbeddingService


@pytest.fixture
def embedding_service() -> EmbeddingService:
    with patch('sentence_transformers.SentenceTransformer') as mock_st:
        # Mock the model's encode method
        mock_model = MagicMock()
        # Return a numpy array (simulating an embedding)
        mock_model.encode.side_effect = lambda x, **kwargs: np.array([0.1, 0.2, 0.3]) if isinstance(x, str) else np.array([[0.1, 0.2, 0.3]] * len(x))
        mock_model.get_sentence_embedding_dimension.return_value = 3
        mock_st.return_value = mock_model

        service = EmbeddingService(model_name="all-MiniLM-L6-v2")
        return service


def test_embedding_service_initialization(embedding_service: EmbeddingService) -> None:
    assert embedding_service is not None
    assert embedding_service.model is not None


def test_encode_single_text(embedding_service: EmbeddingService) -> None:
    text = "Hello world"
    embedding = embedding_service.encode(text)

    assert isinstance(embedding, list)
    assert len(embedding) == 3
    assert embedding == [0.1, 0.2, 0.3]


def test_encode_multiple_texts(embedding_service: EmbeddingService) -> None:
    texts = ["Hello", "World"]
    embeddings = embedding_service.encode(texts)

    assert isinstance(embeddings, list)
    assert len(embeddings) == 2
    # Ensure each item is a list before checking its length
    for e in embeddings:
        assert isinstance(e, list)
        assert len(e) == 3
    assert embeddings[0] == [0.1, 0.2, 0.3]


def test_dimension_property(embedding_service: EmbeddingService) -> None:
    assert embedding_service.dimension == 3
