"""
ontology.py
===========
The framework ontology used to GROUND the pipeline top-down. It can be hydrated
two ways:

  * FrameworkOntology.from_graphdb(client)  -> live load from value-kb (default)
  * FrameworkOntology.from_json(path)       -> static seed (offline / testing)

Beyond a flat concept list it now carries the taxonomy (broader / subClassOf),
skos:related edges, and the object-property vocabulary, so the agents can reason
WITH your schema:

  * scaffold_for_prompt()    -> grounds the Extraction Agent (top-down extraction)
  * catalog_for_prompt()     -> grounds the Relationship Mining Agent's linking
  * related_of(concept_id)   -> feeds the Enrichment Agent's related concepts
  * relation_vocabulary()    -> the predicates extraction/mining should prefer

The SPARQL below uses standard OWL/SKOS predicates. If value-kb models concepts
or hierarchy with custom predicates, adjust the query constants — they are the
single place that knows your modeling conventions.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Dict, List, Optional

from .models import FrameworkConcept

# --------------------------------------------------------------------------- #
# SPARQL — the only place that encodes value-kb's modeling conventions
# --------------------------------------------------------------------------- #
PREFIXES = """PREFIX rdf:  <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX owl:  <http://www.w3.org/2002/07/owl#>
PREFIX skos: <http://www.w3.org/2004/02/skos/core#>"""

Q_CONCEPTS = PREFIXES + """
SELECT ?iri ?label ?definition ?kind WHERE {
  { ?iri a skos:Concept BIND("concept" AS ?kind) }
  UNION
  { ?iri a owl:Class    BIND("class"   AS ?kind) }
  OPTIONAL { ?iri skos:prefLabel ?pref }
  OPTIONAL { ?iri rdfs:label ?rl }
  OPTIONAL { ?iri skos:definition ?sdef }
  OPTIONAL { ?iri rdfs:comment ?cmt }
  BIND(STR(COALESCE(?pref, ?rl)) AS ?label)
  BIND(STR(COALESCE(?sdef, ?cmt, "")) AS ?definition)
  FILTER(BOUND(?label))
}"""

Q_ALIASES = PREFIXES + """
SELECT ?iri ?alias WHERE {
  ?iri skos:altLabel ?alias .
}"""

Q_TAXONOMY = PREFIXES + """
SELECT ?child ?parent WHERE {
  { ?child skos:broader ?parent } UNION { ?child rdfs:subClassOf ?parent }
  FILTER(isIRI(?parent))
}"""

Q_RELATED = PREFIXES + """
SELECT ?a ?b WHERE { ?a skos:related ?b . FILTER(isIRI(?b)) }"""

Q_RELATIONS = PREFIXES + """
SELECT ?iri ?label WHERE {
  ?iri a owl:ObjectProperty .
  OPTIONAL { ?iri rdfs:label ?l }
  BIND(STR(COALESCE(?l, ?iri)) AS ?label)
}"""


def iri_to_id(iri: str) -> str:
    """Stable, readable id from an IRI local name (fallback to a hash)."""
    local = re.split(r"[#/]", iri.rstrip("#/"))[-1]
    local = re.sub(r"[^0-9A-Za-z_]+", "_", local).strip("_")
    if local:
        return f"fw_{local}"
    return "fw_" + hashlib.sha1(iri.encode()).hexdigest()[:12]


