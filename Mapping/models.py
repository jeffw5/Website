"""
models.py
=========
Typed data models shared by every agent in the Avatar 2.0 ingestion pipeline.

Two families of models live here:

1. "Raw*" models are the *LLM output contracts*. They deliberately carry no
   generated IDs and no provenance — the language model only has to describe
   what it found. IDs, hashes, and lineage are assigned in code so they are
   deterministic and never hallucinated.

2. The full models (Entity, Concept, Chunk, ...) are the *internal contracts*
   passed between agents. Each carries a stable ID and enough provenance to
   reconstruct where it came from.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field

# --------------------------------------------------------------------------- #
# Shared vocabularies
# --------------------------------------------------------------------------- #

AudienceLevel = Literal["novice", "practitioner", "expert"]

EntityType = Literal[
    "PERSON",
    "ORGANIZATION",
    "FRAMEWORK",
    "METHOD",
    "STANDARD",
    "TECHNOLOGY",
    "CONCEPT",
    "ARTIFACT",
    "ROLE",
    "EVENT",
    "OTHER",
]

ClaimType = Literal[
    "definition",
    "assertion",
    "causal",
    "normative",
    "comparative",
    "procedural",
    "evidential",
]


def new_id(prefix: str) -> str:
    """Short, readable, collision-resistant id, e.g. 'ent_3f9a2c'."""
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def stable_id(prefix: str, *parts: str) -> str:
    """Deterministic id derived from content — same input always yields same id.

    Used for entities/concepts so the same canonical thing resolves to one id
    even when it appears in many chunks or documents.
    """
    digest = hashlib.sha1("||".join(p.strip().lower() for p in parts).encode()).hexdigest()
    return f"{prefix}_{digest[:12]}"


# --------------------------------------------------------------------------- #
# LLM output contracts (no ids — assigned in code)
# --------------------------------------------------------------------------- #


class RawEntity(BaseModel):
    name: str
    type: EntityType = "OTHER"
    aliases: List[str] = Field(default_factory=list)
    description: Optional[str] = None
    salience: float = Field(0.5, ge=0.0, le=1.0, description="How central to the chunk.")


class RawConcept(BaseModel):
    label: str
    definition: Optional[str] = None


class RawRelationship(BaseModel):
    subject: str
    predicate: str
    object: str
    confidence: float = Field(0.7, ge=0.0, le=1.0)
    evidence: Optional[str] = Field(None, description="Verbatim span supporting the triple.")


class RawClaim(BaseModel):
    text: str
    claim_type: ClaimType = "assertion"
    subject: Optional[str] = None
    confidence: float = Field(0.7, ge=0.0, le=1.0)
    source_span: Optional[str] = None


class ExtractionResult(BaseModel):
    """What the Extraction Agent's LLM returns for a single chunk."""

    entities: List[RawEntity] = Field(default_factory=list)
    concepts: List[RawConcept] = Field(default_factory=list)
    relationships: List[RawRelationship] = Field(default_factory=list)
    claims: List[RawClaim] = Field(default_factory=list)


class EnrichmentResult(BaseModel):
    """What the Enrichment Agent's LLM returns for a single chunk."""

    summary: str = Field(..., description="One or two sentence abstract of the chunk.")
    keywords: List[str] = Field(default_factory=list)
    topics: List[str] = Field(default_factory=list)
    audience_level: AudienceLevel = "practitioner"
    audience_rationale: str = ""
    semantic_tags: List[str] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Internal contracts (carry ids + provenance)
# --------------------------------------------------------------------------- #


class Entity(BaseModel):
    id: str
    name: str
    type: EntityType = "OTHER"
    aliases: List[str] = Field(default_factory=list)
    description: Optional[str] = None
    salience: float = 0.5

    @classmethod
    def from_raw(cls, raw: RawEntity) -> "Entity":
        return cls(
            id=stable_id("ent", raw.name),
            name=raw.name,
            type=raw.type,
            aliases=raw.aliases,
            description=raw.description,
            salience=raw.salience,
        )


class Concept(BaseModel):
    id: str
    label: str
    definition: Optional[str] = None
    ontology_iri: Optional[str] = None  # populated by the Relationship Mining Agent

    @classmethod
    def from_raw(cls, raw: RawConcept) -> "Concept":
        return cls(id=stable_id("con", raw.label), label=raw.label, definition=raw.definition)


class Relationship(BaseModel):
    id: str
    subject: str
    predicate: str
    object: str
    confidence: float = 0.7
    evidence: Optional[str] = None

    @classmethod
    def from_raw(cls, raw: RawRelationship) -> "Relationship":
        return cls(
            id=new_id("rel"),
            subject=raw.subject,
            predicate=raw.predicate,
            object=raw.object,
            confidence=raw.confidence,
            evidence=raw.evidence,
        )


