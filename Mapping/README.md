# Avatar 2.0 — Four-Agent Semantic Ingestion Pipeline

A modular pipeline that turns a corpus of documents into a richly-linked,
provenance-tracked vector store for a semantic knowledge avatar. Four agents run
in sequence, each augmenting the same chunk objects — and all three reasoning
agents are **grounded top-down by your GraphDB `value-kb` ontology**, so the
pipeline populates and enriches your curated schema rather than inventing a
parallel one bottom-up.

```
        value-kb ontology (GraphDB)
                  │  loaded once, grounds every reasoning stage
                  ▼
 Documents ──► Extraction ──► Relationship Mining ──► Enrichment ──► Embedding
                 (1)               (3)                   (4)            (5)
            ontology-guided   links to ontology      ontology       Pinecone
             extraction       + provenance        related concepts
```

## The agents

| # | Agent | Module | Responsibility |
|---|-------|--------|----------------|
| 1 | **Extraction** | `extraction_agent.py` | Chunks each document and extracts entities, concepts, S-P-O relationships, and typed claims per chunk — **guided by the value-kb scaffold** so it uses canonical class/concept labels and known relation predicates, while still surfacing novel items as candidates for ontology growth. |

## Ontology grounding (top-down, not bottom-up)

The `value-kb` ontology is loaded **once** at pipeline start (`from_graphdb`) and
shared by extraction, mining, and enrichment:

- **Extraction** receives a compact schema scaffold (OWL classes, SKOS concepts
  with `broader` parents, and the object-property vocabulary) and extracts
  *against* it — normalizing to your canonical labels and preferred predicates.
- **Mining** links each chunk to ontology nodes by real IRI, with typed relations
  and confidence, and writes `framework ← claim ← chunk ← document` provenance.
- **Enrichment** pulls related concepts straight from the SKOS graph
  (`broader` / `narrower` / `related`).

The SPARQL that encodes your modeling conventions lives in `ontology.py`
(`Q_CONCEPTS`, `Q_TAXONOMY`, `Q_RELATED`, `Q_RELATIONS`). It uses standard
OWL/SKOS predicates; adjust those constants if value-kb models hierarchy or
concepts with custom properties.

## Setup

```bash
pip install -r requirements.txt          # GraphDB client is stdlib-only
export ANTHROPIC_API_KEY=...
export VOYAGE_API_KEY=...                 # or OPENAI_API_KEY
export PINECONE_API_KEY=...
export GRAPHDB_URL=http://localhost:7200  # or your CORS proxy endpoint
# export GRAPHDB_NAMED_GRAPH=https://enablingvalue.com/graphs/frameworks
```
| 3 | **Relationship Mining** | `relationship_mining_agent.py` | Finds cross-document links (shared entity/concept/framework), links every chunk to your framework ontology (RDSG, AICB, HSA, …) with a typed relation + confidence, and builds `framework ← claim ← chunk ← document` provenance chains. |
| 4 | **Enrichment** | `enrichment_agent.py` | Adds a summary, keywords, topics, and semantic tags; classifies each chunk by audience level with a rationale; attaches related ontology concepts via taxonomy walks. |
| 5 | **Embedding** | `embedding_agent.py` | Builds a *contextualized* embedding input (title + summary + concepts + body), embeds with a pluggable provider, flattens metadata to Pinecone-legal types, and upserts with the full chunk text. |

## Run

```python
from avatar2 import AvatarPipeline, Config, Document

pipe = AvatarPipeline(Config())
result = pipe.run(
    [Document(title="RDSG v2.0", text=open("rdsg.md").read())],
    namespace="avatar-2-0",
)
print(result.stats)
```

Or run stages individually to inspect intermediate state (see `example_usage.py`).
You can also skip stages: `pipe.run(docs, do_embedding=False)`.

## Key design choices

- **Forced structured output.** The three LLM agents expose their Pydantic schema
  as a single tool and require the model to call it (`base.py:structured`), which
  is far more reliable than parsing free-text JSON. Failed chunks degrade
  gracefully to empty results instead of killing a long run.
- **Deterministic ids.** Entities/concepts use content hashes (`stable_id`) so
  cross-document resolution and provenance work without a separate ER pass.
- **Hybrid linking.** Framework linking combines a cheap deterministic alias
  match with an LLM pass for the subtle cases and relation typing.
- **Contextual embeddings.** Chunks are embedded with orienting context prepended,
  improving retrieval recall.

## Configuration knobs (`config.py`)

- **Models** — defaults to `claude-sonnet-4-6` for all three LLM agents; drop to
  Haiku for high-volume corpora or raise to Opus for harder reasoning.
- **Embeddings** — `embedding_provider` is `"voyage"` (default), `"openai"`, or
  extend `make_embedder` for Pinecone integrated inference. **Set
  `embedding_dimension` to match your chosen model** (voyage-3.5 → 1024,
  text-embedding-3-large → 3072).
- **Chunking** — `chunk_size` / `chunk_overlap`, or replace `chunking.py` with a
  layout-aware or semantic splitter.
- **Ontology** — `ontology_source` is `"graphdb"` (default, live load from
  value-kb) or `"json"` (offline seed). `graphdb_base_url` points at GraphDB or
  your CORS proxy; `graphdb_named_graph` scopes the load to one context.
  `ontology_guided_extraction` toggles the top-down extraction scaffold, capped
  by `extraction_scaffold_limit` (for a large value-kb, pass a pre-retrieved
  shortlist into a fresh `FrameworkOntology` instead of dumping the whole graph).

## Notes & extension points

- The framework ontology in `avatar2/ontology/framework_concepts.json` is seeded
  with your signature frameworks; edit it or point at a SKOS/TTL export.
- Agents are sync for clarity. For large corpora, parallelize the per-chunk LLM
  calls with `concurrent.futures` in the extraction/enrichment loops, or batch
  via the Anthropic Message Batches API.
- Pinecone metadata is capped (~40 KB/vector); full text is truncated to
  `config.metadata_text_char_limit` and nested objects are projected to string
  lists. Provenance chains and cross-document links live in `MiningResult` — wire
  those into your GraphDB named-graph governance layer for the full knowledge graph.
```
