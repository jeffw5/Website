"""
config.py
=========
One place to tune the pipeline. Everything reads from environment variables by
default so no secrets live in code, but you can also construct a Config object
directly and pass it to the agents.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Config:
    # --- LLM (Anthropic) ---------------------------------------------------- #
    anthropic_api_key: Optional[str] = field(default_factory=lambda: os.getenv("ANTHROPIC_API_KEY"))
    # Sonnet is the quality/cost sweet spot for extraction & enrichment.
    # Drop to haiku for very high-volume corpora; raise to opus for hard reasoning.
    extraction_model: str = "claude-sonnet-4-6"
    mining_model: str = "claude-sonnet-4-6"
    enrichment_model: str = "claude-sonnet-4-6"
    max_tokens: int = 4096
    llm_max_retries: int = 3

    # --- Embeddings --------------------------------------------------------- #
    # provider: "voyage" (Anthropic's recommendation) | "openai" | "pinecone"
    embedding_provider: str = "voyage"
    voyage_api_key: Optional[str] = field(default_factory=lambda: os.getenv("VOYAGE_API_KEY"))
    voyage_model: str = "voyage-3.5"          # 1024-dim by default
    openai_api_key: Optional[str] = field(default_factory=lambda: os.getenv("OPENAI_API_KEY"))
    openai_model: str = "text-embedding-3-large"  # 3072-dim
    embedding_dimension: int = 1024            # MUST match the chosen model
    embedding_batch_size: int = 96

    # --- Pinecone ----------------------------------------------------------- #
    pinecone_api_key: Optional[str] = field(default_factory=lambda: os.getenv("PINECONE_API_KEY"))
    pinecone_index: str = "avatar-kb"
    pinecone_namespace: str = "default"
    pinecone_cloud: str = "aws"
    pinecone_region: str = "us-east-1"
    pinecone_metric: str = "cosine"
    upsert_batch_size: int = 100
    metadata_text_char_limit: int = 30000  # keep under Pinecone's ~40KB/vector cap

    # --- Chunking ----------------------------------------------------------- #
    chunk_size: int = 1200       # target characters per chunk
    chunk_overlap: int = 200     # character overlap between consecutive chunks

    # --- Ontology source ---------------------------------------------------- #
    # "graphdb" -> load the live ontology from value-kb (top-down backbone)
    # "json"    -> load the static seed file (offline / testing)
    ontology_source: str = "graphdb"
    framework_ontology_path: str = "avatar2/ontology/framework_concepts.json"
    # When true, the Extraction Agent is given the ontology scaffold so it
    # extracts *against* your schema instead of purely bottom-up.
    ontology_guided_extraction: bool = True
    # Cap how much of the ontology is injected into the extraction prompt.
    # For a large value-kb, supply a pre-retrieved shortlist instead (see README).
    extraction_scaffold_limit: int = 120

    # --- GraphDB (value-kb) ------------------------------------------------- #
    # Point base_url at your CORS proxy or directly at GraphDB.
    graphdb_base_url: Optional[str] = field(default_factory=lambda: os.getenv("GRAPHDB_URL"))
    graphdb_repository: str = "value-kb"
    graphdb_named_graph: Optional[str] = field(default_factory=lambda: os.getenv("GRAPHDB_NAMED_GRAPH"))
    graphdb_timeout: int = 60

    def require(self, *attrs: str) -> None:
        """Fail loudly and early if a needed credential/setting is missing."""
        missing = [a for a in attrs if not getattr(self, a, None)]
        if missing:
            raise RuntimeError(
                "Missing required configuration: "
                + ", ".join(missing)
                + ". Set the matching environment variable or pass it to Config()."
            )
