"""
pipeline.py
===========
Orchestrates the four agents end to end:

    Extraction  ->  Relationship Mining  ->  Enrichment  ->  Embedding
       (1)               (3)                    (4)            (5)

Each stage mutates/augments the same DocumentExtraction objects, so you can run
the whole thing or stop after any stage and inspect the intermediate state. The
ontology is loaded once and shared by the mining and enrichment agents.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import List, Optional

from .config import Config
from .embedding_agent import EmbeddingAgent
from .enrichment_agent import EnrichmentAgent
from .extraction_agent import ExtractionAgent
from .models import Document, DocumentExtraction, MiningResult
from .ontology import FrameworkOntology
from .relationship_mining_agent import RelationshipMiningAgent

logger = logging.getLogger("avatar2.pipeline")


@dataclass
class PipelineResult:
    extractions: List[DocumentExtraction]
    mining: Optional[MiningResult] = None
    vectors_upserted: int = 0
    stats: dict = field(default_factory=dict)


class AvatarPipeline:
    def __init__(self, config: Config | None = None):
        self.config = config or Config()
        self.ontology = self._load_ontology()
        # The ontology grounds all three reasoning agents — top-down, not bottom-up.
        self.extraction = ExtractionAgent(self.config, ontology=self.ontology)
        self.mining = RelationshipMiningAgent(self.config, ontology=self.ontology)
        self.enrichment = EnrichmentAgent(self.config, ontology=self.ontology)
        self.embedding = EmbeddingAgent(self.config)

    def _load_ontology(self) -> FrameworkOntology:
        if self.config.ontology_source == "graphdb":
            from .graphdb import GraphDBClient

            client = GraphDBClient(self.config)
            onto = FrameworkOntology.from_graphdb(client, named_graph=self.config.graphdb_named_graph)
            logger.info(
                "Loaded %d concepts + %d relations from value-kb (graph=%s)",
                len(onto.concepts),
                len(onto.relations),
                self.config.graphdb_named_graph or "default",
            )
            return onto
        logger.info("Loading ontology from JSON seed: %s", self.config.framework_ontology_path)
        return FrameworkOntology.from_json(self.config.framework_ontology_path)

    def run(
        self,
        documents: List[Document],
        *,
        do_mining: bool = True,
        do_enrichment: bool = True,
        do_embedding: bool = True,
        use_llm_linking: bool = True,
        namespace: str | None = None,
    ) -> PipelineResult:
        logger.info("=== Avatar 2.0 ingestion: %d documents ===", len(documents))

        # Stage 1 — Extraction
        extractions = self.extraction.process_corpus(documents)
        result = PipelineResult(extractions=extractions)

        # Stage 3 — Relationship Mining
        if do_mining:
            result.mining = self.mining.process(extractions, use_llm_linking=use_llm_linking)

        # Stage 4 — Enrichment
        if do_enrichment:
            self.enrichment.process(extractions)

        # Stage 5 — Embedding
        if do_embedding:
            result.vectors_upserted = self.embedding.process(extractions, namespace=namespace)

        result.stats = self._stats(result)
        logger.info("=== Done: %s ===", result.stats)
        return result

    @staticmethod
    def _stats(result: PipelineResult) -> dict:
        chunks = [c for ex in result.extractions for c in ex.chunks]
        return {
            "documents": len(result.extractions),
            "chunks": len(chunks),
            "entities": sum(len(c.entities) for c in chunks),
            "concepts": sum(len(c.concepts) for c in chunks),
            "claims": sum(len(c.claims) for c in chunks),
            "framework_links": sum(len(c.framework_links) for c in chunks),
            "cross_document_links": len(result.mining.cross_document_links) if result.mining else 0,
            "provenance_chains": len(result.mining.provenance_chains) if result.mining else 0,
            "vectors_upserted": result.vectors_upserted,
        }
