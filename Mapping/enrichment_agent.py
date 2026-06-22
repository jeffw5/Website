"""
enrichment_agent.py
===================
AGENT 4 — ENRICHMENT

Adds a semantic-metadata layer to each chunk:
  * summary, keywords, topics, free-form semantic tags
  * audience_level  — novice / practitioner / expert, with a short rationale
  * related_concepts — framework concepts related to (but not necessarily named
    in) the chunk, drawn from the ontology so retrieval can pivot across the
    taxonomy even when a query uses adjacent vocabulary.

The audience tag is the load-bearing field: it lets the avatar answer the same
question at the right altitude (a one-line orientation for a novice vs. an
implementation-grade answer for an expert).
"""

from __future__ import annotations

import logging
from typing import List

from .base import BaseAgent
from .config import Config
from .models import Chunk, DocumentExtraction, Enrichment, EnrichmentResult
from .ontology import FrameworkOntology

logger = logging.getLogger("avatar2.enrichment")

SYSTEM = """You add a retrieval-oriented metadata layer to a chunk of a technical \
knowledge base about ontology engineering, knowledge graphs, systems engineering, \
and AI governance.

Produce:
  summary    — 1–2 sentences capturing the chunk's point, self-contained.
  keywords   — 5–12 precise terms a searcher might use (include acronyms).
  topics     — 2–5 higher-level subject areas this chunk belongs to.
  audience_level — classify the DEPTH required to make use of this chunk:
      novice       — orientation, motivation, definitions, plain-language framing.
      practitioner — how-to, patterns, trade-offs, applied guidance.
      expert       — formal methods, edge cases, proofs, internals, dense jargon.
    Pick the level the chunk best SERVES, then justify in one sentence.
  semantic_tags — short controlled tags (e.g. "governance", "provenance",
    "hazard-analysis", "taxonomy") useful as metadata filters.

Be specific and grounded in the chunk. Do not pad lists with generic terms."""

USER_TEMPLATE = """Document: {title}

<chunk>
{chunk}
</chunk>

Concepts already extracted from this chunk: {concepts}
Frameworks already linked to this chunk: {frameworks}

Produce the enrichment metadata."""


class EnrichmentAgent(BaseAgent):
    def __init__(self, config: Config | None = None, ontology: FrameworkOntology | None = None):
        cfg = config or Config()
        super().__init__(cfg)
        self.ontology = ontology or FrameworkOntology.from_json(cfg.framework_ontology_path)

    def process(self, extractions: List[DocumentExtraction]) -> List[DocumentExtraction]:
        for ex in extractions:
            for chunk in ex.chunks:
                chunk.enrichment = self._enrich(chunk)
        return extractions

    # ------------------------------------------------------------------ #
    def _enrich(self, chunk: Chunk) -> Enrichment:
        result: EnrichmentResult = self.structured(
            model=self.config.enrichment_model,
            system=SYSTEM,
            user_content=USER_TEMPLATE.format(
                title=chunk.document_title,
                chunk=chunk.text,
                concepts=", ".join(c.label for c in chunk.concepts) or "(none)",
                frameworks=", ".join(fl.framework_label for fl in chunk.framework_links) or "(none)",
            ),
            output_model=EnrichmentResult,
        )
        return Enrichment(
            summary=result.summary,
            keywords=result.keywords,
            topics=result.topics,
            audience_level=result.audience_level,
            audience_rationale=result.audience_rationale,
            semantic_tags=result.semantic_tags,
            related_concepts=self._related_concepts(chunk),
        )

    def _related_concepts(self, chunk: Chunk) -> List[str]:
        """Pull in ontology neighbours (broader/narrower/skos:related) of linked frameworks."""
        related: List[str] = []
        for fl in chunk.framework_links:
            related.extend(self.ontology.related_of(fl.framework_concept_id))
        seen = set()
        return [c for c in related if not (c in seen or seen.add(c))]
