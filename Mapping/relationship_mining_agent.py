"""
relationship_mining_agent.py
============================
AGENT 3 — RELATIONSHIP MINING

Operates on the WHOLE corpus of DocumentExtractions and produces three things:

  1. Cross-document links  — chunks in different documents that share an entity,
     a concept, or a framework, or that elaborate on / contradict each other.
     Deterministic shared-key links are computed cheaply; an optional LLM pass
     promotes the strongest candidates to typed "elaborates"/"contradicts" edges.

  2. Framework concept links — each chunk is linked to nodes in the framework
     ontology (RDSG, AICB, HSA, ...). A deterministic alias match catches the
     obvious hits; the LLM resolves the subtler ones and assigns a relation
     (mentions | defines | applies | extends | critiques) and confidence.
     These are written back onto each Chunk.framework_links.

  3. Provenance chains — lineage records of the form
     framework_concept <- claim <- chunk <- document, so any framework concept
     in the avatar can be traced to the exact claim and source that supports it.
"""

from __future__ import annotations

import itertools
import logging
from collections import defaultdict
from typing import Dict, List, Tuple

from .base import BaseAgent
from .config import Config
from .models import (
    Chunk,
    ConceptLink,
    ConceptLinkResult,
    CrossDocumentLink,
    DocumentExtraction,
    MiningResult,
    ProvenanceChain,
)
from .ontology import FrameworkOntology

logger = logging.getLogger("avatar2.mining")

LINK_SYSTEM = """You map text to a fixed framework ontology. You are given a chunk \
and a catalog of framework concepts (each with a stable id). Identify which \
framework concepts the chunk genuinely engages with.

For each link choose the most specific relation:
  mentions  — the concept is referenced
  defines   — the chunk defines or explains the concept
  applies   — the chunk uses/operationalizes the concept in a concrete setting
  extends   — the chunk builds on or generalizes the concept
  critiques — the chunk questions, limits, or argues against the concept

Only link concepts that are actually present. Use the exact framework_concept_id \
from the catalog. Provide a short verbatim evidence span. If nothing matches, \
return an empty list."""

LINK_USER = """Framework concept catalog:
{catalog}

<chunk id="{chunk_id}">
{chunk}
</chunk>

Return the framework concept links for this chunk."""


