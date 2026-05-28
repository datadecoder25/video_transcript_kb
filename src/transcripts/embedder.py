import numpy as np

from transcripts.config import EMBEDDING_MODEL


class Embedder:
    """Wraps sentence-transformers for embedding documents and queries.

    Supports prompt-aware models (via prompts dict) when available.
    Falls back to plain encode() for models without prompt support.
    """

    def __init__(self):
        self._model = None

    def _load_model(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer(EMBEDDING_MODEL)

    def embed_documents(self, texts: list[str], batch_size: int = 64) -> np.ndarray:
        self._load_model()
        show_progress = len(texts) > 100
        kwargs = {"batch_size": batch_size, "show_progress_bar": show_progress}
        if hasattr(self._model, "encode_document"):
            return self._model.encode_document(texts, **kwargs)
        if self._model.prompts and "document" in self._model.prompts:
            kwargs["prompt_name"] = "document"
        return self._model.encode(texts, **kwargs)

    def embed_query(self, text: str) -> np.ndarray:
        self._load_model()
        if hasattr(self._model, "encode_query"):
            return self._model.encode_query(text)
        kwargs = {}
        if self._model.prompts and "query" in self._model.prompts:
            kwargs["prompt_name"] = "query"
        return self._model.encode(text, **kwargs)
