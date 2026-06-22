"""
embedding_agent.py
==================
AGENT 5 — EMBEDDING

For every enriched chunk it:
  1. Builds a *contextualized* embedding input — the chunk text prefixed with its
     document title, summary, and key concepts/frameworks. Embedding this richer
     string (rather than the bare chunk) measurably improves retrieval because
     the vector encodes context a query is likely to match against.
  2. Embeds it with a pluggable provider (Voyage by default; OpenAI or Pinecone
     integrated inference are drop-in alternatives).
  3. Flattens all metadata to Pinecone-legal types (str / number / bool /
     list[str]) and upserts with the full chunk text in metadata so retrieval
     returns ready-to-use context.

Pinecone metadata cannot be nested and is capped (~40 KB/vector), so the full
text is truncated to `config.metadata_text_char_limit` and structured objects
(entities, claims, framework links) are projected to string lists.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Protocol

from .config import Config
from .models import Chunk, DocumentExtraction

logger = logging.getLogger("avatar2.embedding")


# --------------------------------------------------------------------------- #
# Pluggable embedders
# --------------------------------------------------------------------------- #
class Embedder(Protocol):
    dimension: int

    def embed(self, texts: List[str], input_type: str = "document") -> List[List[float]]: ...


class VoyageEmbedder:
    """Anthropic's recommended embedding provider."""

    def __init__(self, config: Config):
        import voyageai

        config.require("voyage_api_key")
        self._client = voyageai.Client(api_key=config.voyage_api_key)
        self._model = config.voyage_model
        self.dimension = config.embedding_dimension

    def embed(self, texts: List[str], input_type: str = "document") -> List[List[float]]:
        return self._client.embed(texts, model=self._model, input_type=input_type).embeddings


class OpenAIEmbedder:
    def __init__(self, config: Config):
        from openai import OpenAI

        config.require("openai_api_key")
        self._client = OpenAI(api_key=config.openai_api_key)
        self._model = config.openai_model
        self.dimension = config.embedding_dimension

    def embed(self, texts: List[str], input_type: str = "document") -> List[List[float]]:
        resp = self._client.embeddings.create(model=self._model, input=texts)
        return [d.embedding for d in resp.data]


def make_embedder(config: Config) -> Embedder:
    provider = config.embedding_provider.lower()
    if provider == "voyage":
        return VoyageEmbedder(config)
    if provider == "openai":
        return OpenAIEmbedder(config)
    raise ValueError(f"Unknown embedding_provider: {config.embedding_provider!r}")


# --------------------------------------------------------------------------- #
# Embedding Agent
# --------------------------------------------------------------------------- #
class EmbeddingAgent:
    def __init__(self, config: Config | None = None, embedder: Embedder | None = None):
        self.config = config or Config()
        self._embedder = embedder
        self._index = None

    @property
    def embedder(self) -> Embedder:
        if self._embedder is None:
            self._embedder = make_embedder(self.config)
        return self._embedder

    @property
    def index(self):
        if self._index is None:
            self._index = self._ensure_index()
        return self._index

    # ------------------------------------------------------------------ #
    def process(self, extractions: List[DocumentExtraction], namespace: str | None = None) -> int:
        chunks = [c for ex in extractions for c in ex.chunks]
        ns = namespace or self.config.pinecone_namespace
        logger.info("Embedding + upserting %d chunks to '%s/%s'", len(chunks), self.config.pinecone_index, ns)

        upserted = 0
        for batch in self._batched(chunks, self.config.embedding_batch_size):
            inputs = [self._embedding_text(c) for c in batch]
            vectors = self.embedder.embed(inputs, input_type="document")
            records = [
                {"id": c.id, "values": v, "metadata": self._metadata(c)}
                for c, v in zip(batch, vectors)
            ]
            for sub in self._batched(records, self.config.upsert_batch_size):
                self.index.upsert(vectors=sub, namespace=ns)
                upserted += len(sub)
        logger.info("Upserted %d vectors.", upserted)
        return upserted

    # ------------------------------------------------------------------ #
    @staticmethod
    def _embedding_text(chunk: Chunk) -> str:
        """Contextual retrieval: prepend orienting context to the chunk body."""
        e = chunk.enrichment
        header_bits = [f"Document: {chunk.document_title}"]
        if e and e.summary:
            header_bits.append(f"Summary: {e.summary}")
        concepts = ", ".join(c.label for c in chunk.concepts)
        if concepts:
            header_bits.append(f"Concepts: {concepts}")
        frameworks = ", ".join(fl.framework_label for fl in chunk.framework_links)
        if frameworks:
            header_bits.append(f"Frameworks: {frameworks}")
        return "\n".join(header_bits) + "\n\n" + chunk.text

    def _metadata(self, chunk: Chunk) -> Dict:
        e = chunk.enrichment
        meta: Dict[str, object] = {
            "document_id": chunk.document_id,
            "document_title": chunk.document_title,
            "sequence": chunk.sequence,
            "char_start": chunk.char_start,
            "char_end": chunk.char_end,
            "text": chunk.text[: self.config.metadata_text_char_limit],
            "entities": [x.name for x in chunk.entities][:64],
            "concepts": [x.label for x in chunk.concepts][:64],
            "framework_concepts": [fl.framework_label for fl in chunk.framework_links][:64],
            "framework_relations": [fl.relation for fl in chunk.framework_links][:64],
            "claim_count": len(chunk.claims),
            "relationship_count": len(chunk.relationships),
        }
        if e:
            meta.update(
                {
                    "summary": e.summary[:1000],
                    "keywords": e.keywords[:32],
                    "topics": e.topics[:16],
                    "semantic_tags": e.semantic_tags[:32],
                    "audience_level": e.audience_level,
                    "related_concepts": e.related_concepts[:32],
                }
            )
        # Pinecone rejects None / empty-typed values — drop them.
        return {k: v for k, v in meta.items() if v not in (None, [], "")}

    # ------------------------------------------------------------------ #
    def _ensure_index(self):
        from pinecone import Pinecone, ServerlessSpec

        self.config.require("pinecone_api_key")
        pc = Pinecone(api_key=self.config.pinecone_api_key)
        existing = {idx.name for idx in pc.list_indexes()}
        if self.config.pinecone_index not in existing:
            logger.info("Creating Pinecone index '%s' (dim=%d)", self.config.pinecone_index, self.embedder.dimension)
            pc.create_index(
                name=self.config.pinecone_index,
                dimension=self.embedder.dimension,
                metric=self.config.pinecone_metric,
                spec=ServerlessSpec(cloud=self.config.pinecone_cloud, region=self.config.pinecone_region),
            )
        return pc.Index(self.config.pinecone_index)

    @staticmethod
    def _batched(items, size):
        for i in range(0, len(items), size):
            yield items[i : i + size]