class RelationshipMiningAgent(BaseAgent):
    def __init__(self, config: Config | None = None, ontology: FrameworkOntology | None = None):
        cfg = config or Config()
        super().__init__(cfg)
        self.ontology = ontology or FrameworkOntology.from_json(cfg.framework_ontology_path)

    def process(self, extractions: List[DocumentExtraction], use_llm_linking: bool = True) -> MiningResult:
        chunks = [c for ex in extractions for c in ex.chunks]
        logger.info("Mining %d chunks across %d documents", len(chunks), len(extractions))

        self._link_frameworks(chunks, use_llm_linking)
        cross_links = self._cross_document_links(chunks)
        provenance = self._provenance_chains(chunks)

        return MiningResult(
            cross_document_links=cross_links,
            provenance_chains=provenance,
            linked_chunk_count=sum(1 for c in chunks if c.framework_links),
        )

    # ------------------------------------------------------------------ #
    # 2. Framework concept linking (deterministic + LLM)
    # ------------------------------------------------------------------ #
    def _link_frameworks(self, chunks: List[Chunk], use_llm: bool) -> None:
        for chunk in chunks:
            links: Dict[str, ConceptLink] = {}

            # (a) deterministic: alias hits on entities, concepts, and raw text
            surface = [e.name for e in chunk.entities] + [c.label for c in chunk.concepts]
            for token in surface:
                fc = self.ontology.match_alias(token)
                if fc:
                    links[fc.id] = ConceptLink(
                        framework_concept_id=fc.id,
                        framework_label=fc.label,
                        framework_iri=fc.iri,
                        relation="mentions",
                        confidence=0.9,
                        evidence=token,
                    )

            # (b) LLM: subtler links + relation typing
            if use_llm:
                result = self._llm_link(chunk)
                for raw in result.links:
                    fc = self.ontology.get(raw.framework_concept_id)
                    if not fc:
                        continue
                    links[fc.id] = ConceptLink(
                        framework_concept_id=fc.id,
                        framework_label=fc.label,
                        framework_iri=fc.iri,
                        relation=raw.relation,
                        confidence=max(raw.confidence, links.get(fc.id).confidence if fc.id in links else 0),
                        evidence=raw.evidence,
                    )

            # tag matched concepts with their ontology IRI for the embedding stage
            for concept in chunk.concepts:
                fc = self.ontology.match_alias(concept.label)
                if fc:
                    concept.ontology_iri = fc.iri

            chunk.framework_links = list(links.values())

    def _llm_link(self, chunk: Chunk) -> ConceptLinkResult:
        return self.structured(
            model=self.config.mining_model,
            system=LINK_SYSTEM,
            user_content=LINK_USER.format(
                catalog=self.ontology.catalog_for_prompt(),
                chunk_id=chunk.id,
                chunk=chunk.text,
            ),
            output_model=ConceptLinkResult,
        )

    # ------------------------------------------------------------------ #
    # 1. Cross-document links (shared entities / concepts / frameworks)
    # ------------------------------------------------------------------ #
    def _cross_document_links(self, chunks: List[Chunk]) -> List[CrossDocumentLink]:
        # invert: key -> list of (chunk, label)
        by_entity: Dict[str, List[Tuple[Chunk, str]]] = defaultdict(list)
        by_concept: Dict[str, List[Tuple[Chunk, str]]] = defaultdict(list)
        by_framework: Dict[str, List[Tuple[Chunk, str]]] = defaultdict(list)

        for c in chunks:
            for e in c.entities:
                by_entity[e.id].append((c, e.name))
            for cc in c.concepts:
                by_concept[cc.id].append((c, cc.label))
            for fl in c.framework_links:
                by_framework[fl.framework_concept_id].append((c, fl.framework_label))

        links: List[CrossDocumentLink] = []
        links += self._pairs(by_entity, "shared_entity", 0.75)
        links += self._pairs(by_concept, "shared_concept", 0.7)
        links += self._pairs(by_framework, "shared_framework", 0.85)
        return links

    @staticmethod
    def _pairs(index, relation, conf) -> List[CrossDocumentLink]:
        out: List[CrossDocumentLink] = []
        for key, members in index.items():
            for (a, label_a), (b, _) in itertools.combinations(members, 2):
                if a.document_id == b.document_id:
                    continue  # only CROSS-document
                out.append(
                    CrossDocumentLink(
                        source_chunk_id=a.id,
                        target_chunk_id=b.id,
                        source_document_id=a.document_id,
                        target_document_id=b.document_id,
                        relation=relation,
                        pivot=label_a,
                        confidence=conf,
                    )
                )
        return out

    # ------------------------------------------------------------------ #
    # 3. Provenance chains: framework <- claim <- chunk <- document
    # ------------------------------------------------------------------ #
    @staticmethod
    def _provenance_chains(chunks: List[Chunk]) -> List[ProvenanceChain]:
        chains: List[ProvenanceChain] = []
        for chunk in chunks:
            if not chunk.framework_links or not chunk.claims:
                continue
            for fl in chunk.framework_links:
                for claim in chunk.claims:
                    chains.append(
                        ProvenanceChain(
                            framework_concept_id=fl.framework_concept_id,
                            framework_label=fl.framework_label,
                            claim_id=claim.id,
                            claim_text=claim.text,
                            chunk_id=chunk.id,
                            document_id=chunk.document_id,
                            document_title=chunk.document_title,
                            relation=fl.relation,
                            confidence=round((fl.confidence + claim.confidence) / 2, 3),
                        )
                    )
        return chains
