"""
extraction_agent.py
===================
AGENT 1 — EXTRACTION

Reads each document, chunks it, and for every chunk identifies:
  * concepts       (the ideas being discussed)
  * entities       (named things: people, orgs, frameworks, methods, standards)
  * relationships  (subject–predicate–object triples)
  * claims         (assertions, definitions, causal/normative statements)

Extraction is done per chunk so that downstream enrichment and embedding stay
chunk-aligned, while document-level aggregates are also produced for the mining
stage. Entities and concepts get *deterministic* ids (content hashes) so the
same "RDSG" mentioned in three documents collapses to one node later.
"""

from __future__ import annotations

import logging
from collections import OrderedDict
from typing import List

from .base import BaseAgent
from .chunking import chunk_text
from .config import Config
from .models import (
    Chunk,
    Claim,
    Concept,
    Document,
    DocumentExtraction,
    Entity,
    ExtractionResult,
    Relationship,
)
from .ontology import FrameworkOntology

logger = logging.getLogger("avatar2.extraction")

SYSTEM = """You are a knowledge-extraction engine for a semantic knowledge base \
built by an enterprise architect specializing in ontology engineering, knowledge \
graphs, and AI governance.

For the chunk of text you are given, extract:

ENTITIES — named things. Use these types: PERSON, ORGANIZATION, FRAMEWORK, METHOD,
  STANDARD, TECHNOLOGY, CONCEPT, ARTIFACT, ROLE, EVENT, OTHER. Record common
  aliases/acronyms. salience = how central the entity is to THIS chunk (0..1).

CONCEPTS — the abstract ideas, theories, or principles discussed (distinct from
  named entities). Give a one-line definition grounded in the text when possible.

RELATIONSHIPS — subject–predicate–object triples that the text actually states or
  strongly implies. Use precise predicates (e.g. "governs", "extends", "mitigates",
  "is_a", "depends_on"). Attach the verbatim evidence span. Do not invent triples.

CLAIMS — standalone propositions the author is asserting. Classify each as one of:
  definition, assertion, causal, normative, comparative, procedural, evidential.
  Keep the claim text self-contained (resolve pronouns). Attach the source span.

Rules:
- Extract only what the text supports. Prefer precision over recall; never fabricate.
- Normalize entity names to their canonical form; put variants in aliases.
- Confidence reflects how clearly the text supports the item, not your prior beliefs.

ONTOLOGY GROUNDING (top-down):
If an <ontology> scaffold is provided, treat it as the governing schema. When an
entity or concept in the text corresponds to a listed class or concept, use that
canonical label (put the surface form in aliases). When a stated relationship
matches a listed relation predicate, use that predicate. This keeps extraction
aligned to the curated knowledge base. The scaffold GROUNDS but does not LIMIT
you: still capture novel entities, concepts, and relations not yet in the
ontology — they are candidates for ontology growth.
"""

USER_TEMPLATE = """Document title: {title}
Chunk {seq} of {total}.
{ontology_block}
<chunk>
{chunk}
</chunk>

Extract entities, concepts, relationships, and claims from this chunk."""


class ExtractionAgent(BaseAgent):
    def __init__(self, config: Config | None = None, ontology: FrameworkOntology | None = None):
        super().__init__(config or Config())
        self.ontology = ontology
        self._scaffold = ""
        if self.ontology and self.config.ontology_guided_extraction:
            scaffold = self.ontology.scaffold_for_prompt(self.config.extraction_scaffold_limit)
            if scaffold:
                self._scaffold = f"\n<ontology>\n{scaffold}\n</ontology>\n"

    def process(self, document: Document) -> DocumentExtraction:
        spans = chunk_text(
            document.text,
            chunk_size=self.config.chunk_size,
            overlap=self.config.chunk_overlap,
        )
        logger.info("Extracting '%s' -> %d chunks", document.title, len(spans))

        chunks: List[Chunk] = []
        for i, (chunk_str, start, end) in enumerate(spans):
            result = self._extract_chunk(document.title, chunk_str, i + 1, len(spans))
            chunks.append(
                Chunk(
                    id=f"{document.id}::chunk_{i:04d}",
                    document_id=document.id,
                    document_title=document.title,
                    sequence=i,
                    text=chunk_str,
                    char_start=start,
                    char_end=end,
                    entities=self._dedupe([Entity.from_raw(e) for e in result.entities]),
                    concepts=self._dedupe([Concept.from_raw(c) for c in result.concepts]),
                    relationships=[Relationship.from_raw(r) for r in result.relationships],
                    claims=[Claim.from_raw(c) for c in result.claims],
                )
            )

        return DocumentExtraction(
            document_id=document.id,
            title=document.title,
            source_path=document.source_path,
            chunks=chunks,
        )

    def process_corpus(self, documents: List[Document]) -> List[DocumentExtraction]:
        return [self.process(d) for d in documents]

    # ------------------------------------------------------------------ #
    def _extract_chunk(self, title: str, chunk: str, seq: int, total: int) -> ExtractionResult:
        return self.structured(
            model=self.config.extraction_model,
            system=SYSTEM,
            user_content=USER_TEMPLATE.format(
                title=title, seq=seq, total=total, chunk=chunk, ontology_block=self._scaffold
            ),
            output_model=ExtractionResult,
        )

    @staticmethod
    def _dedupe(items):
        """Collapse items sharing the same deterministic id within a chunk."""
        seen = OrderedDict()
        for it in items:
            if it.id not in seen:
                seen[it.id] = it
        return list(seen.values())