class Claim(BaseModel):
    id: str
    text: str
    claim_type: ClaimType = "assertion"
    subject: Optional[str] = None
    confidence: float = 0.7
    source_span: Optional[str] = None

    @classmethod
    def from_raw(cls, raw: RawClaim) -> "Claim":
        return cls(
            id=new_id("clm"),
            text=raw.text,
            claim_type=raw.claim_type,
            subject=raw.subject,
            confidence=raw.confidence,
            source_span=raw.source_span,
        )


class Enrichment(BaseModel):
    summary: str
    keywords: List[str] = Field(default_factory=list)
    topics: List[str] = Field(default_factory=list)
    audience_level: AudienceLevel = "practitioner"
    audience_rationale: str = ""
    semantic_tags: List[str] = Field(default_factory=list)
    related_concepts: List[str] = Field(
        default_factory=list,
        description="Ontology concept ids/labels attached by the Enrichment Agent.",
    )


class Chunk(BaseModel):
    id: str
    document_id: str
    document_title: str
    sequence: int
    text: str
    char_start: int
    char_end: int

    # populated by the Extraction Agent
    entities: List[Entity] = Field(default_factory=list)
    concepts: List[Concept] = Field(default_factory=list)
    relationships: List[Relationship] = Field(default_factory=list)
    claims: List[Claim] = Field(default_factory=list)

    # populated by the Relationship Mining Agent
    framework_links: List["ConceptLink"] = Field(default_factory=list)

    # populated by the Enrichment Agent
    enrichment: Optional[Enrichment] = None


class Document(BaseModel):
    id: str = Field(default_factory=lambda: new_id("doc"))
    title: str
    text: str
    source_path: Optional[str] = None
    metadata: Dict[str, str] = Field(default_factory=dict)


class DocumentExtraction(BaseModel):
    """Output of the Extraction Agent for one document."""

    document_id: str
    title: str
    source_path: Optional[str] = None
    chunks: List[Chunk] = Field(default_factory=list)
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


# --------------------------------------------------------------------------- #
# Ontology + relationship-mining contracts
# --------------------------------------------------------------------------- #


class FrameworkConcept(BaseModel):
    """A node in the user's framework ontology (RDSG, AICB, HSA, ...)."""

    id: str
    iri: str
    label: str
    aliases: List[str] = Field(default_factory=list)
    definition: str = ""
    kind: str = "concept"  # "concept" (skos:Concept) | "class" (owl:Class)
    parent: Optional[str] = None  # broader / superclass concept id
    related: List[str] = Field(default_factory=list)  # skos:related concept ids


class ConceptLink(BaseModel):
    """A typed link from chunk content to a framework concept, with confidence."""

    framework_concept_id: str
    framework_label: str
    framework_iri: str
    relation: str = "mentions"  # mentions | defines | applies | extends | critiques
    confidence: float = 0.7
    evidence: Optional[str] = None


class RawConceptLink(BaseModel):
    """LLM output contract for one framework link (resolved to ids in code)."""

    framework_concept_id: str
    relation: str = "mentions"
    confidence: float = Field(0.7, ge=0.0, le=1.0)
    evidence: Optional[str] = None


class ConceptLinkResult(BaseModel):
    links: List[RawConceptLink] = Field(default_factory=list)


class CrossDocumentLink(BaseModel):
    """A connection discovered between two chunks in different documents."""

    id: str = Field(default_factory=lambda: new_id("xdoc"))
    source_chunk_id: str
    target_chunk_id: str
    source_document_id: str
    target_document_id: str
    relation: str  # shared_entity | shared_concept | shared_framework | elaborates | contradicts
    pivot: str  # the entity/concept/framework label the link pivots on
    confidence: float = 0.7


class ProvenanceChain(BaseModel):
    """Lineage: framework concept <- claim <- chunk <- document."""

    id: str = Field(default_factory=lambda: new_id("prov"))
    framework_concept_id: str
    framework_label: str
    claim_id: str
    claim_text: str
    chunk_id: str
    document_id: str
    document_title: str
    relation: str
    confidence: float


class MiningResult(BaseModel):
    """Corpus-level output of the Relationship Mining Agent."""

    cross_document_links: List[CrossDocumentLink] = Field(default_factory=list)
    provenance_chains: List[ProvenanceChain] = Field(default_factory=list)
    # chunks are mutated in place (framework_links populated); kept here for convenience
    linked_chunk_count: int = 0


# resolve forward reference Chunk -> ConceptLink
Chunk.model_rebuild()