class FrameworkOntology:
    def __init__(
        self,
        concepts: List[FrameworkConcept],
        relations: Optional[List[Dict[str, str]]] = None,
        namespace: str = "",
    ):
        self.namespace = namespace
        self.concepts: Dict[str, FrameworkConcept] = {c.id: c for c in concepts}
        self.relations: List[Dict[str, str]] = relations or []  # [{iri,label}]
        self._alias_index: Dict[str, str] = {}
        for c in concepts:
            for token in [c.label, *c.aliases]:
                if token:
                    self._alias_index[token.lower()] = c.id

    # ------------------------------------------------------------------ #
    # Constructors
    # ------------------------------------------------------------------ #
    @classmethod
    def from_json(cls, path: str | Path) -> "FrameworkOntology":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        concepts = [FrameworkConcept(**c) for c in data.get("concepts", [])]
        return cls(concepts, relations=data.get("relations", []), namespace=data.get("namespace", ""))

    @classmethod
    def from_graphdb(cls, client, named_graph: Optional[str] = None) -> "FrameworkOntology":
        """Hydrate the ontology live from value-kb."""
        if named_graph is not None:
            client.named_graph = named_graph

        concepts: Dict[str, FrameworkConcept] = {}
        for row in client.query(Q_CONCEPTS):
            iri = row["iri"]
            cid = iri_to_id(iri)
            if cid not in concepts:
                concepts[cid] = FrameworkConcept(
                    id=cid,
                    iri=iri,
                    label=row.get("label", iri),
                    definition=row.get("definition", ""),
                    kind=row.get("kind", "concept"),
                )

        for row in client.query(Q_ALIASES):
            cid = iri_to_id(row["iri"])
            if cid in concepts and row.get("alias"):
                concepts[cid].aliases.append(row["alias"])

        for row in client.query(Q_TAXONOMY):
            child, parent = iri_to_id(row["child"]), iri_to_id(row["parent"])
            if child in concepts and parent in concepts:
                concepts[child].parent = parent

        for row in client.query(Q_RELATED):
            a, b = iri_to_id(row["a"]), iri_to_id(row["b"])
            if a in concepts and b in concepts:
                concepts[a].related.append(b)

        relations = [{"iri": r["iri"], "label": r.get("label", r["iri"])} for r in client.query(Q_RELATIONS)]

        return cls(list(concepts.values()), relations=relations)

    @classmethod
    def from_triples(cls, rows: List[dict]) -> "FrameworkOntology":
        return cls([FrameworkConcept(**r) for r in rows])

    # ------------------------------------------------------------------ #
    # Lookups
    # ------------------------------------------------------------------ #
    def get(self, concept_id: str) -> Optional[FrameworkConcept]:
        return self.concepts.get(concept_id)

    def match_alias(self, text: str) -> Optional[FrameworkConcept]:
        cid = self._alias_index.get(text.strip().lower())
        return self.concepts.get(cid) if cid else None

    def related_of(self, concept_id: str) -> List[str]:
        """Labels of taxonomically/semantically related concepts (broader, narrower, related)."""
        node = self.concepts.get(concept_id)
        if not node:
            return []
        out: List[str] = []
        if node.parent and node.parent in self.concepts:
            out.append(self.concepts[node.parent].label)
        for other in self.concepts.values():
            if other.parent == concept_id:
                out.append(other.label)
        for rid in node.related:
            if rid in self.concepts:
                out.append(self.concepts[rid].label)
        seen = set()
        return [x for x in out if not (x in seen or seen.add(x))]

    def relation_vocabulary(self) -> List[str]:
        return [r["label"] for r in self.relations]

    # ------------------------------------------------------------------ #
    # Prompt renderings
    # ------------------------------------------------------------------ #
    def catalog_for_prompt(self, limit: Optional[int] = None) -> str:
        """id-stable listing for the mining agent's concept linking."""
        items = list(self.concepts.values())[: limit or len(self.concepts)]
        lines = []
        for c in items:
            alias = f" (aka {', '.join(c.aliases)})" if c.aliases else ""
            lines.append(f"- {c.id} | {c.label}{alias}: {c.definition}")
        return "\n".join(lines)

    def scaffold_for_prompt(self, limit: int = 120) -> str:
        """Compact schema view to ground top-down extraction.

        Lists OWL classes, SKOS concepts (with parents), and the object-property
        vocabulary. Capped at `limit` concepts; for a large value-kb, pass a
        pre-retrieved shortlist into a fresh FrameworkOntology instead.
        """
        classes = [c for c in self.concepts.values() if c.kind == "class"][:limit]
        concepts = [c for c in self.concepts.values() if c.kind == "concept"][:limit]
        lines: List[str] = []
        if classes:
            lines.append("CLASSES (types to recognize instances of):")
            lines += [f"  - {c.label}: {c.definition}".rstrip() for c in classes]
        if concepts:
            lines.append("CONCEPTS (canonical labels; prefer these when they match):")
            for c in concepts:
                parent = self.concepts.get(c.parent).label if c.parent in self.concepts else None
                suffix = f" [broader: {parent}]" if parent else ""
                lines.append(f"  - {c.label}{suffix}")
        rels = self.relation_vocabulary()
        if rels:
            lines.append("RELATION PREDICATES (prefer these for triples when they fit):")
            lines.append("  " + ", ".join(rels[:60]))
        return "\n".join(lines)
